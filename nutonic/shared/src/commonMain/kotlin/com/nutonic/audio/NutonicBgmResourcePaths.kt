package com.nutonic.audio

/** Compose resource path (`composeResources/files/music/…`, `docs/SCREEN-MUSIC-SPEC.md` §4). */
fun NutonicBgmTrack.composeResourcePath(): String = "files/music/$trackId.wav"
