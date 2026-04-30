package com.nutonic.vlm

actual fun createProOnDeviceVlmEngine(): ProOnDeviceVlmEngine = DeterministicProOnDeviceVlmEngine("web verified-bundle runtime")

actual fun sha256Hex(bytes: ByteArray): String = "web-sha256-unavailable"

actual suspend fun loadBundledProVlmModelBytes(record: ProVlmCacheRecord): ByteArray? = null

actual suspend fun loadCachedProVlmModelBytes(record: ProVlmCacheRecord): ByteArray? = null

actual suspend fun saveCachedProVlmModelBytes(
    record: ProVlmCacheRecord,
    bytes: ByteArray,
) = Unit
