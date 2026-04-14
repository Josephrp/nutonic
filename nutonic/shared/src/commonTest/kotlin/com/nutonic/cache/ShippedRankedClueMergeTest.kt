package com.nutonic.cache

import com.nutonic.api.NutonicJson
import com.nutonic.api.RankedClue
import com.nutonic.api.RankedCluePackDocument
import com.nutonic.api.StreetviewHintItem
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class ShippedRankedClueMergeTest {
    @Test
    fun mergeRankedClueWithPack_fillsNarrativeWhenApiOmits() {
        val api =
            RankedClue(
                mapId = "demo",
                locationId = "demo-vienna-001",
                stillBundleId = "b1",
                stillBundledResource = "files/x.jpg",
                usefulHints = null,
                streetviewHintPack = null,
                streetviewAssistNarrative = null,
                playBudgetMs = 1000,
                aiMarkerPhaseEnabled = true,
            )
        val pack =
            RankedCluePackDocument(
                schemaVersion = "nutonic.ranked_clue_pack.v1",
                clues =
                    listOf(
                        RankedClue(
                            mapId = "demo",
                            locationId = "demo-vienna-001",
                            stillBundleId = null,
                            stillBundledResource = null,
                            usefulHints = null,
                            streetviewHintPack = null,
                            streetviewAssistNarrative = "From shipped pack.",
                            playBudgetMs = null,
                            aiMarkerPhaseEnabled = true,
                        ),
                    ),
            )
        val merged = mergeRankedClueWithPack(api, pack)
        assertEquals("From shipped pack.", merged.streetviewAssistNarrative)
        assertEquals("b1", merged.stillBundleId)
    }

    @Test
    fun mergeRankedClueWithPack_prefersApiStreetviewWhenNonEmpty() {
        val apiPack =
            StreetviewHintItem(
                text = "API line",
                viewpointId = null,
                rank = 1,
            )
        val api =
            RankedClue(
                mapId = "demo",
                locationId = "demo-vienna-001",
                stillBundleId = null,
                stillBundledResource = null,
                usefulHints = null,
                streetviewHintPack = listOf(apiPack),
                streetviewAssistNarrative = null,
                playBudgetMs = null,
                aiMarkerPhaseEnabled = true,
            )
        val slice =
            RankedClue(
                mapId = "demo",
                locationId = "demo-vienna-001",
                stillBundleId = null,
                stillBundledResource = null,
                usefulHints = null,
                streetviewHintPack =
                    listOf(
                        StreetviewHintItem(
                            text = "Pack line",
                            viewpointId = null,
                            rank = 1,
                        ),
                    ),
                streetviewAssistNarrative = null,
                playBudgetMs = null,
                aiMarkerPhaseEnabled = true,
            )
        val merged = mergeRankedClueWithPack(api, RankedCluePackDocument("v1", listOf(slice)))
        assertEquals(1, merged.streetviewHintPack?.size)
        assertEquals("API line", merged.streetviewHintPack!![0].text)
    }

    @Test
    fun decode_ranked_clue_pack_document() {
        val j =
            """
            {"schema_version":"nutonic.ranked_clue_pack.v1","clues":[
              {"map_id":"a","location_id":"loc1","still_bundle_id":null,"still_bundled_resource":null,
               "useful_hints":null,"streetview_hint_pack":null,"streetview_assist_narrative":null,
               "play_budget_ms":null,"ai_marker_phase_enabled":true}
            ],"ai_guesses":[]}
            """.trimIndent()
        val doc = NutonicJson.decodeFromString(RankedCluePackDocument.serializer(), j)
        assertEquals("nutonic.ranked_clue_pack.v1", doc.schemaVersion)
        assertEquals(1, doc.clues.size)
        assertNotNull(doc.clues[0].mapId)
        assertTrue(doc.aiGuesses.isEmpty())
    }
}
