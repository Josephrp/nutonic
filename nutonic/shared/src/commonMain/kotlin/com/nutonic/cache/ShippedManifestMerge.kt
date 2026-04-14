package com.nutonic.cache

import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.NutonicJson
import com.nutonic.resources.Res

/**
 * Compose path to the bundled full manifest (non-ranked round truth + assists).
 * Kept in lockstep with [server.catalog] and `data/scripts/assemble_manifest` output
 * (`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md` §3, §7).
 */
object ShippedManifestPaths {
    const val FULL: String = "files/cache/manifest.full.json"
}

/**
 * When the reference server returns a **redacted** manifest (empty `locations` / `ai_guesses`),
 * overlay the shipped bundle so SCAN gameplay stays offline-capable without
 * `NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH` on the wire.
 */
fun mergeShippedRoundTruth(
    networkOrPersisted: CacheManifestDocument,
    shippedFull: CacheManifestDocument?,
): CacheManifestDocument {
    if (shippedFull == null) return networkOrPersisted
    if (networkOrPersisted.contentVersion != shippedFull.contentVersion) {
        return networkOrPersisted
    }
    if (networkOrPersisted.locations.isNotEmpty()) {
        return networkOrPersisted
    }
    return networkOrPersisted.copy(
        locations = shippedFull.locations,
        aiGuesses = shippedFull.aiGuesses,
    )
}

suspend fun readShippedFullManifest(): CacheManifestDocument? =
    runCatching {
        val text = Res.readBytes(ShippedManifestPaths.FULL).decodeToString()
        NutonicJson.decodeFromString<CacheManifestDocument>(text)
    }.getOrNull()
