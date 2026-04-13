package com.nutonic.api

import kotlinx.serialization.builtins.ListSerializer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class NutonicApiModelsTest {
    @Test
    fun decodes_health_response() {
        val j = """{"status":"ok"}"""
        val v = NutonicJson.decodeFromString(HealthResponse.serializer(), j)
        assertEquals("ok", v.status)
    }

    @Test
    fun decodes_config_features_block() {
        val j =
            """
            {"features":{"ranked":false,"community_lb_get":true,"community_lb_post":true,"pro_jobs":false,"guesses_record":false}}
            """.trimIndent()
        val v = NutonicJson.decodeFromString(ConfigResponse.serializer(), j)
        assertTrue(v.features.communityLbGet)
        assertTrue(v.features.communityLbPost)
        assertEquals(false, v.features.ranked)
        assertEquals(false, v.features.proJobs)
        assertEquals(false, v.features.guessesRecord)
    }

    @Test
    fun decodes_map_summary_array() {
        val j =
            """
            [{"map_id":"demo","title":"Demo","engine_version":"0.1.0","content_version":null}]
            """.trimIndent()
        val list = NutonicJson.decodeFromString(ListSerializer(MapSummary.serializer()), j)
        assertEquals(1, list.size)
        assertEquals("demo", list[0].mapId)
        assertEquals("Demo", list[0].title)
        assertEquals("0.1.0", list[0].engineVersion)
    }

    @Test
    fun decodes_debug_session_response() {
        val j = """{"ok":true,"session_id":"sess-1"}"""
        val v = NutonicJson.decodeFromString(DebugSessionResponse.serializer(), j)
        assertEquals(true, v.ok)
        assertEquals("sess-1", v.sessionId)
    }

    @Test
    fun decodes_leaderboard_row_array() {
        val j =
            """
            [{"display_handle":"A","player_role":"HUMAN","score_points":100,"distance_km":12.5}]
            """.trimIndent()
        val list = NutonicJson.decodeFromString(ListSerializer(CommunityLeaderboardRow.serializer()), j)
        assertEquals(1, list.size)
        assertEquals("A", list[0].displayHandle)
        assertEquals(100, list[0].scorePoints)
        assertEquals(12.5, list[0].distanceKm!!)
    }

    @Test
    fun decodes_cache_manifest_document() {
        val j =
            """
            {"content_version":"nutonic.catalog.v1","engine_version":"0.1.0","maps":[
              {"map_id":"demo","title":"Demo mission","engine_version":null,"content_version":null}
            ]}
            """.trimIndent()
        val v = NutonicJson.decodeFromString(CacheManifestDocument.serializer(), j)
        assertEquals("nutonic.catalog.v1", v.contentVersion)
        assertEquals(1, v.maps.size)
        assertEquals("demo", v.maps[0].mapId)
        assertTrue(v.locations.isEmpty())
        assertTrue(v.aiGuesses.isEmpty())
    }

    @Test
    fun decodes_cache_manifest_with_locations_and_ai_guesses() {
        val j =
            """
            {"content_version":"nutonic.manifest.v2","engine_version":"0.1.0","maps":[
              {"map_id":"demo","title":"Demo mission","engine_version":null,"content_version":null}
            ],"locations":[
              {"map_id":"demo","location_id":"demo-vienna-001","truth_lat":48.2082,"truth_lon":16.3738,
               "ruleset_version":"v1","still_bundled_resource":"files/3.jpg","still_http_url":null,
               "useful_hints":{"tier_1":"a","tier_2":"b","tier_3":"c"},"play_budget_ms":180000,"ai_marker_phase_enabled":true}
            ],"ai_guesses":[
              {"map_id":"demo","location_id":"demo-vienna-001","ai_lat":41.9,"ai_lon":12.5}
            ]}
            """.trimIndent()
        val v = NutonicJson.decodeFromString(CacheManifestDocument.serializer(), j)
        assertEquals("nutonic.manifest.v2", v.contentVersion)
        assertEquals(1, v.locations.size)
        assertEquals("demo-vienna-001", v.locations[0].locationId)
        assertEquals(1, v.aiGuesses.size)
        assertEquals(41.9, v.aiGuesses[0].aiLat)
    }

    @Test
    fun decodes_ranked_round_start_out() {
        val j =
            """
            {"round_id":"abc","round_ticket":"t","expires_in":900,"clue":{
              "map_id":"demo","location_id":"demo-vienna-001","still_bundle_id":"nutonic.bundle.v1.demo_still",
              "still_bundled_resource":"files/3.jpg","useful_hints":null,"play_budget_ms":180000,"ai_marker_phase_enabled":true
            }}
            """.trimIndent()
        val v = NutonicJson.decodeFromString(RankedRoundStartOut.serializer(), j)
        assertEquals("abc", v.roundId)
        assertEquals("t", v.roundTicket)
        assertEquals("demo-vienna-001", v.clue.locationId)
        assertEquals("nutonic.bundle.v1.demo_still", v.clue.stillBundleId)
    }

    @Test
    fun encodes_ranked_forfeit_in() {
        val body = RankedForfeitIn(reason = "peer_reveal")
        val s = NutonicJson.encodeToString(RankedForfeitIn.serializer(), body)
        assertTrue(s.contains("peer_reveal"))
    }
}
