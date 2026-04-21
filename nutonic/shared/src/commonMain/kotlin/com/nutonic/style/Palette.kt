package com.nutonic.style

import androidx.compose.material.LocalTextStyle
import androidx.compose.material.MaterialTheme
import androidx.compose.material.ProvideTextStyle
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.sp

/** When true, prefer non-animated transitions (`docs/CLIENT-SETTINGS-SPEC.md` §4.1). */
val LocalNutonicReducedMotion = compositionLocalOf { false }

/** Default BGM crossfade duration (`docs/SCREEN-MUSIC-SPEC.md`, publishable plan §2.2). */
object NutonicMotion {
    const val crossfadeMs: Int = 400
}

/** Semantic colors from `docs/DESIGN.md` §2–4 (HUD / Void palette). */
object NutonicColors {
    /** Transient toast / snack bar surface (shared across entry points). */
    val toastBackground = Color(23, 23, 23)

    val primary = Color(0xFFC3F5FF)
    val primaryContainer = Color(0xFF00E5FF)
    val secondary = Color(0xFFFFB68B)
    val secondaryContainer = Color(0xFFFF7F1C)
    val tertiary = Color(0xFFAAFFC7)
    val tertiaryContainer = Color(0xFF00EE91)
    val surface = Color(0xFF0F131E)
    val surfaceContainerLowest = Color(0xFF0A0E19)
    val surfaceContainerLow = Color(0xFF171B27)
    val surfaceContainerHigh = Color(0xFF262A36)

    /** Glass / frosted panels (`docs/DESIGN.md` §2) — surface @ ~55% on supported surfaces. */
    val surfaceGlass: Color
        get() = surface.copy(alpha = 0.55f)

    /** Optional card outline “ghost” line (`docs/DESIGN.md` §2 No-Line). */
    val outlineGhost: Color
        get() = Color(0xFF3B494C).copy(alpha = 0.15f)

    /** Matte behind cropped bundled reference stills (SCAN clue imagery). */
    val stillImageMatte = Color(0xFF0F1214)

    /** Placeholder panel while a reference still loads or after a bundle miss. */
    val stillImagePlaceholder = Color(0xFF2B2D30)

    /** Caption text on [stillImagePlaceholder] and other near-black image chrome. */
    val onStillImagePlaceholder = Color(0xFFFFFFFF)

    /** Full-screen dimmer for narrative / blocking overlays on top of gameplay. */
    val overlayScrim = Color(0xAA000000)
}

/**
 * Muted foreground for secondary labels; tracks [MaterialTheme.colors.onSurface] so high-contrast
 * theme overrides stay consistent.
 */
@Composable
fun nutonicOnSurfaceMuted(alpha: Float = 0.75f): Color = MaterialTheme.colors.onSurface.copy(alpha = alpha)

@Composable
fun NutonicTheme(
    reducedMotion: Boolean = false,
    highContrast: Boolean = false,
    content: @Composable () -> Unit,
) {
    val typography = rememberNutonicTypography()
    val onFg =
        if (highContrast) {
            Color(0xFFFFFFFF)
        } else {
            Color(0xFFE8F1F5)
        }
    val bg =
        if (highContrast) {
            Color(0xFF000000)
        } else {
            NutonicColors.surfaceContainerLowest
        }
    val surf =
        if (highContrast) {
            Color(0xFF0A0A0A)
        } else {
            NutonicColors.surface
        }
    val colors =
        MaterialTheme.colors.copy(
            primary = NutonicColors.primary,
            primaryVariant = NutonicColors.primaryContainer,
            secondary = NutonicColors.secondary,
            secondaryVariant = NutonicColors.secondaryContainer,
            background = bg,
            surface = surf,
            onPrimary = NutonicColors.surfaceContainerLowest,
            onSecondary = NutonicColors.surfaceContainerLowest,
            onBackground = onFg,
            onSurface = onFg,
        )
    MaterialTheme(
        colors = colors,
        typography = typography,
        shapes = MaterialTheme.shapes,
    ) {
        ProvideTextStyle(LocalTextStyle.current.copy(letterSpacing = 0.sp)) {
            CompositionLocalProvider(LocalNutonicReducedMotion provides reducedMotion) {
                content()
            }
        }
    }
}
