package com.nutonic.vlm

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.IOException
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption

actual class ProVlmModelCacheWriter actual constructor(
    private val modelBundleId: String,
    private val revision: String,
) {
    private val cacheFileName = "${modelBundleId.safeCacheSegment()}-${revision.safeCacheSegment()}.bundle"
    private val finalPath: Path =
        Path.of(
            System.getProperty("user.home"),
            ".nutonic",
            "pro-vlm",
            cacheFileName,
        )
    private var tmpPath: Path? = null
    private var out: java.io.OutputStream? = null

    actual suspend fun open(): Boolean =
        withContext(Dispatchers.IO) {
            try {
                Files.createDirectories(finalPath.parent)
                val tmp = finalPath.resolveSibling(finalPath.fileName.toString() + ".tmp")
                tmpPath = tmp
                out =
                    Files.newOutputStream(
                        tmp,
                        StandardOpenOption.CREATE,
                        StandardOpenOption.TRUNCATE_EXISTING,
                    )
                true
            } catch (_: IOException) {
                false
            }
        }

    actual fun write(
        bytes: ByteArray,
        offset: Int,
        length: Int,
    ) {
        out?.write(bytes, offset, length) ?: error("ProVlmModelCacheWriter is not open")
    }

    actual suspend fun commit() {
        withContext(Dispatchers.IO) {
            out?.close()
            out = null
            val tmp = tmpPath ?: return@withContext
            Files.move(tmp, finalPath, StandardCopyOption.REPLACE_EXISTING)
            tmpPath = null
        }
    }

    actual suspend fun abort() {
        withContext(Dispatchers.IO) {
            try {
                out?.close()
            } finally {
                out = null
                tmpPath?.let { runCatching { Files.deleteIfExists(it) } }
                tmpPath = null
            }
        }
    }
}

actual fun proVlmVerifiedBundleExists(record: ProVlmCacheRecord): Boolean =
    runCatching {
        val path =
            Path.of(
                System.getProperty("user.home"),
                ".nutonic",
                "pro-vlm",
                "${record.modelBundleId.safeCacheSegment()}-${record.revision.safeCacheSegment()}.bundle",
            )
        Files.isRegularFile(path) && Files.size(path) > 0L
    }.getOrDefault(false)

private fun String.safeCacheSegment(): String =
    replace(Regex("""[\\/:*?"<>|]+"""), "_")
