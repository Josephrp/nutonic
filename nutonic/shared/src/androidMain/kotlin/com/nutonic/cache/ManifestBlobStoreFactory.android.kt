package com.nutonic.cache

import com.nutonic.AndroidNutonicAppContext
import java.io.File

actual fun createManifestBlobStore(): ManifestBlobStore {
    val ctx = AndroidNutonicAppContext.application ?: return MemoryManifestBlobStore()
    val f = File(ctx.filesDir, "nutonic/cache/manifest-envelope.json")
    f.parentFile?.mkdirs()
    return FileManifestBlobStore(f.toPath())
}
