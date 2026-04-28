package com.nutonic.cache

import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.ManifestRoundLocation
import com.nutonic.map.LatLon

/** First published round row for a map id (solo default). */
fun CacheManifestDocument.locationForMap(mapId: String): ManifestRoundLocation? = locations.firstOrNull { it.mapId == mapId }

data class ProOverlayGuess(
    val mapId: String,
    val locationId: String? = null,
    val coordinates: LatLon,
    val jobId: String,
    val profile: String,
    val artifactId: String? = null,
) {
    val sourceLabel: String
        get() =
            buildString {
                append("PRO run")
                if (jobId.isNotBlank()) {
                    append(" ")
                    append(jobId.take(8))
                }
                if (profile.isNotBlank()) {
                    append(" · ")
                    append(profile)
                }
                artifactId?.takeIf { it.isNotBlank() }?.let {
                    append(" · ")
                    append(it)
                }
            }
}

class ProOverlayGuessRepository {
    private val guesses = mutableMapOf<Pair<String, String?>, ProOverlayGuess>()

    fun publish(guess: ProOverlayGuess) {
        guesses[guess.mapId to guess.locationId] = guess
    }

    fun clear(
        mapId: String,
        locationId: String? = null,
    ) {
        guesses.remove(mapId to locationId)
    }

    fun overlayFor(
        mapId: String,
        locationId: String,
    ): ProOverlayGuess? = guesses[mapId to locationId] ?: guesses[mapId to null]

    fun all(): List<ProOverlayGuess> = guesses.values.toList()
}

/**
 * AI marker provenance for gameplay. PRO outputs may be exposed only through an explicit
 * overlay source; they never mutate the shipped manifest `ai_guesses`.
 */
data class AiGuessResolution(
    val coordinates: LatLon,
    val source: String,
)

/**
 * Resolves precomputed AI coordinates from manifest `ai_guesses` (`IMP-082`) plus optional
 * user-selected PRO overlays kept separate from the published manifest.
 */
class AiGuessStore(
    private val document: CacheManifestDocument,
    private val proOverlayGuessRepository: ProOverlayGuessRepository? = null,
) {
    fun coordinates(
        mapId: String,
        locationId: String,
    ): LatLon? = resolution(mapId, locationId)?.coordinates

    fun resolution(
        mapId: String,
        locationId: String,
    ): AiGuessResolution? {
        proOverlayGuessRepository?.overlayFor(mapId, locationId)?.let {
            return AiGuessResolution(coordinates = it.coordinates, source = it.sourceLabel)
        }
        return document.aiGuesses
            .firstOrNull { it.mapId == mapId && it.locationId == locationId }
            ?.let { AiGuessResolution(coordinates = LatLon(latitude = it.aiLat, longitude = it.aiLon), source = "manifest") }
    }
}

fun ManifestRoundLocation.truthLatLon(): LatLon = LatLon(latitude = truthLat, longitude = truthLon)
