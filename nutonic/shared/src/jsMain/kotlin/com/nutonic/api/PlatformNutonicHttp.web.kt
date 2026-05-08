package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.engine.js.Js
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json
import kotlinx.browser.window

private const val WEEK_MS = 604_800_000L

actual fun createNutonicHttpClient(): HttpClient =
    HttpClient(Js) {
        install(HttpTimeout) {
            requestTimeoutMillis = WEEK_MS
            connectTimeoutMillis = 120_000
            socketTimeoutMillis = WEEK_MS
        }
        install(ContentNegotiation) {
            json(NutonicJson)
        }
    }

/** Browser dev: same-machine game server; ensure CORS on server matches webpack origin. */
actual fun defaultNutonicServerOrigin(): String {
    val fromQuery =
        runCatching {
            val params = window.location.search.removePrefix("?")
            params
                .split("&")
                .asSequence()
                .mapNotNull { it.split("=", limit = 2).takeIf { parts -> parts.size == 2 } }
                .firstOrNull { (k, _) -> k == "nutonicOrigin" || k == "nutonic_origin" || k == "NUTONIC_SERVER_ORIGIN" }
                ?.get(1)
        }.getOrNull()
    val fromStorage = runCatching { window.localStorage.getItem("nutonicServerOrigin") }.getOrNull()
    val candidate = (fromQuery ?: fromStorage)?.trim()?.trimEnd('/').orEmpty()
    if (candidate.isNotEmpty()) {
        return candidate
    }
    return "http://127.0.0.1:7860"
}
