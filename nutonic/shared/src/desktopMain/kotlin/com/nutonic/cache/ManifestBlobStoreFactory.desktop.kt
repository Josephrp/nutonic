package com.nutonic.cache

import java.nio.file.Path

actual fun createManifestBlobStore(): ManifestBlobStore =
    FileManifestBlobStore(
        Path.of(
            System.getProperty("user.home"),
            ".nutonic",
            "cache",
            "manifest-envelope.json",
        ),
    )
