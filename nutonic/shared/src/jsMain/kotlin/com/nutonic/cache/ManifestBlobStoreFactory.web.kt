package com.nutonic.cache

actual fun createManifestBlobStore(): ManifestBlobStore = WebManifestBlobStore()
