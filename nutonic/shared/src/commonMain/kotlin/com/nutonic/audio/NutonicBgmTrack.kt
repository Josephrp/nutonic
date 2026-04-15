package com.nutonic.audio

/**
 * Canonical loop ids (`docs/SCREEN-MUSIC-SPEC.md` §3). Filenames under
 * `composeResources/files/music/` should match when assets ship.
 */
enum class NutonicBgmTrack(
    val trackId: String,
) {
    MusicSplash("music_splash"),
    MusicAuth("music_auth"),
    MusicRole("music_role"),
    MusicScanHub("music_scan_hub"),
    MusicGameplay("music_gameplay"),
    MusicSuccess("music_success"),
    MusicResults("music_results"),
    MusicIntel("music_intel"),
    MusicRank("music_rank"),
    MusicSetup("music_setup"),
    MusicPro("music_pro"),
    ;

    companion object {
        fun fromTrackId(id: String): NutonicBgmTrack? = entries.find { it.trackId == id }
    }
}
