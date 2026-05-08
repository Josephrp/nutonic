package com.nutonic.audio

import com.nutonic.style.NutonicMotion

/**
 * Platform decoder/output (`rules/03-kotlin-multiplatform-structure.md` §Audio).
 * Loops live under `composeResources/files/music/<track_id>.wav` (`docs/SCREEN-MUSIC-SPEC.md` §4);
 * playback no-ops when assets are missing or the host has no audio mixer (e.g. headless CI).
 */
expect class PlatformBgmPlayer() {
    suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
        crossfadeMs: Int = NutonicMotion.crossfadeMs,
    )
}
