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
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue

class NutonicApiClientProContractTest {
    @Test
    fun getProReadiness_decodesProductionReadinessContract() =
        runTest {
            val engine =
                MockEngine { request ->
                    assertEquals(HttpMethod.Get, request.method)
                    assertTrue(request.url.toString().endsWith("/api/v1/pro/readiness"))
                    respond(
                        """
                        {
                          "feature_enabled": true,
                          "ready": false,
                          "materialization_configured": true,
                          "materialization_healthy": true,
                          "lfm_brief_configured": true,
                          "lfm_brief_healthy": false,
                          "inference_worker_configured": false,
                          "inference_worker_healthy": null,
                          "vlm_model_configured": true,
                          "vlm_model_available": true,
                          "vlm_model_bundle_id": "nutonic.pro.vlm.test",
                          "degraded_reasons": ["lfm_brief_unhealthy"]
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

            val result = client.getProReadiness("sess")

            val ok = assertIs<ApiResult.Ok<ProReadinessOut>>(result)
            assertEquals(false, ok.value.ready)
            assertEquals("nutonic.pro.vlm.test", ok.value.vlmModelBundleId)
            assertEquals(listOf("lfm_brief_unhealthy"), ok.value.degradedReasons)
            http.close()
        }

    @Test
    fun pollProJob_retriesTransientFailuresUntilTerminalStatus() =
        runTest {
            var calls = 0
            val engine =
                MockEngine { request ->
                    calls += 1
                    assertEquals(HttpMethod.Get, request.method)
                    assertTrue(request.url.toString().endsWith("/api/v1/pro/jobs/job-1"))
                    when (calls) {
                        1 ->
                            respond(
                                """{"detail":"try again"}""",
                                HttpStatusCode.InternalServerError,
                                headersOf(HttpHeaders.ContentType to listOf("application/json")),
                            )
                        2 ->
                            respond(
                                """{"job_id":"job-1","status":"running","progress_pct":40}""",
                                HttpStatusCode.OK,
                                headersOf(HttpHeaders.ContentType to listOf("application/json")),
                            )
                        else ->
                            respond(
                                """{"job_id":"job-1","status":"completed","progress_pct":100,"analysis_profile":"future_profile"}""",
                                HttpStatusCode.OK,
                                headersOf(HttpHeaders.ContentType to listOf("application/json")),
                            )
                    }
                }
            val http =
                HttpClient(engine) {
                    install(ContentNegotiation) {
                        json(NutonicJson)
                    }
                }
            val client = NutonicApiClient("https://api.test", http)
            val progress = mutableListOf<String>()

            val result =
                client.pollProJob(
                    jobId = "job-1",
                    bearerAccessToken = "sess",
                    intervalMs = 0,
                    maxAttempts = 4,
                    onProgress = { progress.add(it.status) },
                )

            val ok = assertIs<ApiResult.Ok<ProJobStatusOut>>(result)
            assertEquals("completed", ok.value.status)
            assertEquals("future_profile", ok.value.analysisProfile)
            assertEquals(listOf("running", "completed"), progress)
            assertEquals(3, calls)
            http.close()
        }

    @Test
    fun pollProJob_doesNotRetryClientValidationFailures() =
        runTest {
            var calls = 0
            val engine =
                MockEngine {
                    calls += 1
                    respond(
                        """{"detail":"bad job id"}""",
                        HttpStatusCode.BadRequest,
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

            val result = client.pollProJob("bad", "sess", intervalMs = 0, maxAttempts = 4)

            val failure = assertIs<ApiResult.HttpFailure>(result)
            assertEquals(400, failure.statusCode)
            assertEquals(1, calls)
            http.close()
        }
}
