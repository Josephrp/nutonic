package com.nutonic.shell

import com.nutonic.api.MapSummary
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.ApiResult
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.cache.ManifestSyncResult

internal fun manifestLineForSync(m: ManifestSyncResult): String =
    when (m) {
        is ManifestSyncResult.Updated ->
            "Manifest: updated ${m.document.contentVersion} (ETag ${m.etag.take(16)}…)"
        is ManifestSyncResult.NotModified ->
            "Manifest: up to date (${m.document.contentVersion})"
        is ManifestSyncResult.UsedStaleCache ->
            "Manifest: using cached ${m.document.contentVersion} (${m.reason})"
        is ManifestSyncResult.Failed -> "Manifest: ${m.reason}"
    }

internal fun mapsFromManifestSync(m: ManifestSyncResult): List<MapSummary>? =
    when (m) {
        is ManifestSyncResult.Updated -> m.document.maps
        is ManifestSyncResult.NotModified -> m.document.maps
        is ManifestSyncResult.UsedStaleCache -> m.document.maps
        is ManifestSyncResult.Failed -> null
    }

/**
 * Single hydration pass: refresh manifest first, then use [CacheManifestDocument.maps] when present
 * so SCAN catalog tracks the same snapshot as gameplay (`rules/13`); falls back to `GET /api/v1/maps`.
 */
internal suspend fun refreshScanHubCatalog(
    client: NutonicApiClient,
    contentCacheRepository: ContentCacheRepository?,
    mapContextId: String,
    onManifestLine: (String?) -> Unit,
    onMapsStatus: (String?) -> Unit,
    onMaps: (List<MapSummary>) -> Unit,
    onMapContextSelect: (String, String?) -> Unit,
) {
    val sync = contentCacheRepository?.refreshManifest()
    onManifestLine(sync?.let(::manifestLineForSync))

    val fromManifest = sync?.let(::mapsFromManifestSync)
    if (!fromManifest.isNullOrEmpty()) {
        onMaps(fromManifest)
        onMapsStatus(null)
        val ids = fromManifest.map { it.mapId }
        if (mapContextId !in ids) {
            val first = fromManifest.first()
            onMapContextSelect(first.mapId, first.title)
        }
        return
    }

    onMapsStatus("Fetching maps…")
    when (val r = client.getMaps()) {
        is ApiResult.Ok -> {
            onMaps(r.value)
            onMapsStatus(null)
            val ids = r.value.map { it.mapId }
            if (mapContextId !in ids && r.value.isNotEmpty()) {
                val first = r.value.first()
                onMapContextSelect(first.mapId, first.title)
            }
        }

        is ApiResult.HttpFailure -> {
            onMaps(emptyList())
            onMapsStatus(r.userMessage)
            val fb = contentCacheRepository?.cachedMapsOrNull()
            if (!fb.isNullOrEmpty()) {
                onMaps(fb)
                onMapsStatus("${r.userMessage} Showing catalog from last manifest cache.")
            }
        }

        is ApiResult.NetworkFailure -> {
            onMaps(emptyList())
            onMapsStatus("Network: ${r.debugMessage}")
            val fb = contentCacheRepository?.cachedMapsOrNull()
            if (!fb.isNullOrEmpty()) {
                onMaps(fb)
                onMapsStatus("Network: ${r.debugMessage} Showing catalog from last manifest cache.")
            }
        }
    }
}

internal data class ScanMissionOption(
    val missionId: String,
    val title: String,
    val narrative: String,
)

internal fun buildScanMissionOptions(map: MapSummary?): List<ScanMissionOption> {
    val mapTitle = map?.title ?: "the selected map"
    return listOf(
        ScanMissionOption(
            missionId = "mission_recon",
            title = "Recon sweep",
            narrative = "Warm up on $mapTitle with full assists available and one primary submit.",
        ),
        ScanMissionOption(
            missionId = "mission_signal_lock",
            title = "Signal lock",
            narrative = "Balanced pass on $mapTitle with the standard SCAN loop and local rank tracking.",
        ),
        ScanMissionOption(
            missionId = "mission_quiet_vector",
            title = "Quiet vector",
            narrative = "Low-noise run on $mapTitle focused on map-reading confidence before PRO tooling.",
        ),
    )
}
