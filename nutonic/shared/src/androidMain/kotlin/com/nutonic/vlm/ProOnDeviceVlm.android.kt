package com.nutonic.vlm

import com.nutonic.AndroidNutonicAppContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest

actual fun createProOnDeviceVlmEngine(): ProOnDeviceVlmEngine = DeterministicProOnDeviceVlmEngine("Android verified-bundle runtime")

actual fun sha256Hex(bytes: ByteArray): String = bytes.sha256HexJvm()

actual suspend fun loadBundledProVlmModelBytes(record: ProVlmCacheRecord): ByteArray? =
    withContext(Dispatchers.IO) {
        val ctx = AndroidNutonicAppContext.application ?: return@withContext null
        val candidates =
            listOf(
                "pro_vlm/${record.modelBundleId}.bundle",
                "pro_vlm/${record.modelBundleId}-${record.revision}.bundle",
                "pro_vlm/pro-vlm.bundle",
            )
        candidates.firstNotNullOfOrNull { assetPath ->
            runCatching { ctx.assets.open(assetPath).use { it.readBytes() } }.getOrNull()
        }
    }

actual suspend fun loadCachedProVlmModelBytes(record: ProVlmCacheRecord): ByteArray? =
    withContext(Dispatchers.IO) {
        cacheFile(record).takeIf { it.isFile }?.readBytes()
    }

actual suspend fun saveCachedProVlmModelBytes(
    record: ProVlmCacheRecord,
    bytes: ByteArray,
) {
    withContext(Dispatchers.IO) {
        val file = cacheFile(record)
        file.parentFile?.mkdirs()
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(file)) {
            tmp.copyTo(file, overwrite = true)
            tmp.delete()
        }
    }
}

private fun cacheFile(record: ProVlmCacheRecord): File {
    val ctx = AndroidNutonicAppContext.application ?: return File("pro-vlm-unavailable.bin")
    return File(ctx.filesDir, "nutonic/pro-vlm/${record.modelBundleId}-${record.revision}.bundle")
}

private fun ByteArray.sha256HexJvm(): String =
    MessageDigest
        .getInstance("SHA-256")
        .digest(this)
        .joinToString("") { b -> (b.toInt() and 0xff).toString(16).padStart(2, '0') }
