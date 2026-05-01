@file:Suppress("UNUSED_PARAMETER")

package com.nutonic.vlm

actual class ProVlmModelCacheWriter actual constructor(
    modelBundleId: String,
    revision: String,
) {
    actual suspend fun open(): Boolean = false

    actual fun write(
        bytes: ByteArray,
        offset: Int,
        length: Int,
    ) = Unit

    actual suspend fun commit() = Unit

    actual suspend fun abort() = Unit
}

actual fun proVlmVerifiedBundleExists(record: ProVlmCacheRecord): Boolean = false
