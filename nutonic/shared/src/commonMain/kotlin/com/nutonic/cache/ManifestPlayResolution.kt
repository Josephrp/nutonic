package com.nutonic.cache

import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.ManifestRoundLocation
import com.nutonic.map.LatLon

/** First published round row for a map id (solo default). */
fun CacheManifestDocument.locationForMap(mapId: String): ManifestRoundLocation? = locations.firstOrNull { it.mapId == mapId }

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
    private val proOverlayGuesses: Map<Pair<String, String>, LatLon> = emptyMap(),
) {
    fun coordinates(
        mapId: String,
        locationId: String,
    ): LatLon? = resolution(mapId, locationId)?.coordinates

    fun resolution(
        mapId: String,
        locationId: String,
    ): AiGuessResolution? {
        val key = mapId to locationId
        proOverlayGuesses[key]?.let {
            return AiGuessResolution(coordinates = it, source = "PRO run")
        }
        return document.aiGuesses
            .firstOrNull { it.mapId == mapId && it.locationId == locationId }
            ?.let { AiGuessResolution(coordinates = LatLon(latitude = it.aiLat, longitude = it.aiLon), source = "manifest") }
    }
}

fun ManifestRoundLocation.truthLatLon(): LatLon = LatLon(latitude = truthLat, longitude = truthLon)
