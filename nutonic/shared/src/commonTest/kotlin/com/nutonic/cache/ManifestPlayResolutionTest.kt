package com.nutonic.cache

import com.nutonic.api.AiGuessRow
import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.MapSummary
import com.nutonic.map.LatLon
import kotlin.test.Test
import kotlin.test.assertEquals

class ManifestPlayResolutionTest {
    @Test
    fun ai_guess_store_prefers_explicit_pro_overlay_without_mutating_manifest() {
        val manifest =
            CacheManifestDocument(
                contentVersion = "v",
                engineVersion = "e",
                maps = listOf(MapSummary(mapId = "demo", title = "Demo")),
                aiGuesses = listOf(AiGuessRow(mapId = "demo", locationId = "loc-1", aiLat = 1.0, aiLon = 2.0)),
            )
        val overlays = ProOverlayGuessRepository()
        overlays.publish(
            ProOverlayGuess(
                mapId = "demo",
                coordinates = LatLon(3.0, 4.0),
                jobId = "job-123456789",
                profile = "wildfire",
                artifactId = "wildfire_aoi_overlay",
            ),
        )

        val resolution = AiGuessStore(manifest, overlays).resolution("demo", "loc-1")

        assertEquals(LatLon(3.0, 4.0), resolution?.coordinates)
        assertEquals("PRO run job-1234 · wildfire · wildfire_aoi_overlay", resolution?.source)
        assertEquals(1.0, manifest.aiGuesses.single().aiLat)
    }

    @Test
    fun ai_guess_store_uses_manifest_when_no_pro_overlay_published() {
        val manifest =
            CacheManifestDocument(
                contentVersion = "v",
                engineVersion = "e",
                maps = listOf(MapSummary(mapId = "demo", title = "Demo")),
                aiGuesses = listOf(AiGuessRow(mapId = "demo", locationId = "loc-1", aiLat = 1.0, aiLon = 2.0)),
            )

        val resolution = AiGuessStore(manifest, ProOverlayGuessRepository()).resolution("demo", "loc-1")

        assertEquals(LatLon(1.0, 2.0), resolution?.coordinates)
        assertEquals("manifest", resolution?.source)
    }
}
