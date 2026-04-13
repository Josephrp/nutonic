package com.nutonic.api

import io.ktor.client.HttpClient

expect fun createNutonicHttpClient(): HttpClient

/**
 * Default game server origin for local dev (scheme + host + port, no `/api/v1` suffix).
 * Per `docs/openapi.yaml`, request paths are full `/api/v1/...`.
 */
expect fun defaultNutonicServerOrigin(): String
