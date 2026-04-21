package com.nutonic.persistence

import com.nutonic.AndroidNutonicAppContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import kotlin.io.path.notExists
import kotlin.io.path.readText
import kotlin.io.path.writeText

private class PathUtf8BlobStore(
    private val path: Path,
) : Utf8BlobStore {
    override suspend fun load(): String? =
        withContext(Dispatchers.IO) {
            if (path.notExists()) null else path.readText()
        }

    override suspend fun save(text: String) {
        withContext(Dispatchers.IO) {
            path.parent?.let { Files.createDirectories(it) }
            val tmp = path.resolveSibling(path.fileName.toString() + ".tmp")
            tmp.writeText(text)
            try {
                Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING)
            }
        }
    }
}

private fun androidNutonicBlob(relative: String): Utf8BlobStore {
    val ctx = AndroidNutonicAppContext.application ?: return MemoryUtf8BlobStore()
    val f = java.io.File(ctx.filesDir, relative)
    f.parentFile?.mkdirs()
    return PathUtf8BlobStore(f.toPath())
}

actual fun createLocalLeaderboardBlobStore(): Utf8BlobStore =
    androidNutonicBlob("nutonic/local-nonranked-leaderboard.json")

actual fun createGuessSyncOutboxBlobStore(): Utf8BlobStore =
    androidNutonicBlob("nutonic/guess-record-outbox.json")
