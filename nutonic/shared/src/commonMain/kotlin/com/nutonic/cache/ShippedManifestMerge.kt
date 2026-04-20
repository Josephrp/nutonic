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

enum class ShippedManifestMergeOutcome {
    NO_SHIPPED_MANIFEST,
    VERSION_MISMATCH,
    NETWORK_HAS_ROUND_TRUTH,
    OVERLAID_FROM_SHIPPED,
}

data class ShippedManifestMergeResult(
    val document: CacheManifestDocument,
    val outcome: ShippedManifestMergeOutcome,
    val shippedContentVersion: String? = null,
)

/**
 * When the reference server returns a **redacted** manifest (empty `locations` / `ai_guesses`),
 * overlay the shipped bundle so SCAN gameplay stays offline-capable without
 * `NUTONIC_EXPOSE_MANIFEST_ROUND_TRUTH` on the wire.
 */
fun mergeShippedRoundTruthDetailed(
    networkOrPersisted: CacheManifestDocument,
    shippedFull: CacheManifestDocument?,
): ShippedManifestMergeResult {
    if (shippedFull == null) {
        return ShippedManifestMergeResult(
            document = networkOrPersisted,
            outcome = ShippedManifestMergeOutcome.NO_SHIPPED_MANIFEST,
            shippedContentVersion = null,
        )
    }
    val contentVersionMatches = networkOrPersisted.contentVersion == shippedFull.contentVersion
    val needsLocationOverlay = networkOrPersisted.locations.isEmpty() && shippedFull.locations.isNotEmpty()
    val needsAiOverlay = networkOrPersisted.aiGuesses.isEmpty() && shippedFull.aiGuesses.isNotEmpty()
    if (!needsLocationOverlay && !needsAiOverlay && networkOrPersisted.locations.isNotEmpty()) {
        return ShippedManifestMergeResult(
            document = networkOrPersisted,
            outcome =
                if (contentVersionMatches) {
                    ShippedManifestMergeOutcome.NETWORK_HAS_ROUND_TRUTH
                } else {
                    ShippedManifestMergeOutcome.VERSION_MISMATCH
                },
            shippedContentVersion = shippedFull.contentVersion,
        )
    }
    if (!needsLocationOverlay && !needsAiOverlay) {
        return ShippedManifestMergeResult(
            document = networkOrPersisted,
            outcome =
                if (contentVersionMatches) {
                    ShippedManifestMergeOutcome.NETWORK_HAS_ROUND_TRUTH
                } else {
                    ShippedManifestMergeOutcome.VERSION_MISMATCH
                },
            shippedContentVersion = shippedFull.contentVersion,
        )
    }
    return ShippedManifestMergeResult(
        document =
            networkOrPersisted.copy(
                locations =
                    if (needsLocationOverlay) {
                        shippedFull.locations
                    } else {
                        networkOrPersisted.locations
                    },
                aiGuesses =
                    if (needsAiOverlay) {
                        shippedFull.aiGuesses
                    } else {
                        networkOrPersisted.aiGuesses
                    },
            ),
        outcome =
            if (contentVersionMatches) {
                ShippedManifestMergeOutcome.OVERLAID_FROM_SHIPPED
            } else {
                ShippedManifestMergeOutcome.VERSION_MISMATCH
            },
        shippedContentVersion = shippedFull.contentVersion,
    )
}

fun mergeShippedRoundTruth(
    networkOrPersisted: CacheManifestDocument,
    shippedFull: CacheManifestDocument?,
): CacheManifestDocument = mergeShippedRoundTruthDetailed(networkOrPersisted, shippedFull).document

suspend fun readShippedFullManifest(): CacheManifestDocument? =
    runCatching {
        val text = Res.readBytes(ShippedManifestPaths.FULL).decodeToString()
        NutonicJson.decodeFromString<CacheManifestDocument>(text)
    }.getOrNull()
