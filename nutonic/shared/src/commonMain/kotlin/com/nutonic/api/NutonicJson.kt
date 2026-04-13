package com.nutonic.api

import kotlinx.serialization.json.Json

/** Shared JSON settings for game server DTOs (`docs/openapi.yaml`). */
val NutonicJson: Json =
    Json {
        ignoreUnknownKeys = true
        isLenient = false
        encodeDefaults = true
    }
