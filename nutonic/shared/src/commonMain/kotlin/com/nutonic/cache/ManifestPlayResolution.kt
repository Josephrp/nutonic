package com.nutonic.cache

import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.ManifestRoundLocation
import com.nutonic.map.LatLon

/** First published round row for a map id (solo default). */
fun CacheManifestDocument.locationForMap(mapId: String): ManifestRoundLocation? = locations.firstOrNull { it.mapId == mapId }

/**
 * Resolves precomputed AI coordinates from manifest `ai_guesses` (`IMP-082`).
 */
class AiGuessStore(
    private val document: CacheManifestDocument,
) {
    fun coordinates(
        mapId: String,
        locationId: String,
    ): LatLon? =
        document.aiGuesses
            .firstOrNull { it.mapId == mapId && it.locationId == locationId }
            ?.let { LatLon(latitude = it.aiLat, longitude = it.aiLon) }
}

fun ManifestRoundLocation.truthLatLon(): LatLon = LatLon(latitude = truthLat, longitude = truthLon)
