package com.nutonic.vlm

import com.nutonic.AndroidNutonicAppContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

actual class ProVlmModelCacheWriter actual constructor(
    private val modelBundleId: String,
    private val revision: String,
) {
    private var tmp: File? = null
    private var stream: FileOutputStream? = null

    private fun finalFile(): File? {
        val ctx = AndroidNutonicAppContext.application ?: return null
        return File(ctx.filesDir, "nutonic/pro-vlm/$modelBundleId-$revision.bundle")
    }

    actual suspend fun open(): Boolean =
        withContext(Dispatchers.IO) {
            try {
                val target = finalFile() ?: return@withContext false
                target.parentFile?.mkdirs()
                val t = File(target.parentFile, target.name + ".tmp")
                tmp = t
                stream = FileOutputStream(t)
                true
            } catch (_: Exception) {
                false
            }
        }

    actual fun write(
        bytes: ByteArray,
        offset: Int,
        length: Int,
    ) {
        stream?.write(bytes, offset, length) ?: error("ProVlmModelCacheWriter is not open")
    }

    actual suspend fun commit() {
        withContext(Dispatchers.IO) {
            stream?.flush()
            stream?.close()
            stream = null
            val t = tmp ?: return@withContext
            val target = finalFile() ?: run {
                tmp = null
                return@withContext
            }
            if (!t.renameTo(target)) {
                t.copyTo(target, overwrite = true)
                t.delete()
            }
            tmp = null
        }
    }

    actual suspend fun abort() {
        withContext(Dispatchers.IO) {
            try {
                stream?.close()
            } finally {
                stream = null
                tmp?.delete()
                tmp = null
            }
        }
    }
}

actual fun proVlmVerifiedBundleExists(record: ProVlmCacheRecord): Boolean {
    val ctx = AndroidNutonicAppContext.application ?: return false
    val f = File(ctx.filesDir, "nutonic/pro-vlm/${record.modelBundleId}-${record.revision}.bundle")
    return f.isFile && f.length() > 0L
}
