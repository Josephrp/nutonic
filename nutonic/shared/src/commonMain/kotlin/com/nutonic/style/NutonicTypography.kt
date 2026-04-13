@file:OptIn(org.jetbrains.compose.resources.ExperimentalResourceApi::class)

package com.nutonic.style

import androidx.compose.material.Typography
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.nutonic.resources.Res
import com.nutonic.resources.allFontResources
import org.jetbrains.compose.resources.Font as ComposeFont

/**
 * Three-family stack from [docs/DESIGN.md] §3 — Space Grotesk (display), Inter (UI/body), Orbitron (tactical / HUD).
 * Fonts are vendored under `composeResources/font/` (no runtime CDN).
 *
 * Uses [Res.allFontResources] keys so we avoid fragile `Res.font.*` imports (nested `font` vs [ComposeFont] name).
 * [ComposeFont] is @[Composable]; families are built once per composition via [remember].
 */
@Composable
fun rememberNutonicTypography(): Typography {
    val spaceRes = Res.allFontResources.getValue("SpaceGroteskVariable")
    val interRes = Res.allFontResources.getValue("InterVariable")
    val orbitronRes = Res.allFontResources.getValue("OrbitronVariable")
    val spaceGroteskFamily =
        FontFamily(
            ComposeFont(spaceRes, weight = FontWeight.Normal),
            ComposeFont(spaceRes, weight = FontWeight.SemiBold),
            ComposeFont(spaceRes, weight = FontWeight.Bold),
        )
    val interFamily =
        FontFamily(
            ComposeFont(interRes, weight = FontWeight.Normal),
            ComposeFont(interRes, weight = FontWeight.Medium),
            ComposeFont(interRes, weight = FontWeight.SemiBold),
        )
    val orbitronFamily =
        FontFamily(
            ComposeFont(orbitronRes, weight = FontWeight.Normal),
            ComposeFont(orbitronRes, weight = FontWeight.Medium),
            ComposeFont(orbitronRes, weight = FontWeight.SemiBold),
            ComposeFont(orbitronRes, weight = FontWeight.Bold),
        )
    return remember(spaceGroteskFamily, interFamily, orbitronFamily) {
        Typography(
            defaultFontFamily = interFamily,
            h4 =
                TextStyle(
                    fontFamily = spaceGroteskFamily,
                    fontWeight = FontWeight.Bold,
                    fontSize = 34.sp,
                    letterSpacing = 1.7.sp,
                ),
            h5 =
                TextStyle(
                    fontFamily = spaceGroteskFamily,
                    fontWeight = FontWeight.Bold,
                    fontSize = 24.sp,
                    letterSpacing = 1.2.sp,
                ),
            h6 =
                TextStyle(
                    fontFamily = spaceGroteskFamily,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 20.sp,
                    letterSpacing = 1.sp,
                ),
            subtitle1 =
                TextStyle(
                    fontFamily = interFamily,
                    fontWeight = FontWeight.Medium,
                    fontSize = 16.sp,
                    letterSpacing = 0.15.sp,
                ),
            subtitle2 =
                TextStyle(
                    fontFamily = interFamily,
                    fontWeight = FontWeight.Normal,
                    fontSize = 14.sp,
                    letterSpacing = 0.1.sp,
                ),
            body1 =
                TextStyle(
                    fontFamily = interFamily,
                    fontWeight = FontWeight.Normal,
                    fontSize = 16.sp,
                    letterSpacing = 0.25.sp,
                ),
            body2 =
                TextStyle(
                    fontFamily = interFamily,
                    fontWeight = FontWeight.Normal,
                    fontSize = 14.sp,
                    letterSpacing = 0.25.sp,
                ),
            button =
                TextStyle(
                    fontFamily = interFamily,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 14.sp,
                    letterSpacing = 0.5.sp,
                ),
            caption =
                TextStyle(
                    fontFamily = orbitronFamily,
                    fontWeight = FontWeight.Medium,
                    fontSize = 12.sp,
                    letterSpacing = 0.4.sp,
                ),
            overline =
                TextStyle(
                    fontFamily = orbitronFamily,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 10.sp,
                    letterSpacing = 0.8.sp,
                ),
        )
    }
}
