package com.nutonic.style

/**
 * Central waiver list for raw color literals outside [NutonicColors] / Material theme tokens.
 * Per `rules/08` and publishable UI plan §2.2: new feature composables should use semantic tokens;
 * exceptions are recorded here with a short product/engineering note.
 */
object ThemeExceptions {
    /** Legacy Material-era placeholders in gameplay reference card (migrate when HUD tokens land). */
    val gameplayReferenceCardNotes: String =
        "Reference still card uses NutonicColors.stillImage* only; no extra raw hex waivers."
}
