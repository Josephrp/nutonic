package com.nutonic.cache

import com.nutonic.api.ApiResult
import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.ManifestFetchOutcome
import com.nutonic.api.MapSummary
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.stubUserMessageForStatus

/**
 * Syncs **`GET /api/v1/cache/manifest`** with local envelope (`rules/13`, IMP-080).
 * On transport failure, callers may still read [cachedDocument] / [cachedMapsOrNull].
 */
class ContentCacheRepository(
    private val client: NutonicApiClient,
    private val store: ManifestBlobStore,
) {
    suspend fun refreshManifest(): ManifestSyncResult {
        val previous = store.loadEnvelope()
        return when (val net = client.getCacheManifest(previous?.etag)) {
            is ApiResult.Ok ->
                when (val outcome = net.value) {
                    is ManifestFetchOutcome.NotModified -> {
                        val prev = previous
                        if (prev == null) {
                            ManifestSyncResult.Failed(
                                "Server returned 304 Not Modified but no local manifest is cached yet.",
                            )
                        } else {
                            ManifestSyncResult.NotModified(
                                document = prev.document,
                                etag = prev.etag,
                            )
                        }
                    }

                    is ManifestFetchOutcome.Fresh -> {
                        val env =
                            PersistedManifestEnvelope(
                                etag = outcome.etag,
                                contentVersion = outcome.document.contentVersion,
                                document = outcome.document,
                            )
                        store.saveEnvelope(env)
                        ManifestSyncResult.Updated(
                            document = outcome.document,
                            etag = outcome.etag,
                        )
                    }
                }

            is ApiResult.HttpFailure -> offlineOrError(previous, stubUserMessageForStatus(net.statusCode, net.featureDisabled))

            is ApiResult.NetworkFailure -> offlineOrError(previous, net.debugMessage)
        }
    }

    suspend fun cachedDocument(): CacheManifestDocument? {
        return cachedDocumentWithMergeOutcome()?.document
    }

    suspend fun cachedDocumentWithMergeOutcome(): CachedDocumentWithMergeOutcome? {
        val shipped = readShippedFullManifest()
        val env = store.loadEnvelope()
        if (env == null) {
            val doc = shipped ?: return null
            return CachedDocumentWithMergeOutcome(
                document = doc,
                mergeOutcome = ShippedManifestMergeOutcome.OVERLAID_FROM_SHIPPED,
                shippedContentVersion = shipped.contentVersion,
            )
        }
        val merged = mergeShippedRoundTruthDetailed(env.document, shipped)
        return CachedDocumentWithMergeOutcome(
            document = merged.document,
            mergeOutcome = merged.outcome,
            shippedContentVersion = merged.shippedContentVersion,
        )
    }

    suspend fun cachedMapsOrNull(): List<MapSummary>? = cachedDocument()?.maps

    private fun offlineOrError(
        previous: PersistedManifestEnvelope?,
        message: String,
    ): ManifestSyncResult =
        if (previous != null) {
            ManifestSyncResult.UsedStaleCache(
                document = previous.document,
                etag = previous.etag,
                reason = message,
            )
        } else {
            ManifestSyncResult.Failed(message)
        }
}

data class CachedDocumentWithMergeOutcome(
    val document: CacheManifestDocument,
    val mergeOutcome: ShippedManifestMergeOutcome,
    val shippedContentVersion: String? = null,
)

sealed class ManifestSyncResult {
    data class Updated(
        val document: CacheManifestDocument,
        val etag: String,
    ) : ManifestSyncResult()

    data class NotModified(
        val document: CacheManifestDocument,
        val etag: String,
    ) : ManifestSyncResult()

    data class UsedStaleCache(
        val document: CacheManifestDocument,
        val etag: String,
        val reason: String,
    ) : ManifestSyncResult()

    data class Failed(
        val reason: String,
    ) : ManifestSyncResult()
}
