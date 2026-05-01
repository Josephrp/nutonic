package com.nutonic.leaderboard

import com.nutonic.api.NutonicJson
import com.nutonic.persistence.Utf8BlobStore
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class LocalNonRankedLeaderboardRow(
    @SerialName("round_instance_id") val roundInstanceId: String,
    @SerialName("map_id") val mapId: String,
    @SerialName("location_id") val locationId: String,
    @SerialName("player_role") val playerRole: String,
    /** Display handle used when posting community boards / sharing scorecards. */
    @SerialName("display_handle") val displayHandle: String = "",
    /** e.g. `HUMAN_VS_AI` for filters (`rules/05`). */
    @SerialName("matchup_type") val matchupType: String,
    @SerialName("human_distance_km") val humanDistanceKm: Double,
    @SerialName("human_score_points") val humanScorePoints: Int,
    @SerialName("ai_distance_to_truth_km") val aiDistanceToTruthKm: Double?,
    @SerialName("guess_lat") val guessLat: Double,
    @SerialName("guess_lon") val guessLon: Double,
    @SerialName("saved_at_epoch_ms") val savedAtEpochMs: Long,
    @SerialName("ruleset_version") val rulesetVersion: String? = null,
)

@Serializable
private data class LocalNonRankedLeaderboardEnvelope(
    val rows: List<LocalNonRankedLeaderboardRow> = emptyList(),
)

/**
 * Device-local per-map history (`rules/05`, `IMP-083`); optional community POST stays separate.
 */
class LocalNonRankedLeaderboardRepository(
    private val blob: Utf8BlobStore,
) {
    suspend fun appendRow(row: LocalNonRankedLeaderboardRow) {
        val current = loadEnvelope().rows.toMutableList()
        if (current.any { it.roundInstanceId == row.roundInstanceId }) {
            return
        }
        current.add(0, row)
        saveEnvelope(LocalNonRankedLeaderboardEnvelope(current))
    }

    suspend fun rowsForMap(mapId: String): List<LocalNonRankedLeaderboardRow> = loadEnvelope().rows.filter { it.mapId == mapId }

    suspend fun latestForMap(mapId: String): LocalNonRankedLeaderboardRow? = rowsForMap(mapId).firstOrNull()

    private suspend fun loadEnvelope(): LocalNonRankedLeaderboardEnvelope {
        val raw = blob.load() ?: return LocalNonRankedLeaderboardEnvelope()
        return runCatching {
            NutonicJson.decodeFromString(LocalNonRankedLeaderboardEnvelope.serializer(), raw)
        }.getOrElse { LocalNonRankedLeaderboardEnvelope() }
    }

    private suspend fun saveEnvelope(env: LocalNonRankedLeaderboardEnvelope) {
        blob.save(NutonicJson.encodeToString(LocalNonRankedLeaderboardEnvelope.serializer(), env))
    }
}
