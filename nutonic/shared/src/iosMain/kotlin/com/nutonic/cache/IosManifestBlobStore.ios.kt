@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class)

package com.nutonic.cache

import com.nutonic.api.NutonicJson
import com.nutonic.storage.mkdirs
import com.nutonic.storage.readText
import com.nutonic.storage.writeText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import platform.Foundation.NSURL

/**
 * Persists manifest under the app documents directory (`IMP-080`).
 */
class IosManifestBlobStore(
    private val fileUrl: NSURL,
) : ManifestBlobStore {
    override suspend fun loadEnvelope(): PersistedManifestEnvelope? =
        withContext(Dispatchers.Default) {
            runCatching {
                NutonicJson.decodeFromString(
                    PersistedManifestEnvelope.serializer(),
                    fileUrl.readText(),
                )
            }.getOrNull()
        }

    override suspend fun saveEnvelope(envelope: PersistedManifestEnvelope) {
        withContext(Dispatchers.Default) {
            fileUrl.URLByDeletingLastPathComponent?.mkdirs()
            val text = NutonicJson.encodeToString(PersistedManifestEnvelope.serializer(), envelope)
            fileUrl.writeText(text)
        }
    }
}
