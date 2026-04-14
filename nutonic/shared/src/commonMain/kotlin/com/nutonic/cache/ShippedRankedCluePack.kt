package com.nutonic.cache

import com.nutonic.api.NutonicJson
import com.nutonic.api.RankedClue
import com.nutonic.api.RankedCluePackDocument
import com.nutonic.resources.Res

/**
 * Bundled ranked clue slice (`plans/2026-04-14-shipped-cache-narrative-hint-pipeline.md` §3, §7).
 * Merged with [com.nutonic.api.RankedRoundStartOut.clue] so assists stay available when the wire
 * payload is intentionally thin.
 */
object ShippedRankedCluePaths {
    const val PACK: String = "files/ranked/ranked_clue_pack.json"
}

/**
 * Overlay optional assists from the shipped pack when the API clue omits them (same `map_id` /
 * `location_id`). API non-empty values win.
 */
fun mergeRankedClueWithPack(
    clue: RankedClue,
    pack: RankedCluePackDocument?,
): RankedClue {
    if (pack == null) return clue
    val slice = pack.clues.find { it.mapId == clue.mapId && it.locationId == clue.locationId } ?: return clue
    return clue.copy(
        usefulHints = clue.usefulHints ?: slice.usefulHints,
        streetviewHintPack =
            clue.streetviewHintPack?.takeIf { it.isNotEmpty() }
                ?: slice.streetviewHintPack?.takeIf { it.isNotEmpty() },
        streetviewAssistNarrative =
            clue.streetviewAssistNarrative?.takeIf { it.isNotBlank() }
                ?: slice.streetviewAssistNarrative?.takeIf { it.isNotBlank() },
        stillBundleId = clue.stillBundleId ?: slice.stillBundleId,
        stillBundledResource = clue.stillBundledResource ?: slice.stillBundledResource,
        playBudgetMs = clue.playBudgetMs ?: slice.playBudgetMs,
        aiMarkerPhaseEnabled = clue.aiMarkerPhaseEnabled,
    )
}

suspend fun readShippedRankedCluePack(): RankedCluePackDocument? =
    runCatching {
        val text = Res.readBytes(ShippedRankedCluePaths.PACK).decodeToString()
        NutonicJson.decodeFromString(RankedCluePackDocument.serializer(), text)
    }.getOrNull()
