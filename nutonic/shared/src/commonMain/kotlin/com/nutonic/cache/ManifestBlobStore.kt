package com.nutonic.cache

import com.nutonic.api.CacheManifestDocument
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Persists last-known manifest + **ETag** / **content_version** (`rules/13`, IMP-080).
 * Implementations must not partially expose a new document without matching metadata.
 */
interface ManifestBlobStore {
    suspend fun loadEnvelope(): PersistedManifestEnvelope?

    suspend fun saveEnvelope(envelope: PersistedManifestEnvelope)
}

@Serializable
data class PersistedManifestEnvelope(
    val etag: String,
    @SerialName("content_version") val contentVersion: String,
    val document: CacheManifestDocument,
)

/** In-process store (tests + mobile/web until platform files land). */
class MemoryManifestBlobStore : ManifestBlobStore {
    private var snapshot: PersistedManifestEnvelope? = null

    override suspend fun loadEnvelope(): PersistedManifestEnvelope? = snapshot

    override suspend fun saveEnvelope(envelope: PersistedManifestEnvelope) {
        snapshot = envelope
    }
}
