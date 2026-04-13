package com.nutonic.cache

import com.nutonic.api.NutonicApiClient
import com.nutonic.api.NutonicJson
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertIs
import kotlin.test.assertTrue

class ContentCacheRepositoryTest {
    @Test
    fun refreshManifest_persistsThenUses304() =
        runTest {
            val etag = "W/\"testetag123456789012\""
            val body =
                """
                {"content_version":"nutonic.catalog.v1","engine_version":"0.1.0","maps":[
                  {"map_id":"demo","title":"Demo mission","engine_version":null,"content_version":null}
                ]}
                """.trimIndent()
            val engine =
                MockEngine { request ->
                    val pathOk = request.url.toString().contains("cache/manifest")
                    val inm = request.headers[HttpHeaders.IfNoneMatch]
                    when {
                        !pathOk -> respond("missing", HttpStatusCode.NotFound)
                        inm == etag ->
                            respond(
                                "",
                                HttpStatusCode.NotModified,
                                headersOf(
                                    HttpHeaders.ETag to listOf(etag),
                                    HttpHeaders.ContentType to listOf(ContentType.Application.Json.toString()),
                                ),
                            )

                        else ->
                            respond(
                                body,
                                HttpStatusCode.OK,
                                headersOf(
                                    HttpHeaders.ETag to listOf(etag),
                                    HttpHeaders.ContentType to listOf(ContentType.Application.Json.toString()),
                                ),
                            )
                    }
                }
            val http =
                HttpClient(engine) {
                    install(ContentNegotiation) {
                        json(NutonicJson)
                    }
                }
            val client = NutonicApiClient("https://example.invalid", http)
            val store = MemoryManifestBlobStore()
            val repo = ContentCacheRepository(client, store)

            val first = repo.refreshManifest()
            assertIs<ManifestSyncResult.Updated>(first)

            val second = repo.refreshManifest()
            assertIs<ManifestSyncResult.NotModified>(second)

            http.close()
        }

    @Test
    fun refreshManifest_httpFailureUsesStaleCache() =
        runTest {
            val etag = "W/\"stale123\""
            val body =
                """
                {"content_version":"v-stale","engine_version":null,"maps":[
                  {"map_id":"x","title":"X","engine_version":null,"content_version":null}
                ]}
                """.trimIndent()
            var calls = 0
            val engine =
                MockEngine { request ->
                    val pathOk = request.url.toString().contains("cache/manifest")
                    when {
                        !pathOk -> respond("missing", HttpStatusCode.NotFound)
                        else -> {
                            calls++
                            if (calls == 1) {
                                respond(
                                    body,
                                    HttpStatusCode.OK,
                                    headersOf(
                                        HttpHeaders.ETag to listOf(etag),
                                        HttpHeaders.ContentType to listOf(ContentType.Application.Json.toString()),
                                    ),
                                )
                            } else {
                                respond(
                                    "no",
                                    HttpStatusCode.InternalServerError,
                                    headersOf(HttpHeaders.ContentType to listOf(ContentType.Text.Plain.toString())),
                                )
                            }
                        }
                    }
                }
            val http =
                HttpClient(engine) {
                    install(ContentNegotiation) {
                        json(NutonicJson)
                    }
                }
            val client = NutonicApiClient("https://example.invalid", http)
            val store = MemoryManifestBlobStore()
            val repo = ContentCacheRepository(client, store)
            assertIs<ManifestSyncResult.Updated>(repo.refreshManifest())
            val stale = repo.refreshManifest()
            assertIs<ManifestSyncResult.UsedStaleCache>(stale)
            assertTrue(stale.document.maps.any { it.mapId == "x" })
            http.close()
        }
}
