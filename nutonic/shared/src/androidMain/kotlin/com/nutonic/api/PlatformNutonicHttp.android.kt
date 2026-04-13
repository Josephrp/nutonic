package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json

actual fun createNutonicHttpClient(): HttpClient =
    HttpClient(OkHttp) {
        install(ContentNegotiation) {
            json(NutonicJson)
        }
    }

/** Android emulator → host loopback (`uvicorn` default port per `server/README.md`). */
actual fun defaultNutonicServerOrigin(): String = "http://10.0.2.2:7860"
