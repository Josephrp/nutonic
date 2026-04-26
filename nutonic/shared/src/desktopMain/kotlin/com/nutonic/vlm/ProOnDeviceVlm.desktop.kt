package com.nutonic.vlm

import java.security.MessageDigest

actual fun createProOnDeviceVlmEngine(): ProOnDeviceVlmEngine = UnsupportedProOnDeviceVlmEngine("Desktop VLM runtime is not linked yet.")

actual fun sha256Hex(bytes: ByteArray): String = bytes.sha256HexJvm()

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

private fun ByteArray.sha256HexJvm(): String =
    MessageDigest
        .getInstance("SHA-256")
        .digest(this)
        .joinToString("") { b -> (b.toInt() and 0xff).toString(16).padStart(2, '0') }
