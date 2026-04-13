package com.nutonic.settings

/**
 * Cross-platform preference keys (`docs/CLIENT-SETTINGS-SPEC.md` §6 sketch).
 * Platform persistence actuals can back [SettingsRepository] later.
 */
data class ClientSettings(
    /** `game.role` — HUMAN | ASTRONAUT | ALIEN (`docs/CLIENT-SETTINGS-SPEC.md` §6.1). */
    val playerRole: String? = null,
    val reducedMotion: Boolean = false,
    val highContrast: Boolean = false,
    val musicMasterEnabled: Boolean = true,
)
