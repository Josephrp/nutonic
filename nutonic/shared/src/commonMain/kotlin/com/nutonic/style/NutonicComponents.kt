package com.nutonic.style

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CornerSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Button
import androidx.compose.material.ButtonDefaults
import androidx.compose.material.Card
import androidx.compose.material.LocalContentColor
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Primary / ghost CTA corner radius (publishable plan §2.2: 12–16dp). */
val NutonicCtaShape = RoundedCornerShape(CornerSize(14.dp))

@Composable
fun NutonicGlassCard(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Card(
        modifier = modifier,
        shape = RoundedCornerShape(12.dp),
        backgroundColor = NutonicColors.surfaceGlass,
        border = BorderStroke(width = 1.dp, color = NutonicColors.primary.copy(alpha = 0.12f)),
        elevation = 0.dp,
    ) {
        CompositionLocalProvider(LocalContentColor provides MaterialTheme.colors.onBackground) {
            androidx.compose.foundation.layout.Column(modifier = Modifier.padding(12.dp)) {
                content()
            }
        }
    }
}

@Composable
fun NutonicPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        modifier = modifier,
        enabled = enabled,
        shape = NutonicCtaShape,
        colors =
            ButtonDefaults.buttonColors(
                backgroundColor = MaterialTheme.colors.primaryVariant,
                contentColor = MaterialTheme.colors.onPrimary,
                disabledBackgroundColor = NutonicColors.surfaceContainerHigh,
            ),
    ) {
        Text(text)
    }
}

@Composable
fun NutonicGhostButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier,
        enabled = enabled,
        shape = NutonicCtaShape,
        border = BorderStroke(1.dp, NutonicColors.primary.copy(alpha = 0.28f)),
        colors =
            ButtonDefaults.outlinedButtonColors(
                backgroundColor = NutonicColors.surfaceContainerLow.copy(alpha = 0.35f),
                contentColor = NutonicColors.primary,
            ),
    ) {
        Text(text)
    }
}
