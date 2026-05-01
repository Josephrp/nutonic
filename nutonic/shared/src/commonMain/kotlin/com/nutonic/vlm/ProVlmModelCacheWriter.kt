package com.nutonic.vlm

/** Streams a PRO VLM bundle to platform sandbox cache (temp file → atomic rename). */
expect class ProVlmModelCacheWriter(modelBundleId: String, revision: String) {
    suspend fun open(): Boolean

    fun write(
        bytes: ByteArray,
        offset: Int,
        length: Int,
    )

    suspend fun commit()

    suspend fun abort()
}

/** True when a non-empty cached bundle exists on disk (avoid reloading multi‑GiB models into the heap). */
expect fun proVlmVerifiedBundleExists(record: ProVlmCacheRecord): Boolean
