@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class)

package com.nutonic.vlm

import kotlinx.cinterop.addressOf
import kotlinx.cinterop.convert
import kotlinx.cinterop.usePinned
import platform.CoreCrypto.CC_SHA256
import platform.CoreCrypto.CC_SHA256_DIGEST_LENGTH

actual fun createProOnDeviceVlmEngine(): ProOnDeviceVlmEngine = DeterministicProOnDeviceVlmEngine("iOS verified-bundle runtime")

actual fun sha256Hex(bytes: ByteArray): String {
    val digest = UByteArray(CC_SHA256_DIGEST_LENGTH)
    bytes.usePinned { pinned ->
        digest.usePinned { out ->
            CC_SHA256(pinned.addressOf(0), bytes.size.convert(), out.addressOf(0))
        }
    }
    return digest.joinToString("") { it.toString(16).padStart(2, '0') }
}

actual suspend fun loadBundledProVlmModelBytes(record: ProVlmCacheRecord): ByteArray? = null

actual suspend fun loadCachedProVlmModelBytes(record: ProVlmCacheRecord): ByteArray? = null

actual suspend fun saveCachedProVlmModelBytes(
    record: ProVlmCacheRecord,
    bytes: ByteArray,
) = Unit
