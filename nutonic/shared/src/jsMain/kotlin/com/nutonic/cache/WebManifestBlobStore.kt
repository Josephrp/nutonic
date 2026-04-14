package com.nutonic.cache

import com.nutonic.api.NutonicJson
import kotlinx.browser.localStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val MANIFEST_STORAGE_KEY = "nutonic.manifest.envelope.v1"

/** Browser `localStorage` manifest envelope (`IMP-080`). */
class WebManifestBlobStore : ManifestBlobStore {
    override suspend fun loadEnvelope(): PersistedManifestEnvelope? =
        withContext(Dispatchers.Default) {
            val raw = localStorage.getItem(MANIFEST_STORAGE_KEY) ?: return@withContext null
            runCatching {
                NutonicJson.decodeFromString(PersistedManifestEnvelope.serializer(), raw)
            }.getOrNull()
        }

    override suspend fun saveEnvelope(envelope: PersistedManifestEnvelope) {
        withContext(Dispatchers.Default) {
            val text = NutonicJson.encodeToString(PersistedManifestEnvelope.serializer(), envelope)
            localStorage.setItem(MANIFEST_STORAGE_KEY, text)
        }
    }
}
