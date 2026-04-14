package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.isSuccess
import kotlin.coroutines.cancellation.CancellationException

/**
 * Thin REST client for `docs/openapi.yaml` (`IMP-070`).
 * [origin] is deployment origin only (no `/api/v1` suffix).
 */
class NutonicApiClient(
    origin: String,
    private val http: HttpClient = createNutonicHttpClient(),
) {
    private val originTrimmed = origin.trimEnd('/')

    fun close() {
        http.close()
    }

    suspend fun getHealth(): ApiResult<HealthResponse> = getJson("$originTrimmed/api/v1/health")

    suspend fun getConfig(): ApiResult<ConfigResponse> = getJson("$originTrimmed/api/v1/config")

    suspend fun getMaps(): ApiResult<List<MapSummary>> = getJson("$originTrimmed/api/v1/maps")

    /**
     * Hydration manifest (`GET /api/v1/cache/manifest`, IMP-080). Pass prior **ETag** for **304** handling.
     */
    suspend fun getCacheManifest(ifNoneMatch: String?): ApiResult<ManifestFetchOutcome> =
        try {
            val response: HttpResponse =
                http.get("$originTrimmed/api/v1/cache/manifest") {
                    if (!ifNoneMatch.isNullOrBlank()) {
                        header(HttpHeaders.IfNoneMatch, ifNoneMatch)
                    }
                }
            when {
                response.status == HttpStatusCode.NotModified ->
                    ApiResult.Ok(ManifestFetchOutcome.NotModified)

                response.status.isSuccess() -> {
                    val etag = response.headers[HttpHeaders.ETag].orEmpty()
                    val body = response.body<CacheManifestDocument>()
                    ApiResult.Ok(ManifestFetchOutcome.Fresh(document = body, etag = etag))
                }

                else -> {
                    val text = runCatching { response.bodyAsText() }.getOrNull()
                    val featureOff =
                        runCatching {
                            if (text.isNullOrBlank()) {
                                null
                            } else {
                                NutonicJson.decodeFromString(FeatureDisabledError.serializer(), text)
                            }
                        }.getOrNull()
                    ApiResult.HttpFailure(
                        response.status.value,
                        stubUserMessageForStatus(response.status.value, featureOff),
                        featureOff,
                    )
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    suspend fun postAuthToken(): ApiResult<TokenResponse> = postJson("$originTrimmed/api/v1/auth/token")

    suspend fun getDebugSession(bearerAccessToken: String): ApiResult<DebugSessionResponse> =
        getJson("$originTrimmed/api/v1/debug/session") {
            header("Authorization", "Bearer $bearerAccessToken")
        }

    suspend fun getLeaderboard(mapId: String): ApiResult<List<CommunityLeaderboardRow>> = getJson(leaderboardUrl(mapId))

    /** IMP-081: fetch versioned still bytes (`GET /api/v1/bundles/{bundle_id}`). */
    suspend fun getBundleStill(bundleId: String): ApiResult<ByteArray> =
        try {
            val url = "$originTrimmed/api/v1/bundles/${encodePathSegment(bundleId)}"
            val response: HttpResponse = http.get(url)
            when {
                response.status.isSuccess() -> ApiResult.Ok(response.body())
                else ->
                    ApiResult.HttpFailure(
                        response.status.value,
                        stubUserMessageForStatus(response.status.value, null),
                        null,
                    )
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    /**
     * Fetch arbitrary bytes (e.g. manifest [still_http_url] CDN still). Same [HttpClient] as other calls.
     */
    suspend fun getHttpBytes(url: String): ApiResult<ByteArray> =
        try {
            val response: HttpResponse = http.get(url.trim())
            when {
                response.status.isSuccess() -> ApiResult.Ok(response.body())
                else ->
                    ApiResult.HttpFailure(
                        response.status.value,
                        stubUserMessageForStatus(response.status.value, null),
                        null,
                    )
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    suspend fun postGuessRecord(
        mapId: String,
        body: GuessRecordIn,
        bearerAccessToken: String,
        idempotencyKey: String? = null,
    ): ApiResult<GuessRecordOut> =
        try {
            val response: HttpResponse =
                http.post(
                    originTrimmed.trimEnd('/') + "/api/v1/maps/" + encodePathSegment(mapId) + "/guesses/record",
                ) {
                    header("Authorization", "Bearer $bearerAccessToken")
                    if (!idempotencyKey.isNullOrBlank()) {
                        header("Idempotency-Key", idempotencyKey)
                    }
                    setBody(body)
                }
            decodeResponse(response)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    suspend fun postLeaderboard(
        mapId: String,
        body: CommunityLeaderboardPostBody,
        bearerAccessToken: String,
        idempotencyKey: String? = null,
    ): ApiResult<CommunityLeaderboardRow> =
        try {
            val response: HttpResponse =
                http.post(leaderboardUrl(mapId)) {
                    header("Authorization", "Bearer $bearerAccessToken")
                    if (!idempotencyKey.isNullOrBlank()) {
                        header("Idempotency-Key", idempotencyKey)
                    }
                    setBody(body)
                }
            decodeResponse(response)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    suspend fun postRankedRoundStart(
        body: RankedRoundStartIn,
        bearerAccessToken: String,
    ): ApiResult<RankedRoundStartOut> =
        try {
            val response: HttpResponse =
                http.post(originTrimmed.trimEnd('/') + "/api/v1/ranked/rounds/start") {
                    header("Authorization", "Bearer $bearerAccessToken")
                    setBody(body)
                }
            decodeResponse(response)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    suspend fun postRankedRoundSubmit(
        roundId: String,
        body: RankedSubmitIn,
        bearerAccessToken: String,
        idempotencyKey: String,
    ): ApiResult<RankedSubmitOut> =
        try {
            val url =
                originTrimmed.trimEnd('/') +
                    "/api/v1/ranked/rounds/" +
                    encodePathSegment(roundId) +
                    "/submit"
            val response: HttpResponse =
                http.post(url) {
                    header("Authorization", "Bearer $bearerAccessToken")
                    header("Idempotency-Key", idempotencyKey)
                    setBody(body)
                }
            decodeResponse(response)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    suspend fun postRankedForfeitIntegrity(
        roundId: String,
        body: RankedForfeitIn,
        bearerAccessToken: String,
    ): ApiResult<RankedForfeitOut> =
        try {
            val url =
                originTrimmed.trimEnd('/') +
                    "/api/v1/ranked/rounds/" +
                    encodePathSegment(roundId) +
                    "/forfeit-ranked-integrity"
            val response: HttpResponse =
                http.post(url) {
                    header("Authorization", "Bearer $bearerAccessToken")
                    setBody(body)
                }
            decodeResponse(response)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    private fun leaderboardUrl(mapId: String): String =
        originTrimmed.trimEnd('/') + "/api/v1/maps/" + encodePathSegment(mapId) + "/leaderboard"

    private fun encodePathSegment(segment: String): String =
        buildString(segment.length * 3) {
            for (b in segment.encodeToByteArray()) {
                val c = b.toInt() and 0xff
                when (c) {
                    in 0x41..0x5A,
                    in 0x61..0x7a,
                    in 0x30..0x39,
                    0x2d,
                    0x5f,
                    0x2e,
                    0x7e,
                    -> append(c.toChar())
                    else ->
                        append('%')
                            .append(c.toString(16).uppercase().padStart(2, '0'))
                }
            }
        }

    private suspend inline fun <reified T> getJson(
        url: String,
        crossinline configure: HttpRequestBuilder.() -> Unit = {},
    ): ApiResult<T> =
        try {
            val response =
                http.get(url) {
                    configure()
                }
            decodeResponse(response)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    private suspend inline fun <reified T> postJson(url: String): ApiResult<T> =
        try {
            val response = http.post(url)
            decodeResponse(response)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ApiResult.NetworkFailure(e.message ?: e::class.simpleName ?: "network")
        }

    private suspend inline fun <reified T> decodeResponse(response: HttpResponse): ApiResult<T> =
        when {
            response.status.isSuccess() -> ApiResult.Ok(response.body())
            response.status == HttpStatusCode.NotImplemented ->
                ApiResult.HttpFailure(
                    response.status.value,
                    stubUserMessageForStatus(response.status.value),
                    null,
                )

            else -> {
                val text = runCatching { response.bodyAsText() }.getOrNull()
                val featureOff =
                    runCatching {
                        if (text.isNullOrBlank()) {
                            null
                        } else {
                            NutonicJson.decodeFromString(FeatureDisabledError.serializer(), text)
                        }
                    }.getOrNull()
                ApiResult.HttpFailure(
                    response.status.value,
                    stubUserMessageForStatus(response.status.value, featureOff),
                    featureOff,
                )
            }
        }
}

sealed class ApiResult<out T> {
    data class Ok<T>(
        val value: T,
    ) : ApiResult<T>()

    data class HttpFailure(
        val statusCode: Int,
        val userMessage: String,
        val featureDisabled: FeatureDisabledError? = null,
    ) : ApiResult<Nothing>()

    data class NetworkFailure(
        val debugMessage: String,
    ) : ApiResult<Nothing>()
}

/** Short copy for UI while themed retry flows land (`rules/08`, `IMP-070`). */
fun stubUserMessageForStatus(
    statusCode: Int,
    featureDisabled: FeatureDisabledError? = null,
): String =
    when {
        featureDisabled != null ->
            "This server has ${featureDisabled.feature} turned off. Try another build or ask the host to enable it."

        statusCode == 401 -> "Session missing or expired. Refresh your token and try again."
        statusCode == 403 -> "The server declined this action for this deployment."
        statusCode == 404 -> "That endpoint or map was not found."
        statusCode == 429 -> "Too many requests. Wait a moment and try again."
        statusCode in 500..599 -> "Server hiccup. Retry in a few seconds."
        statusCode == 501 -> "That feature is not implemented on this server yet."
        else -> "Request failed (HTTP $statusCode)."
    }
