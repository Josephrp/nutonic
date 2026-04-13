package com.nutonic.cache

import com.nutonic.api.NutonicJson
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import kotlin.io.path.createDirectories
import kotlin.io.path.notExists
import kotlin.io.path.readText
import kotlin.io.path.writeText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** JVM Path-backed manifest envelope (Android sandbox, IMP-080). */
class FileManifestBlobStore(
    private val path: Path,
) : ManifestBlobStore {
    override suspend fun loadEnvelope(): PersistedManifestEnvelope? =
        withContext(Dispatchers.IO) {
            if (path.notExists()) {
                null
            } else {
                NutonicJson.decodeFromString(
                    PersistedManifestEnvelope.serializer(),
                    path.readText(),
                )
            }
        }

    override suspend fun saveEnvelope(envelope: PersistedManifestEnvelope) {
        withContext(Dispatchers.IO) {
            path.parent?.createDirectories()
            val tmp = path.resolveSibling(path.fileName.toString() + ".tmp")
            val text = NutonicJson.encodeToString(PersistedManifestEnvelope.serializer(), envelope)
            tmp.writeText(text)
            try {
                Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(tmp, path, StandardCopyOption.REPLACE_EXISTING)
            }
            Unit
        }
    }
}
