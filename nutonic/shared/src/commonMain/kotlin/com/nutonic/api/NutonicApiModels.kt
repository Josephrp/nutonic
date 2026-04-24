package com.nutonic.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class HealthResponse(
    val status: String,
)

@Serializable
data class FeatureFlags(
    val ranked: Boolean,
    @SerialName("community_lb_get") val communityLbGet: Boolean,
    @SerialName("community_lb_post") val communityLbPost: Boolean,
    @SerialName("pro_jobs") val proJobs: Boolean,
    @SerialName("guesses_record") val guessesRecord: Boolean = false,
)

@Serializable
data class ConfigResponse(
    val features: FeatureFlags,
    @SerialName("engine_version") val engineVersion: String? = null,
    @SerialName("content_version") val contentVersion: String? = null,
)

@Serializable
data class TokenResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("token_type") val tokenType: String,
    @SerialName("expires_in") val expiresIn: Int,
)

@Serializable
data class DebugSessionResponse(
    val ok: Boolean,
    @SerialName("session_id") val sessionId: String? = null,
)

@Serializable
data class CommunityLeaderboardRow(
    @SerialName("display_handle") val displayHandle: String,
    @SerialName("player_role") val playerRole: String,
    @SerialName("score_points") val scorePoints: Int,
    @SerialName("distance_km") val distanceKm: Double? = null,
)

@Serializable
data class MapSummary(
    @SerialName("map_id") val mapId: String,
    val title: String,
    @SerialName("engine_version") val engineVersion: String? = null,
    @SerialName("content_version") val contentVersion: String? = null,
)

@Serializable
data class UsefulHintsTiers(
    @SerialName("tier_1") val tier1: String? = null,
    @SerialName("tier_2") val tier2: String? = null,
    @SerialName("tier_3") val tier3: String? = null,
    @SerialName("tier_4") val tier4: String? = null,
    @SerialName("tier_5") val tier5: String? = null,
    @SerialName("tier_6") val tier6: String? = null,
)

@Serializable
data class StreetviewHintItem(
    val text: String,
    @SerialName("viewpoint_id") val viewpointId: String? = null,
    val rank: Int? = null,
)

@Serializable
data class ManifestRoundLocation(
    @SerialName("map_id") val mapId: String,
    @SerialName("location_id") val locationId: String,
    @SerialName("truth_lat") val truthLat: Double,
    @SerialName("truth_lon") val truthLon: Double,
    @SerialName("ruleset_version") val rulesetVersion: String? = null,
    @SerialName("still_bundle_id") val stillBundleId: String? = null,
    @SerialName("still_bundled_resource") val stillBundledResource: String? = null,
    @SerialName("still_http_url") val stillHttpUrl: String? = null,
    @SerialName("useful_hints") val usefulHints: UsefulHintsTiers? = null,
    @SerialName("streetview_hint_pack") val streetviewHintPack: List<StreetviewHintItem>? = null,
    @SerialName("streetview_assist_narrative") val streetviewAssistNarrative: String? = null,
    @SerialName("satellite_caption_sidecar") val satelliteCaptionSidecar: JsonObject? = null,
    @SerialName("play_budget_ms") val playBudgetMs: Int? = null,
    @SerialName("ai_marker_phase_enabled") val aiMarkerPhaseEnabled: Boolean = true,
)

@Serializable
data class AiGuessRow(
    @SerialName("map_id") val mapId: String,
    @SerialName("location_id") val locationId: String,
    @SerialName("ai_lat") val aiLat: Double,
    @SerialName("ai_lon") val aiLon: Double,
)

@Serializable
data class CacheManifestDocument(
    @SerialName("content_version") val contentVersion: String,
    @SerialName("engine_version") val engineVersion: String? = null,
    val maps: List<MapSummary>,
    val locations: List<ManifestRoundLocation> = emptyList(),
    @SerialName("ai_guesses") val aiGuesses: List<AiGuessRow> = emptyList(),
)

sealed class ManifestFetchOutcome {
    data class Fresh(
        val document: CacheManifestDocument,
        val etag: String,
    ) : ManifestFetchOutcome()

    data object NotModified : ManifestFetchOutcome()
}

@Serializable
data class CommunityLeaderboardPostBody(
    @SerialName("display_handle") val displayHandle: String,
    @SerialName("player_role") val playerRole: String,
    @SerialName("score_points") val scorePoints: Int,
    @SerialName("distance_km") val distanceKm: Double? = null,
)

@Serializable
data class FeatureDisabledError(
    val error: String,
    val feature: String,
)

@Serializable
data class GuessRecordIn(
    @SerialName("round_instance_id") val roundInstanceId: String,
    @SerialName("location_id") val locationId: String,
    @SerialName("guess_lat") val guessLat: Double,
    @SerialName("guess_lon") val guessLon: Double,
    @SerialName("client_distance_km") val clientDistanceKm: Double? = null,
    @SerialName("ruleset_version") val rulesetVersion: String? = null,
)

@Serializable
data class GuessRecordOut(
    val id: Int,
    val recorded: Boolean = true,
)

@Serializable
data class RankedRoundStartIn(
    @SerialName("map_id") val mapId: String,
)

@Serializable
data class RankedClue(
    @SerialName("map_id") val mapId: String,
    @SerialName("location_id") val locationId: String,
    @SerialName("still_bundle_id") val stillBundleId: String? = null,
    @SerialName("still_bundled_resource") val stillBundledResource: String? = null,
    @SerialName("useful_hints") val usefulHints: UsefulHintsTiers? = null,
    @SerialName("streetview_hint_pack") val streetviewHintPack: List<StreetviewHintItem>? = null,
    @SerialName("streetview_assist_narrative") val streetviewAssistNarrative: String? = null,
    @SerialName("satellite_caption_sidecar") val satelliteCaptionSidecar: JsonObject? = null,
    @SerialName("play_budget_ms") val playBudgetMs: Int? = null,
    @SerialName("ai_marker_phase_enabled") val aiMarkerPhaseEnabled: Boolean = true,
)

/** Envelope for on-disk ranked clue slices (`data/scripts/assemble_ranked_clue_pack.py`). */
@Serializable
data class RankedCluePackDocument(
    @SerialName("schema_version") val schemaVersion: String,
    val clues: List<RankedClue> = emptyList(),
    @SerialName("ai_guesses") val aiGuesses: List<AiGuessRow> = emptyList(),
)

@Serializable
data class RankedRoundStartOut(
    @SerialName("round_id") val roundId: String,
    @SerialName("round_ticket") val roundTicket: String,
    @SerialName("expires_in") val expiresIn: Int,
    val clue: RankedClue,
)

@Serializable
data class RankedSubmitIn(
    @SerialName("guess_lat") val guessLat: Double,
    @SerialName("guess_lon") val guessLon: Double,
    @SerialName("round_ticket") val roundTicket: String,
)

@Serializable
data class RankedSubmitOut(
    @SerialName("distance_km") val distanceKm: Double,
    @SerialName("score_points") val scorePoints: Int,
    val verified: Boolean = true,
)

@Serializable
data class RankedForfeitIn(
    val reason: String,
)

@Serializable
data class RankedForfeitOut(
    val ok: Boolean = true,
    val status: String,
)

@Serializable
enum class ProJobProfile {
    @SerialName("wildfire")
    WILDFIRE,

    @SerialName("oceanscout_ship_detection")
    OCEANSCOUT_SHIP_DETECTION,

    @SerialName("land_use_change")
    LAND_USE_CHANGE,

    @SerialName("flood_pulse")
    FLOOD_PULSE,

    @SerialName("brief_only")
    BRIEF_ONLY,
    ;

    fun wireToken(): String =
        when (this) {
            WILDFIRE -> "wildfire"
            OCEANSCOUT_SHIP_DETECTION -> "oceanscout_ship_detection"
            LAND_USE_CHANGE -> "land_use_change"
            FLOOD_PULSE -> "flood_pulse"
            BRIEF_ONLY -> "brief_only"
        }

    companion object {
        fun fromWireOrDefault(value: String?): ProJobProfile =
            when (value?.trim()) {
                "wildfire" -> WILDFIRE
                "oceanscout_ship_detection",
                "vessel_monitoring",
                -> OCEANSCOUT_SHIP_DETECTION
                "land_use_change" -> LAND_USE_CHANGE
                "flood_pulse" -> FLOOD_PULSE
                "brief_only" -> BRIEF_ONLY
                else -> BRIEF_ONLY
            }
    }
}

@Serializable
data class ProJobCreateIn(
    @SerialName("center_lat") val centerLat: Double,
    @SerialName("center_lon") val centerLon: Double,
    @SerialName("bbox_half_km") val bboxHalfKm: Double = 5.0,
    @SerialName("mapbox_zoom") val mapboxZoom: Int = 12,
    @SerialName("analysis_profile") val analysisProfile: ProJobProfile = ProJobProfile.BRIEF_ONLY,
    @SerialName("enable_tim") val enableTim: Boolean = false,
    @SerialName("tim_branch") val timBranch: String = "RGB_mapbox",
    @SerialName("vlm_contract_id") val vlmContractId: String = "nutonic.pro.vlm.v1_512",
    @SerialName("sentinel_fetch_mode") val sentinelFetchMode: String = "MINIMAL_RGB",
    @SerialName("datetime_interval") val datetimeInterval: String? = null,
    @SerialName("scene_id_t0") val sceneIdT0: String? = null,
    @SerialName("scene_id_t1") val sceneIdT1: String? = null,
    @SerialName("scene_id_t2") val sceneIdT2: String? = null,
)

@Serializable
data class ProJobCreateOut(
    @SerialName("job_id") val jobId: String,
    val status: String = "queued",
    @SerialName("inference_upstream_ok") val inferenceUpstreamOk: Boolean? = null,
    @SerialName("materialization_ok") val materializationOk: Boolean? = null,
    @SerialName("materialization_id") val materializationId: String? = null,
    @SerialName("cache_key") val cacheKey: String? = null,
    @SerialName("materialization_error") val materializationError: String? = null,
)

@Serializable
data class ProArtifactRef(
    @SerialName("artifact_id") val artifactId: String,
    val kind: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    val profile: String? = null,
    @SerialName("download_url") val downloadUrl: String? = null,
)

@Serializable
data class ProBriefSection(
    val title: String,
    val body: String,
    val confidence: String? = null,
)

@Serializable
data class ProOnDevicePayload(
    @SerialName("brief_sections") val briefSections: List<ProBriefSection> = emptyList(),
    @SerialName("overlay_refs") val overlayRefs: List<ProArtifactRef> = emptyList(),
    @SerialName("confidence_summary") val confidenceSummary: String? = null,
)

@Serializable
data class ProJobStatusOut(
    @SerialName("job_id") val jobId: String,
    val status: String,
    @SerialName("status_reason") val statusReason: String? = null,
    @SerialName("error_class") val errorClass: String? = null,
    @SerialName("error_detail") val errorDetail: String? = null,
    @SerialName("progress_pct") val progressPct: Int? = null,
    val profile: String? = null,
    @SerialName("analysis_profile") val analysisProfile: String? = null,
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("finished_at") val finishedAt: String? = null,
    val artifacts: List<ProArtifactRef>? = null,
    @SerialName("analysis_artifacts") val analysisArtifacts: List<ProArtifactRef>? = null,
    @SerialName("brief_artifacts") val briefArtifacts: List<ProArtifactRef>? = null,
    @SerialName("scene_provenance") val sceneProvenance: JsonObject? = null,
    @SerialName("on_device_payload") val onDevicePayload: ProOnDevicePayload? = null,
    @SerialName("bundle_download_url") val bundleDownloadUrl: String? = null,
    @SerialName("materialization_id") val materializationId: String? = null,
    @SerialName("cache_key") val cacheKey: String? = null,
    @SerialName("materialization_summary") val materializationSummary: JsonObject? = null,
)

@Serializable
data class ProJobCancelOut(
    val ok: Boolean = true,
    val status: String,
)
