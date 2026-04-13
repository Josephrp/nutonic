package com.nutonic.persistence

import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.notExists
import kotlin.io.path.readText
import kotlin.io.path.writeText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

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
            path.writeText(text)
        }
    }
}

actual fun createLocalLeaderboardBlobStore(): Utf8BlobStore =
    PathUtf8BlobStore(
        Path.of(
            System.getProperty("user.home"),
            ".nutonic",
            "local-nonranked-leaderboard.json",
        ),
    )
