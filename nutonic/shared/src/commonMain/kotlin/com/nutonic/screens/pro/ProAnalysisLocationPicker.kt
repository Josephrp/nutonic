package com.nutonic.screens.pro

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.nutonic.screens.format
import com.nutonic.style.NutonicColors
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard

@Composable
fun ProAnalysisLocationPicker(
    centerLat: Double,
    centerLon: Double,
    bboxHalfKm: Double,
    onCenterChange: (Double, Double) -> Unit,
    onBboxHalfKmChange: (Double) -> Unit,
    modifier: Modifier = Modifier,
) {
    var advancedOpen by rememberSaveable { mutableStateOf(false) }
    var latText by rememberSaveable(centerLat) { mutableStateOf(centerLat.format(5)) }
    var lonText by rememberSaveable(centerLon) { mutableStateOf(centerLon.format(5)) }
    var bboxText by rememberSaveable(bboxHalfKm) { mutableStateOf(bboxHalfKm.format(1)) }

    NutonicGlassCard(modifier = modifier.fillMaxWidth()) {
        Text("Analysis center", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Box(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .height(260.dp)
                    .padding(top = 8.dp)
                    .background(NutonicColors.surfaceContainerLow)
                    .clickable {
                        onCenterChange(
                            (centerLat + 0.01).coerceIn(-90.0, 90.0),
                            (centerLon + 0.01).coerceIn(-180.0, 180.0),
                        )
                    },
            contentAlignment = Alignment.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Map preview", color = MaterialTheme.colors.primary)
                Text("Pin ${centerLat.format()}, ${centerLon.format()}")
                Text("AOI radius ${bboxHalfKm.format(1)} km")
                Text("Tap preview or use controls to move the pin", style = MaterialTheme.typography.caption)
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            NutonicGhostButton(
                text = "North",
                onClick = { onCenterChange((centerLat + 0.01).coerceAtMost(90.0), centerLon) },
                modifier = Modifier.weight(1f),
            )
            NutonicGhostButton(
                text = "East",
                onClick = { onCenterChange(centerLat, (centerLon + 0.01).coerceAtMost(180.0)) },
                modifier = Modifier.weight(1f),
            )
            NutonicGhostButton(
                text = "Use my location",
                onClick = { onCenterChange(centerLat, centerLon) },
                modifier = Modifier.weight(1f),
            )
        }
        NutonicGhostButton(
            text = if (advancedOpen) "Hide coordinate fields" else "Enter coordinates",
            onClick = { advancedOpen = !advancedOpen },
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
        if (advancedOpen) {
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = latText,
                onValueChange = {
                    latText = it
                    it.toDoubleOrNull()?.takeIf { v -> v in -90.0..90.0 }?.let { v -> onCenterChange(v, centerLon) }
                },
                label = { Text("Latitude") },
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = lonText,
                onValueChange = {
                    lonText = it
                    it.toDoubleOrNull()?.takeIf { v -> v in -180.0..180.0 }?.let { v -> onCenterChange(centerLat, v) }
                },
                label = { Text("Longitude") },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            OutlinedTextField(
                value = bboxText,
                onValueChange = {
                    bboxText = it
                    it.toDoubleOrNull()?.takeIf { v -> v > 0.0 && v <= 500.0 }?.let(onBboxHalfKmChange)
                },
                label = { Text("AOI radius km") },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }
    }
}
