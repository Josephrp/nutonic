package com.nutonic.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.nutonic.api.NutonicJson
import com.nutonic.persistence.Utf8BlobStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * Loads/saves [ClientSettings] to a platform [Utf8BlobStore] (`rules/13`).
 * Call [hydrate] once after composition starts so disk values replace defaults.
 */
class PersistedSettingsRepository(
    private val blob: Utf8BlobStore,
    private val scope: CoroutineScope,
) : SettingsRepository {
    private var state by mutableStateOf(ClientSettings())

    override val settings: ClientSettings
        get() = state

    suspend fun hydrate() {
        val raw = blob.load() ?: return
        val loaded =
            runCatching {
                NutonicJson.decodeFromString(ClientSettings.serializer(), raw)
            }.getOrNull()
        if (loaded != null) {
            state = loaded
        }
    }

    override fun update(transform: (ClientSettings) -> ClientSettings) {
        state = transform(state)
        val snapshot = state
        scope.launch {
            blob.save(NutonicJson.encodeToString(ClientSettings.serializer(), snapshot))
        }
    }
}
