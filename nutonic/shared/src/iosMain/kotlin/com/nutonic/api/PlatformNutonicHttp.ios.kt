package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.engine.darwin.Darwin
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json
import platform.Foundation.NSProcessInfo

private const val WEEK_MS = 604_800_000L

actual fun createNutonicHttpClient(): HttpClient =
    HttpClient(Darwin) {
        install(HttpTimeout) {
            requestTimeoutMillis = WEEK_MS
            connectTimeoutMillis = 120_000
            socketTimeoutMillis = WEEK_MS
        }
        install(ContentNegotiation) {
            json(NutonicJson)
        }
    }

/** iOS Simulator → Mac localhost. */
actual fun defaultNutonicServerOrigin(): String =
    (NSProcessInfo.processInfo.environment["NUTONIC_SERVER_ORIGIN"] as? String)
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?: "http://127.0.0.1:7860"
