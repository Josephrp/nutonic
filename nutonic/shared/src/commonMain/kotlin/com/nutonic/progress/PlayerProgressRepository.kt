package com.nutonic.progress

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.nutonic.api.NutonicJson
import com.nutonic.persistence.Utf8BlobStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

private const val MAX_MAPS_TRACKED = 200

@Serializable
data class PlayerProgressState(
    @SerialName("rounds_completed") val roundsCompleted: Int = 0,
    @SerialName("lifetime_score_points") val lifetimeScorePoints: Long = 0,
    @SerialName("maps_played") val mapsPlayed: List<String> = emptyList(),
    @SerialName("screen_visit_counts") val screenVisitCounts: Map<String, Int> = emptyMap(),
    @SerialName("last_round_map_id") val lastRoundMapId: String? = null,
    @SerialName("last_round_score_points") val lastRoundScorePoints: Int? = null,
    @SerialName("last_round_at_epoch_ms") val lastRoundAtEpochMs: Long? = null,
)

@Serializable
private data class PlayerProgressEnvelope(
    val progress: PlayerProgressState = PlayerProgressState(),
)

/**
 * Device-local career stats and lightweight screen analytics (no server requirement).
 */
class PlayerProgressRepository(
    private val blob: Utf8BlobStore,
    private val scope: CoroutineScope,
) {
    private var state by mutableStateOf(PlayerProgressState())

    val progress: PlayerProgressState
        get() = state

    suspend fun hydrate() {
        val raw = blob.load() ?: return
        val env =
            runCatching {
                NutonicJson.decodeFromString(PlayerProgressEnvelope.serializer(), raw)
            }.getOrNull()
        if (env != null) {
            state = env.progress
        }
    }

    fun recordScreenVisit(screenId: String) {
        val key = screenId.trim().lowercase()
        if (key.isEmpty()) return
        val nextCount = (state.screenVisitCounts[key] ?: 0) + 1
        state =
            state.copy(
                screenVisitCounts = state.screenVisitCounts + (key to nextCount),
            )
        persistAsync()
    }

    fun recordNonRankedRoundComplete(
        mapId: String,
        scorePoints: Int,
        nowEpochMs: Long,
    ) {
        val maps =
            buildList {
                add(mapId)
                state.mapsPlayed.forEach { m ->
                    if (m != mapId) add(m)
                }
            }.take(MAX_MAPS_TRACKED)
        state =
            state.copy(
                roundsCompleted = state.roundsCompleted + 1,
                lifetimeScorePoints = state.lifetimeScorePoints + scorePoints.coerceAtLeast(0),
                mapsPlayed = maps,
                lastRoundMapId = mapId,
                lastRoundScorePoints = scorePoints,
                lastRoundAtEpochMs = nowEpochMs,
            )
        persistAsync()
    }

    private fun persistAsync() {
        val snap = state
        scope.launch {
            blob.save(NutonicJson.encodeToString(PlayerProgressEnvelope.serializer(), PlayerProgressEnvelope(snap)))
        }
    }
}
