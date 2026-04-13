package com.nutonic.cache

import com.nutonic.storage.File
import com.nutonic.storage.iosDocumentsDirectory
import com.nutonic.storage.mkdirs

actual fun createManifestBlobStore(): ManifestBlobStore {
    val root = File(iosDocumentsDirectory(), "nutonic/cache")
    root.mkdirs()
    return IosManifestBlobStore(File(root, "manifest-envelope.json"))
}
