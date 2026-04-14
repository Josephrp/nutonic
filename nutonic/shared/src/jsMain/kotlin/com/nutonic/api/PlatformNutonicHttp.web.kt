package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.engine.js.Js
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json

actual fun createNutonicHttpClient(): HttpClient =
    HttpClient(Js) {
        install(ContentNegotiation) {
            json(NutonicJson)
        }
    }

/** Browser dev: same-machine game server; ensure CORS on server matches webpack origin. */
actual fun defaultNutonicServerOrigin(): String = "http://127.0.0.1:7860"
