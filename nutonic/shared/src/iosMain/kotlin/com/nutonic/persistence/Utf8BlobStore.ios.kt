@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class)

package com.nutonic.persistence

import com.nutonic.storage.File
import com.nutonic.storage.iosDocumentsDirectory
import com.nutonic.storage.mkdirs
import com.nutonic.storage.readText
import com.nutonic.storage.writeText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import platform.Foundation.NSURL

private class IosUtf8BlobStore(
    private val fileUrl: NSURL,
) : Utf8BlobStore {
    override suspend fun load(): String? =
        withContext(Dispatchers.Default) {
            runCatching { fileUrl.readText() }.getOrNull()
        }

    override suspend fun save(text: String) {
        withContext(Dispatchers.Default) {
            fileUrl.URLByDeletingLastPathComponent?.mkdirs()
            // NSString.writeToURL(..., atomically = true) — durable single-file replace on iOS.
            fileUrl.writeText(text)
        }
    }
}

private fun iosNutonicBlob(fileName: String): Utf8BlobStore {
    val root = File(iosDocumentsDirectory(), "nutonic")
    root.mkdirs()
    val file = File(root, fileName)
    return IosUtf8BlobStore(file)
}

actual fun createLocalLeaderboardBlobStore(): Utf8BlobStore =
    iosNutonicBlob("local-nonranked-leaderboard.json")

actual fun createGuessSyncOutboxBlobStore(): Utf8BlobStore =
    iosNutonicBlob("guess-record-outbox.json")
