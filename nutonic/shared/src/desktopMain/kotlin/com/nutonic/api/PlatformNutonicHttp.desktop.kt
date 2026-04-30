package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json

actual fun createNutonicHttpClient(): HttpClient =
    HttpClient(CIO) {
        install(ContentNegotiation) {
            json(NutonicJson)
        }
    }

actual fun defaultNutonicServerOrigin(): String =
    (System.getenv("NUTONIC_SERVER_ORIGIN") ?: System.getProperty("nutonic.serverOrigin"))
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?: "http://127.0.0.1:7860"
