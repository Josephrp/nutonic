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

/** Legacy photo-gallery toast / chrome accents; prefer [NutonicColors] for new UI. */
object NutonicPhotoGalleryColors {
    val ToastBackground = Color(23, 23, 23)
    val background = Color(0xFFFFFFFF)
    val onBackground = Color(0xFF19191C)

    val fullScreenImageBackground = Color(0xFF19191C)
    val filterButtonsBackground = fullScreenImageBackground.copy(alpha = 0.7f)
    val uiLightBlack = Color(25, 25, 28).copy(alpha = 0.7f)
    val noteBlockBackground = Color(0xFFF3F3F4)
}

/** Semantic colors from `docs/DESIGN.md` §2–4 (HUD / Void palette). */
object NutonicColors {
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
}

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
