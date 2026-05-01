package com.nutonic.persistence

import kotlinx.browser.localStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val LEADERBOARD_STORAGE_KEY = "nutonic.local_nonranked_leaderboard.v1"
private const val GUESS_OUTBOX_STORAGE_KEY = "nutonic.guess_record_outbox.v1"
private const val PRO_VLM_MODEL_STORAGE_KEY = "nutonic.pro_vlm_model_cache.v1"
private const val SETTINGS_STORAGE_KEY = "nutonic.client_settings.v1"
private const val PLAYER_PROGRESS_STORAGE_KEY = "nutonic.player_progress.v1"

private class WebUtf8BlobStore(
    private val key: String,
) : Utf8BlobStore {
    override suspend fun load(): String? =
        withContext(Dispatchers.Default) {
            localStorage.getItem(key)
        }

    override suspend fun save(text: String) {
        withContext(Dispatchers.Default) {
            localStorage.setItem(key, text)
        }
    }
}

actual fun createLocalLeaderboardBlobStore(): Utf8BlobStore = WebUtf8BlobStore(LEADERBOARD_STORAGE_KEY)

actual fun createGuessSyncOutboxBlobStore(): Utf8BlobStore = WebUtf8BlobStore(GUESS_OUTBOX_STORAGE_KEY)

actual fun createSettingsBlobStore(): Utf8BlobStore = WebUtf8BlobStore(SETTINGS_STORAGE_KEY)

actual fun createPlayerProgressBlobStore(): Utf8BlobStore = WebUtf8BlobStore(PLAYER_PROGRESS_STORAGE_KEY)

actual fun createProVlmModelBlobStore(): Utf8BlobStore = WebUtf8BlobStore(PRO_VLM_MODEL_STORAGE_KEY)
