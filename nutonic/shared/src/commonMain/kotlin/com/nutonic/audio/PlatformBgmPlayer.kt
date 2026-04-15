package com.nutonic.audio

/**
 * Platform decoder/output (`rules/03-kotlin-multiplatform-structure.md` §Audio).
 * Stubs until bundled loops exist under `composeResources/files/music/`.
 */
expect class PlatformBgmPlayer() {
    suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
    )
}
