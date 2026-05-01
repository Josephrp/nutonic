package com.nutonic.api

import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.serialization.kotlinx.json.json

private const val WEEK_MS = 604_800_000L

actual fun createNutonicHttpClient(): HttpClient =
    HttpClient(OkHttp) {
        install(HttpTimeout) {
            requestTimeoutMillis = WEEK_MS
            connectTimeoutMillis = 120_000
            socketTimeoutMillis = WEEK_MS
        }
        install(ContentNegotiation) {
            json(NutonicJson)
        }
    }

/** Android emulator → host loopback (`uvicorn` default port per `server/README.md`). */
actual fun defaultNutonicServerOrigin(): String = "http://10.0.2.2:7860"
