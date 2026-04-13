package com.nutonic.persistence

import kotlinx.browser.localStorage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val LEADERBOARD_STORAGE_KEY = "nutonic.local_nonranked_leaderboard.v1"

private class WebUtf8BlobStore : Utf8BlobStore {
    override suspend fun load(): String? =
        withContext(Dispatchers.Default) {
            localStorage.getItem(LEADERBOARD_STORAGE_KEY)
        }

    override suspend fun save(text: String) {
        withContext(Dispatchers.Default) {
            localStorage.setItem(LEADERBOARD_STORAGE_KEY, text)
        }
    }
}

actual fun createLocalLeaderboardBlobStore(): Utf8BlobStore = WebUtf8BlobStore()
