package com.nutonic.leaderboard

import com.nutonic.api.ApiResult
import com.nutonic.api.GuessRecordIn
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.NutonicJson
import com.nutonic.persistence.Utf8BlobStore
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.datetime.Clock
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.random.Random

private const val MAX_OUTBOX_ROWS = 120

private val backoffMs =
    longArrayOf(
        1_000L,
        2_000L,
        4_000L,
        8_000L,
        15_000L,
        30_000L,
        60_000L,
        120_000L,
    )

@Serializable
private data class GuessRecordOutboxEnvelope(
    val rows: List<GuessRecordOutboxRow> = emptyList(),
)

@Serializable
data class GuessRecordOutboxRow(
    @SerialName("idempotency_key") val idempotencyKey: String,
    @SerialName("map_id") val mapId: String,
    val payload: GuessRecordIn,
    @SerialName("attempt_count") val attemptCount: Int = 0,
    @SerialName("next_attempt_at_epoch_ms") val nextAttemptAtEpochMs: Long = 0L,
    @SerialName("last_error") val lastError: String? = null,
    @SerialName("created_at_epoch_ms") val createdAtEpochMs: Long,
    @SerialName("last_attempt_at_epoch_ms") val lastAttemptAtEpochMs: Long? = null,
)

/**
 * Persists non-ranked guess POST payloads and drains them when the network allows
 * (publishable plan §5.1 — single JSON blob, bounded queue).
 */
class GuessRecordOutboxRepository(
    private val blob: Utf8BlobStore,
) {
    private val mutex = Mutex()

    suspend fun enqueueOrReplace(
        mapId: String,
        idempotencyKey: String,
        payload: GuessRecordIn,
    ) {
        mutex.withLock {
            val rows = loadEnvelope().rows.toMutableList()
            rows.removeAll { it.idempotencyKey == idempotencyKey }
            val now = Clock.System.now().toEpochMilliseconds()
            rows.add(
                0,
                GuessRecordOutboxRow(
                    idempotencyKey = idempotencyKey,
                    mapId = mapId,
                    payload = payload,
                    attemptCount = 0,
                    nextAttemptAtEpochMs = 0L,
                    lastError = null,
                    createdAtEpochMs = now,
                    lastAttemptAtEpochMs = null,
                ),
            )
            while (rows.size > MAX_OUTBOX_ROWS) {
                rows.removeAt(rows.lastIndex)
            }
            saveEnvelope(GuessRecordOutboxEnvelope(rows))
        }
    }

    /**
     * Sends due rows until none remain or auth/network blocks progress.
     */
    suspend fun flushPending(nutonicApiClient: NutonicApiClient): String? =
        mutex.withLock {
            var lastMessage: String? = null
            repeat(32) {
                val now = Clock.System.now().toEpochMilliseconds()
                val row =
                    loadEnvelope()
                        .rows
                        .filter { it.nextAttemptAtEpochMs <= now }
                        .minByOrNull { it.createdAtEpochMs }
                        ?: return@withLock lastMessage

                val token =
                    when (val t = nutonicApiClient.postAuthToken()) {
                        is ApiResult.Ok -> t.value.accessToken
                        is ApiResult.HttpFailure -> {
                            rescheduleLocked(row, "Sign-in failed: ${t.userMessage}")
                            return@withLock "Saved locally; will retry sign-in."
                        }
                        is ApiResult.NetworkFailure -> {
                            rescheduleLocked(row, t.debugMessage)
                            return@withLock "Saved locally; offline — will retry."
                        }
                    }

                val result =
                    nutonicApiClient.postGuessRecord(
                        mapId = row.mapId,
                        body = row.payload,
                        bearerAccessToken = token,
                        idempotencyKey = row.idempotencyKey,
                    )

                when (result) {
                    is ApiResult.Ok -> {
                        removeRowLocked(row.idempotencyKey)
                        lastMessage = "Score synced with server."
                    }
                    is ApiResult.HttpFailure ->
                        when (result.statusCode) {
                            409 -> {
                                removeRowLocked(row.idempotencyKey)
                                lastMessage = "Score synced with server."
                            }
                            in 500..599 -> {
                                rescheduleLocked(row, result.userMessage)
                                lastMessage = "Saved locally; server busy — will retry."
                            }
                            in 400..499 -> {
                                removeRowLocked(row.idempotencyKey)
                                lastMessage = "Could not upload score: ${result.userMessage}"
                            }
                            else -> {
                                rescheduleLocked(row, result.userMessage)
                                lastMessage = "Saved locally; will retry."
                            }
                        }
                    is ApiResult.NetworkFailure -> {
                        rescheduleLocked(row, result.debugMessage)
                        lastMessage = "Saved locally; offline — will retry."
                    }
                }
            }
            lastMessage
        }

    private suspend fun loadEnvelope(): GuessRecordOutboxEnvelope {
        val raw = blob.load() ?: return GuessRecordOutboxEnvelope()
        return runCatching {
            NutonicJson.decodeFromString(GuessRecordOutboxEnvelope.serializer(), raw)
        }.getOrElse { GuessRecordOutboxEnvelope() }
    }

    private suspend fun saveEnvelope(env: GuessRecordOutboxEnvelope) {
        blob.save(NutonicJson.encodeToString(GuessRecordOutboxEnvelope.serializer(), env))
    }

    private suspend fun removeRowLocked(idempotencyKey: String) {
        val rows = loadEnvelope().rows.toMutableList()
        rows.removeAll { it.idempotencyKey == idempotencyKey }
        saveEnvelope(GuessRecordOutboxEnvelope(rows))
    }

    private suspend fun rescheduleLocked(
        row: GuessRecordOutboxRow,
        error: String,
    ) {
        val rows = loadEnvelope().rows.toMutableList()
        val idx = rows.indexOfFirst { it.idempotencyKey == row.idempotencyKey }
        if (idx < 0) {
            return
        }
        val nextAttempt = row.attemptCount + 1
        if (nextAttempt >= 24) {
            rows.removeAt(idx)
            saveEnvelope(GuessRecordOutboxEnvelope(rows))
            return
        }
        val delayIdx = nextAttempt.coerceAtMost(backoffMs.lastIndex)
        val base = backoffMs[delayIdx]
        val jitter = Random.nextLong(0, 500L)
        val now = Clock.System.now().toEpochMilliseconds()
        rows[idx] =
            row.copy(
                attemptCount = nextAttempt,
                nextAttemptAtEpochMs = now + base + jitter,
                lastError = error,
                lastAttemptAtEpochMs = now,
            )
        saveEnvelope(GuessRecordOutboxEnvelope(rows))
    }
}
