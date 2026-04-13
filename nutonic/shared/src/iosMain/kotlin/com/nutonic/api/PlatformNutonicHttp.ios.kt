package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.engine.darwin.Darwin
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json

actual fun createNutonicHttpClient(): HttpClient =
    HttpClient(Darwin) {
        install(ContentNegotiation) {
            json(NutonicJson)
        }
    }

/** iOS Simulator → Mac localhost. */
actual fun defaultNutonicServerOrigin(): String = "http://127.0.0.1:7860"
