package com.nutonic.cache

import com.nutonic.api.AiGuessRow
import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.ManifestRoundLocation
import com.nutonic.api.MapSummary
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
        val detailed = mergeShippedRoundTruthDetailed(public, shipped)
        assertEquals(1, merged.locations.size)
        assertEquals(48.2082, merged.locations[0].truthLat)
        assertEquals(1, merged.aiGuesses.size)
        assertEquals(ShippedManifestMergeOutcome.OVERLAID_FROM_SHIPPED, detailed.outcome)
        assertEquals("nutonic.manifest.v2", detailed.shippedContentVersion)
    }

    @Test
    fun merge_overlays_when_content_version_mismatches_and_network_is_redacted() {
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
        val detailed = mergeShippedRoundTruthDetailed(public, shipped)
        assertEquals(1, merged.locations.size)
        assertEquals("x", merged.locations.single().locationId)
        assertEquals(ShippedManifestMergeOutcome.VERSION_MISMATCH, detailed.outcome)
        assertEquals("nutonic.manifest.v2", detailed.shippedContentVersion)
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
        val detailed = mergeShippedRoundTruthDetailed(public, shipped)
        assertEquals("from-server", merged.locations.single().locationId)
        assertEquals(ShippedManifestMergeOutcome.NETWORK_HAS_ROUND_TRUTH, detailed.outcome)
    }

    @Test
    fun merge_keeps_server_locations_when_versions_mismatch_but_network_has_round_truth() {
        val serverLocation =
            ManifestRoundLocation(
                mapId = "demo",
                locationId = "from-server-v3",
                truthLat = 10.0,
                truthLon = 20.0,
            )
        val public =
            CacheManifestDocument(
                contentVersion = "nutonic.manifest.v3",
                maps = listOf(MapSummary(mapId = "demo", title = "Demo mission")),
                locations = listOf(serverLocation),
                aiGuesses = emptyList(),
            )
        val shipped =
            CacheManifestDocument(
                contentVersion = "nutonic.manifest.v2",
                maps = public.maps,
                locations =
                    listOf(
                        ManifestRoundLocation(
                            mapId = "demo",
                            locationId = "from-bundle-v2",
                            truthLat = 99.0,
                            truthLon = 99.0,
                        ),
                    ),
                aiGuesses = listOf(AiGuessRow(mapId = "demo", locationId = "from-server-v3", aiLat = 1.0, aiLon = 2.0)),
            )

        val detailed = mergeShippedRoundTruthDetailed(public, shipped)

        assertEquals("from-server-v3", detailed.document.locations.single().locationId)
        assertEquals(1, detailed.document.aiGuesses.size)
        assertEquals(ShippedManifestMergeOutcome.VERSION_MISMATCH, detailed.outcome)
    }

    @Test
    fun ensurePlayableLocationFromShipped_fills_missing_map_row_when_server_has_other_maps() {
        val serverLocOther =
            ManifestRoundLocation(
                mapId = "other",
                locationId = "x",
                truthLat = 1.0,
                truthLon = 2.0,
            )
        val public =
            CacheManifestDocument(
                contentVersion = "v3",
                maps = listOf(MapSummary(mapId = "demo", title = "Demo"), MapSummary(mapId = "other", title = "Other")),
                locations = listOf(serverLocOther),
                aiGuesses = emptyList(),
            )
        val shippedLocDemo =
            ManifestRoundLocation(
                mapId = "demo",
                locationId = "demo-from-ship",
                truthLat = 48.0,
                truthLon = 16.0,
            )
        val shipped =
            CacheManifestDocument(
                contentVersion = "v2",
                maps = public.maps,
                locations = listOf(shippedLocDemo),
                aiGuesses = listOf(AiGuessRow(mapId = "demo", locationId = "demo-from-ship", aiLat = 3.0, aiLon = 4.0)),
            )
        val patched = ensurePlayableLocationFromShipped(public, shipped, "demo")
        assertEquals(2, patched.locations.size)
        assertEquals("demo-from-ship", patched.locationForMap("demo")?.locationId)
        assertEquals(1, patched.aiGuesses.size)
    }
}
