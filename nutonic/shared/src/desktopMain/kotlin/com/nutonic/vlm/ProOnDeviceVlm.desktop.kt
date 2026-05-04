package com.nutonic.vlm

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

actual fun createProOnDeviceVlmEngine(): ProOnDeviceVlmEngine = DesktopLeapProOnDeviceVlmEngine()

actual fun sha256Hex(bytes: ByteArray): String = bytes.sha256HexJvm()

actual suspend fun loadBundledProVlmModelBytes(record: ProVlmCacheRecord): ByteArray? =
    withContext(Dispatchers.IO) {
        val candidates =
            listOf(
                Path.of("pro_vlm", "${record.modelBundleId}.bundle"),
                Path.of("pro_vlm", "${record.modelBundleId}-${record.revision}.bundle"),
                Path.of("pro_vlm", "pro-vlm.bundle"),
            )
        candidates.firstOrNull { Files.isRegularFile(it) }?.let { Files.readAllBytes(it) }
    }

actual suspend fun loadCachedProVlmModelBytes(record: ProVlmCacheRecord): ByteArray? =
    withContext(Dispatchers.IO) {
        cachePath(record).takeIf { Files.isRegularFile(it) }?.let { Files.readAllBytes(it) }
    }

actual suspend fun saveCachedProVlmModelBytes(
    record: ProVlmCacheRecord,
    bytes: ByteArray,
) {
    withContext(Dispatchers.IO) {
        val path = cachePath(record)
        Files.createDirectories(path.parent)
        val tmp = path.resolveSibling(path.fileName.toString() + ".tmp")
        Files.write(tmp, bytes)
        Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING)
    }
}

private fun cachePath(record: ProVlmCacheRecord): Path =
    Path.of(
        System.getProperty("user.home"),
        ".nutonic",
        "pro-vlm",
        "${record.modelBundleId}-${record.revision}.bundle",
    )

private fun ByteArray.sha256HexJvm(): String =
    MessageDigest
        .getInstance("SHA-256")
        .digest(this)
        .joinToString("") { b -> (b.toInt() and 0xff).toString(16).padStart(2, '0') }
