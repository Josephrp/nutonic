package com.nutonic.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

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
    @SerialName("play_budget_ms") val playBudgetMs: Int? = null,
    @SerialName("ai_marker_phase_enabled") val aiMarkerPhaseEnabled: Boolean = true,
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
