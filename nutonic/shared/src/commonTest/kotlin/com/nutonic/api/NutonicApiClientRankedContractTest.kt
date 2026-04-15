package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class NutonicApiClientRankedContractTest {
    @Test
    fun postRankedRoundStart_postsBearerJsonToVersionedPath() =
        runTest {
            lateinit var capturedAuth: String
            val engine =
                MockEngine { request ->
                    assertEquals(HttpMethod.Post, request.method)
                    assertTrue(request.url.toString().endsWith("/api/v1/ranked/rounds/start"))
                    capturedAuth = request.headers[HttpHeaders.Authorization].orEmpty()
                    assertTrue(capturedAuth.startsWith("Bearer "))
                    respond(
                        """
                        {
                          "round_id":"abc",
                          "round_ticket":"t.t.t",
                          "expires_in":900,
                          "clue":{
                            "map_id":"demo",
                            "location_id":"loc1",
                            "still_bundle_id":"nutonic.bundle.v1.demo_still",
                            "still_bundled_resource":null,
                            "useful_hints":null,
                            "streetview_hint_pack":[{"text":"hint"}],
                            "streetview_assist_narrative":null,
                            "satellite_caption_sidecar":{"caption":"cap"},
                            "play_budget_ms":180000,
                            "ai_marker_phase_enabled":true
                          }
                        }
                        """.trimIndent(),
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType to listOf("application/json")),
                    )
                }
            val http =
                HttpClient(engine) {
                    install(ContentNegotiation) {
                        json(NutonicJson)
                    }
                }
            val client = NutonicApiClient("https://api.test", http)
            val out =
                when (
                    val r =
                        client.postRankedRoundStart(
                            RankedRoundStartIn(mapId = "demo"),
                            bearerAccessToken = "sess-token",
                        )
                ) {
                    is ApiResult.Ok -> r.value
                    else -> error(r.toString())
                }
            assertEquals("abc", out.roundId)
            assertEquals("t.t.t", out.roundTicket)
            assertEquals("demo", out.clue.mapId)
            assertEquals(1, out.clue.streetviewHintPack?.size)
            assertEquals(JsonPrimitive("cap"), out.clue.satelliteCaptionSidecar?.get("caption"))
            assertEquals("Bearer sess-token", capturedAuth)
            http.close()
        }

    @Test
    fun postRankedRoundSubmit_sendsIdempotencyKeyHeader() =
        runTest {
            var idem: String? = null
            val engine =
                MockEngine { request ->
                    assertTrue(request.url.toString().contains("/api/v1/ranked/rounds/abc123/submit"))
                    idem = request.headers["Idempotency-Key"]
                    respond(
                        """{"distance_km":0.5,"score_points":4200,"verified":true}""",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType to listOf("application/json")),
                    )
                }
            val http =
                HttpClient(engine) {
                    install(ContentNegotiation) {
                        json(NutonicJson)
                    }
                }
            val client = NutonicApiClient("https://api.test", http)
            val sub =
                client.postRankedRoundSubmit(
                    roundId = "abc123",
                    body =
                        RankedSubmitIn(
                            guessLat = 1.0,
                            guessLon = 2.0,
                            roundTicket = "jwt-here",
                        ),
                    bearerAccessToken = "sess",
                    idempotencyKey = "ranked|abc123|submit",
                )
            val ok = assertIs<ApiResult.Ok<RankedSubmitOut>>(sub)
            assertEquals(0.5, ok.value.distanceKm)
            assertEquals(4200, ok.value.scorePoints)
            assertEquals("ranked|abc123|submit", idem)
            http.close()
        }

    @Test
    fun getRankedLeaderboard_hitsRankedAggregatePath() =
        runTest {
            val engine =
                MockEngine { request ->
                    assertTrue(request.url.toString().contains("/api/v1/maps/demo/leaderboard/ranked"))
                    respond(
                        """[{"display_handle":"RNK-ABCDEF01","player_role":"RANKED","score_points":9000,"distance_km":1.2}]""",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType to listOf("application/json")),
                    )
                }
            val http =
                HttpClient(engine) {
                    install(ContentNegotiation) {
                        json(NutonicJson)
                    }
                }
            val client = NutonicApiClient("https://api.test", http)
            val rows =
                when (val r = client.getRankedLeaderboard("demo")) {
                    is ApiResult.Ok -> r.value
                    else -> error(r.toString())
                }
            assertEquals(1, rows.size)
            assertEquals("RANKED", rows[0].playerRole)
            http.close()
        }

    @Test
    fun getLeaderboard_tierRanked_appendsTierQuery() =
        runTest {
            val engine =
                MockEngine { request ->
                    assertEquals(HttpMethod.Get, request.method)
                    assertTrue(request.url.toString().contains("/api/v1/maps/demo/leaderboard?tier=ranked"))
                    respond(
                        """[{"display_handle":"RNK-ABCDEF01","player_role":"RANKED","score_points":9000,"distance_km":1.2}]""",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType to listOf("application/json")),
                    )
                }
            val http =
                HttpClient(engine) {
                    install(ContentNegotiation) {
                        json(NutonicJson)
                    }
                }
            val client = NutonicApiClient("https://api.test", http)
            val rows =
                when (val r = client.getLeaderboard("demo", tier = "ranked")) {
                    is ApiResult.Ok -> r.value
                    else -> error(r.toString())
                }
            assertEquals(1, rows.size)
            assertEquals("RANKED", rows[0].playerRole)
            http.close()
        }
}
