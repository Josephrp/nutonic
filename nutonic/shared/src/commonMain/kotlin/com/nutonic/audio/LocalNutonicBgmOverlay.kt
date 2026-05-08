package com.nutonic.audio

import androidx.compose.runtime.MutableState
import androidx.compose.runtime.compositionLocalOf

/**
 * Optional override on top of [resolveNutonicBgmTrack] (e.g. success overlay during gameplay,
 * `docs/SCREEN-MUSIC-SPEC.md` §3 **Overlays**). Null means “use route-only mapping”.
 */
val LocalNutonicBgmOverlay =
    compositionLocalOf<MutableState<NutonicBgmTrack?>?> {
        null
    }
