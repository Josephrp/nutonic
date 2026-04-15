package com.nutonic.screens

import androidx.compose.material.Icon
import androidx.compose.material.IconButton
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.material.TopAppBar
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/** Global music master in the header zone (`docs/SCREEN-MUSIC-SPEC` §5); route BGM is driven from [com.nutonic.NutonicApp]. */
@Composable
fun NutonicMusicMasterTopBar(
    musicMasterEnabled: Boolean,
    onMusicMasterChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    TopAppBar(
        modifier = modifier,
        backgroundColor = MaterialTheme.colors.surface,
        title = {
            Text(
                text = "NU:TONIC",
                style = MaterialTheme.typography.subtitle1,
                color = MaterialTheme.colors.onSurface,
            )
        },
        actions = {
            IconButton(onClick = { onMusicMasterChange(!musicMasterEnabled) }) {
                Icon(
                    imageVector = if (musicMasterEnabled) Icons.AutoMirrored.Filled.VolumeUp else Icons.AutoMirrored.Filled.VolumeOff,
                    contentDescription = if (musicMasterEnabled) "Mute music" else "Unmute music",
                    tint = MaterialTheme.colors.onSurface,
                )
            }
        },
    )
}
