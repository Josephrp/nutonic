package com.nutonic.settings

/**
 * Cross-platform preference keys (`docs/CLIENT-SETTINGS-SPEC.md` §6 sketch).
 * Platform persistence actuals can back [SettingsRepository] later.
 */
data class ClientSettings(
    /** `game.role` — HUMAN | ASTRONAUT | ALIEN (`docs/CLIENT-SETTINGS-SPEC.md` §6.1). */
    val playerRole: String? = null,
    val displayName: String = "",
    val showRankBadge: Boolean = true,
    val reducedMotion: Boolean = false,
    val highContrast: Boolean = false,
    val largeDataRendering: Boolean = false,
    val musicMasterEnabled: Boolean = true,
    val musicVolume: Float = 0.85f,
    val sfxVolume: Float = 0.42f,
    val muteWhenBackgrounded: Boolean = true,
    val showNonAiHints: Boolean = true,
    val showAiGroundHints: Boolean = false,
    val showCoordinateReadout: Boolean = true,
    val showTimer: Boolean = true,
    val showScorePreview: Boolean = true,
    val confirmBeforeSubmit: Boolean = true,
    val rememberLastViewport: Boolean = false,
    val overlayDefaultOpen: Boolean = false,
    val preserveNarrativeNotes: Boolean = true,
    val allowAnalytics: Boolean = false,
    val allowOptionalCommunitySync: Boolean = false,
    val autoRefetchLeaderboard: Boolean = false,
)
