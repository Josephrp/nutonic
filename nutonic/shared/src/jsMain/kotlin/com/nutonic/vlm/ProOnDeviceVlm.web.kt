package com.nutonic.vlm

actual fun createProOnDeviceVlmEngine(): ProOnDeviceVlmEngine = UnsupportedProOnDeviceVlmEngine("Web VLM runtime is not linked yet.")

actual fun sha256Hex(bytes: ByteArray): String = "web-sha256-unavailable"

private class UnsupportedProOnDeviceVlmEngine(
    private val reason: String,
) : ProOnDeviceVlmEngine {
    override suspend fun prepareModel(
        bytes: ByteArray,
        cacheRecord: ProVlmCacheRecord,
    ) = Unit

    override suspend fun run(input: ProVlmPreparedInput): ProOnDeviceVlmRunResult =
        ProOnDeviceVlmRunResult.Unsupported(reason)
}
