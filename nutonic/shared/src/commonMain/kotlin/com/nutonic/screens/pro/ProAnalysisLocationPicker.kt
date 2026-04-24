package com.nutonic.screens.pro

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.nutonic.map.BasemapMode
import com.nutonic.map.LatLon
import com.nutonic.map.MapCameraState
import com.nutonic.map.MapGuessState
import com.nutonic.map.MapViewport
import com.nutonic.map.SelfGuessMarker
import com.nutonic.screens.format
import com.nutonic.style.NutonicColors
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard

@Composable
fun ProAnalysisLocationPicker(
    centerLat: Double,
    centerLon: Double,
    bboxHalfKm: Double,
    mapboxZoom: Int,
    onCenterChange: (Double, Double) -> Unit,
    onBboxHalfKmChange: (Double) -> Unit,
    onMapboxZoomChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    var advancedOpen by rememberSaveable { mutableStateOf(false) }
    var basemapMode by rememberSaveable { mutableStateOf(BasemapMode.SATELLITE) }
    var latText by rememberSaveable(centerLat) { mutableStateOf(centerLat.format(5)) }
    var lonText by rememberSaveable(centerLon) { mutableStateOf(centerLon.format(5)) }
    var bboxText by rememberSaveable(bboxHalfKm) { mutableStateOf(bboxHalfKm.format(1)) }
    var cameraState by remember {
        mutableStateOf(
            MapCameraState(
                center = LatLon(centerLat, centerLon).normalized(),
                zoomLevel = mapboxZoom.toDouble(),
            ),
        )
    }

    LaunchedEffect(centerLat, centerLon, mapboxZoom) {
        cameraState =
            MapCameraState(
                center = LatLon(centerLat, centerLon).normalized(),
                zoomLevel = mapboxZoom.toDouble(),
            )
    }

    NutonicGlassCard(modifier = modifier.fillMaxWidth()) {
        Text("Analysis center", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Box(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .height(260.dp)
                    .padding(top = 8.dp)
                    .background(NutonicColors.surfaceContainerLow),
            contentAlignment = Alignment.Center,
        ) {
            MapViewport(
                modifier = Modifier.fillMaxSize(),
                basemapMode = basemapMode,
                cameraState = cameraState,
                viewportBounds = null,
                selfGuess =
                    SelfGuessMarker(
                        coordinate = LatLon(centerLat, centerLon).normalized(),
                        state = MapGuessState.PROVISIONAL,
                    ),
                peerMarker = null,
                aiMarker = null,
                enabled = true,
                onCameraChange = { next ->
                    cameraState = next
                    onCenterChange(next.center.latitude, next.center.longitude)
                    val roundedZoom = next.zoomLevel.toInt().coerceIn(1, 18)
                    onMapboxZoomChange(roundedZoom)
                    onBboxHalfKmChange(bboxHalfKmForZoom(next.zoomLevel))
                },
                onProvisionalGuess = { tapped ->
                    val normalized = tapped.normalized()
                    onCenterChange(normalized.latitude, normalized.longitude)
                    cameraState = cameraState.copy(center = normalized)
                },
            )
        }
        Text(
            "Tap or drag the map to place the analysis pin. Zoom adjusts the AOI radius used for the job.",
            style = MaterialTheme.typography.caption,
            modifier = Modifier.padding(top = 6.dp),
        )
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            NutonicGhostButton(
                text = "Basemap: ${basemapMode.name.lowercase()}",
                onClick = { basemapMode = basemapMode.next() },
                modifier = Modifier.weight(1f),
            )
            NutonicGhostButton(
                text = "Zoom in",
                onClick = {
                    val nextZoom = (mapboxZoom + 1).coerceAtMost(18)
                    onMapboxZoomChange(nextZoom)
                    onBboxHalfKmChange(bboxHalfKmForZoom(nextZoom.toDouble()))
                },
                modifier = Modifier.weight(1f),
            )
            NutonicGhostButton(
                text = "Zoom out",
                onClick = {
                    val nextZoom = (mapboxZoom - 1).coerceAtLeast(1)
                    onMapboxZoomChange(nextZoom)
                    onBboxHalfKmChange(bboxHalfKmForZoom(nextZoom.toDouble()))
                },
                modifier = Modifier.weight(1f),
            )
        }
        Text(
            "Pin ${centerLat.format()}, ${centerLon.format()} · AOI radius ${bboxHalfKm.format(1)} km · zoom $mapboxZoom",
            style = MaterialTheme.typography.caption,
            modifier = Modifier.padding(top = 6.dp),
        )
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
                    it.toDoubleOrNull()?.takeIf { v -> v in -90.0..90.0 }?.let { v ->
                        onCenterChange(v, centerLon)
                    }
                },
                label = { Text("Latitude") },
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = lonText,
                onValueChange = {
                    lonText = it
                    it.toDoubleOrNull()?.takeIf { v -> v in -180.0..180.0 }?.let { v ->
                        onCenterChange(centerLat, v)
                    }
                },
                label = { Text("Longitude") },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            OutlinedTextField(
                value = bboxText,
                onValueChange = {
                    bboxText = it
                    it.toDoubleOrNull()?.takeIf { v -> v > 0.0 && v <= 500.0 }?.let { v ->
                        onBboxHalfKmChange(v)
                        onMapboxZoomChange(zoomForBboxHalfKm(v))
                    }
                },
                label = { Text("AOI radius km") },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }
    }
}

private fun BasemapMode.next(): BasemapMode =
    when (this) {
        BasemapMode.SATELLITE -> BasemapMode.ROADMAP
        BasemapMode.ROADMAP -> BasemapMode.HYBRID
        BasemapMode.HYBRID -> BasemapMode.SATELLITE
    }

private fun bboxHalfKmForZoom(zoom: Double): Double {
    val rounded = zoom.toInt().coerceIn(1, 18)
    return when {
        rounded >= 16 -> 0.5
        rounded >= 15 -> 1.0
        rounded >= 14 -> 2.0
        rounded >= 13 -> 3.0
        rounded >= 12 -> 5.0
        rounded >= 11 -> 8.0
        rounded >= 10 -> 12.0
        rounded >= 9 -> 20.0
        rounded >= 8 -> 35.0
        rounded >= 7 -> 60.0
        rounded >= 6 -> 100.0
        else -> 250.0
    }
}

private fun zoomForBboxHalfKm(bboxHalfKm: Double): Int =
    when {
        bboxHalfKm <= 0.5 -> 16
        bboxHalfKm <= 1.0 -> 15
        bboxHalfKm <= 2.0 -> 14
        bboxHalfKm <= 3.0 -> 13
        bboxHalfKm <= 5.0 -> 12
        bboxHalfKm <= 8.0 -> 11
        bboxHalfKm <= 12.0 -> 10
        bboxHalfKm <= 20.0 -> 9
        bboxHalfKm <= 35.0 -> 8
        bboxHalfKm <= 60.0 -> 7
        bboxHalfKm <= 100.0 -> 6
        else -> 5
    }
