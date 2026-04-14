package com.nutonic.cache

import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.MapSummary
import com.nutonic.api.ManifestRoundLocation
import com.nutonic.api.AiGuessRow
import com.nutonic.api.UsefulHintsTiers
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ShippedManifestMergeTest {
    @Test
    fun merge_overlays_locations_when_network_redacted_same_content_version() {
        val public =
            CacheManifestDocument(
                contentVersion = "nutonic.manifest.v2",
                engineVersion = "0.1.0",
                maps = listOf(MapSummary(mapId = "demo", title = "Demo mission")),
                locations = emptyList(),
                aiGuesses = emptyList(),
            )
        val shipped =
            CacheManifestDocument(
                contentVersion = "nutonic.manifest.v2",
                engineVersion = "0.1.0",
                maps = public.maps,
                locations =
                    listOf(
                        ManifestRoundLocation(
                            mapId = "demo",
                            locationId = "demo-vienna-001",
                            truthLat = 48.2082,
                            truthLon = 16.3738,
                            stillBundledResource = "files/3.jpg",
                            usefulHints = UsefulHintsTiers(tier1 = "a"),
                        ),
                    ),
                aiGuesses = listOf(AiGuessRow(mapId = "demo", locationId = "demo-vienna-001", aiLat = 1.0, aiLon = 2.0)),
            )
        val merged = mergeShippedRoundTruth(public, shipped)
        assertEquals(1, merged.locations.size)
        assertEquals(48.2082, merged.locations[0].truthLat)
        assertEquals(1, merged.aiGuesses.size)
    }

    @Test
    fun merge_skips_when_content_version_mismatches() {
        val public =
            CacheManifestDocument(
                contentVersion = "nutonic.manifest.v3",
                maps = listOf(MapSummary(mapId = "demo", title = "Demo mission")),
                locations = emptyList(),
            )
        val shipped =
            CacheManifestDocument(
                contentVersion = "nutonic.manifest.v2",
                maps = public.maps,
                locations =
                    listOf(
                        ManifestRoundLocation(
                            mapId = "demo",
                            locationId = "x",
                            truthLat = 1.0,
                            truthLon = 2.0,
                        ),
                    ),
            )
        val merged = mergeShippedRoundTruth(public, shipped)
        assertTrue(merged.locations.isEmpty())
    }

    @Test
    fun merge_skips_when_network_already_has_locations() {
        val loc =
            ManifestRoundLocation(
                mapId = "demo",
                locationId = "from-server",
                truthLat = 10.0,
                truthLon = 20.0,
            )
        val public =
            CacheManifestDocument(
                contentVersion = "nutonic.manifest.v2",
                maps = listOf(MapSummary(mapId = "demo", title = "Demo mission")),
                locations = listOf(loc),
            )
        val shipped =
            CacheManifestDocument(
                contentVersion = "nutonic.manifest.v2",
                maps = public.maps,
                locations =
                    listOf(
                        ManifestRoundLocation(
                            mapId = "demo",
                            locationId = "from-bundle",
                            truthLat = 99.0,
                            truthLon = 99.0,
                        ),
                    ),
            )
        val merged = mergeShippedRoundTruth(public, shipped)
        assertEquals("from-server", merged.locations.single().locationId)
    }
}
