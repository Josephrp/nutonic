package com.nutonic.map

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import kotlin.math.abs
import kotlin.math.ln
import kotlin.math.pow

private const val DESKTOP_MAP_USER_AGENT = "NutonicDesktopMapViewport/1.0"

@Composable
actual fun MapViewport(
    modifier: Modifier,
    basemapMode: BasemapMode,
    cameraState: MapCameraState,
    viewportBounds: ViewportBounds?,
    selfGuess: SelfGuessMarker?,
    peerMarker: LatLon?,
    aiMarker: LatLon?,
    enabled: Boolean,
    onCameraChange: (MapCameraState) -> Unit,
    onProvisionalGuess: (LatLon) -> Unit,
) {
    val boundedExternalCamera = cameraState.normalized(viewportBounds)
    val mapState =
        remember {
            mutableStateOf(
                MapState(
                    latitude = boundedExternalCamera.center.latitude,
                    longitude = boundedExternalCamera.center.longitude,
                    scale = zoomLevelToDesktopScale(boundedExternalCamera.zoomLevel),
                ),
            )
        }
    var lastEmittedCamera by remember { mutableStateOf<MapCameraState?>(null) }

    LaunchedEffect(
        boundedExternalCamera.center.latitude,
        boundedExternalCamera.center.longitude,
        boundedExternalCamera.zoomLevel,
    ) {
        val target =
            MapState(
                latitude = boundedExternalCamera.center.latitude,
                longitude = boundedExternalCamera.center.longitude,
                scale = zoomLevelToDesktopScale(boundedExternalCamera.zoomLevel),
            )
        if (!mapState.value.isApproximately(target)) {
            mapState.value = target
        }
    }

    Box(modifier = modifier) {
        val markerSpecs =
            remember(selfGuess, peerMarker, aiMarker) {
                buildList {
                    selfGuess?.let {
                        val color =
                            when (it.state) {
                                MapGuessState.PROVISIONAL -> Color(0xFFFF9800)
                                MapGuessState.LOCKED -> Color(0xFFD32F2F)
                            }
                        add(DesktopMarkerSpec(it.coordinate.normalized(), color))
                    }
                    peerMarker?.let { add(DesktopMarkerSpec(it.normalized(), Color(0xFF0288D1))) }
                    aiMarker?.let { add(DesktopMarkerSpec(it.normalized(), Color(0xFF388E3C))) }
                }
            }

        MapView(
            modifier = Modifier.fillMaxSize(),
            userAgent = DESKTOP_MAP_USER_AGENT,
            state = mapState,
            onStateChange = { rawState ->
                val nextCamera =
                    MapCameraState(
                        center = LatLon(rawState.latitude, rawState.longitude),
                        zoomLevel = desktopScaleToZoomLevel(rawState.scale),
                    ).normalized(viewportBounds)

                val correctedState =
                    MapState(
                        latitude = nextCamera.center.latitude,
                        longitude = nextCamera.center.longitude,
                        scale = zoomLevelToDesktopScale(nextCamera.zoomLevel),
                    )

                if (!mapState.value.isApproximately(correctedState)) {
                    mapState.value = correctedState
                }

                if (!nextCamera.isApproximately(lastEmittedCamera)) {
                    lastEmittedCamera = nextCamera
                    onCameraChange(nextCamera)
                }
            },
            onMapViewClick = { latitude, longitude ->
                if (!enabled) {
                    return@MapView false
                }
                val rawTap = LatLon(latitude, longitude).normalized()
                val clampedTap = viewportBounds?.clamp(rawTap) ?: rawTap
                onProvisionalGuess(clampedTap)
                false
            },
            foregroundDraw = { projection ->
                drawDesktopMarkerSpecs(projection, markerSpecs)
            },
        )

        if (basemapMode != BasemapMode.ROADMAP) {
            Text(
                text = "Desktop engine uses OSM roadmap tiles. ${basemapMode.name.lowercase()} falls back to roadmap.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onSurface,
                textAlign = TextAlign.End,
                modifier =
                    Modifier
                        .align(Alignment.TopEnd)
                        .padding(10.dp)
                        .background(MaterialTheme.colors.surface.copy(alpha = 0.85f))
                        .padding(horizontal = 8.dp, vertical = 4.dp),
            )
        }
    }
}

private fun DrawScope.drawDesktopMarkerSpecs(
    projection: InternalMapState,
    markers: List<DesktopMarkerSpec>,
) {
    if (markers.isEmpty() || size.width <= 0f || size.height <= 0f) {
        return
    }

    val worldWidth = projection.geoLengthToDisplay(1.0).toDouble().coerceAtLeast(1.0)
    val viewportWidth = size.width.toDouble()

    markers.forEach { marker ->
        val display = projection.geoToDisplay(createGeoPt(marker.coordinate.latitude, marker.coordinate.longitude))
        val wrappedX = wrapDisplayX(display.x.toDouble(), worldWidth, viewportWidth).toFloat()
        val y = display.y.toFloat()
        if (wrappedX < -24f || wrappedX > size.width + 24f || y < -24f || y > size.height + 24f) {
            return@forEach
        }

        drawCircle(
            color = Color.White,
            radius = 11f,
            center = Offset(wrappedX, y),
        )
        drawCircle(
            color = marker.color,
            radius = 7f,
            center = Offset(wrappedX, y),
        )
    }
}

private data class DesktopMarkerSpec(
    val coordinate: LatLon,
    val color: Color,
)

private fun MapState.isApproximately(other: MapState): Boolean =
    abs(latitude - other.latitude) < 0.00001 &&
        abs(longitude - other.longitude) < 0.00001 &&
        abs(scale - other.scale) < 0.01

private fun zoomLevelToDesktopScale(zoomLevel: Double): Double = 2.0.pow(zoomLevel.coerceIn(MIN_MAP_ZOOM_LEVEL, MAX_MAP_ZOOM_LEVEL))

private fun desktopScaleToZoomLevel(scale: Double): Double {
    val safeScale = scale.coerceAtLeast(1.0)
    return (ln(safeScale) / ln(2.0)).coerceIn(MIN_MAP_ZOOM_LEVEL, MAX_MAP_ZOOM_LEVEL)
}

private fun wrapDisplayX(
    x: Double,
    worldWidth: Double,
    viewportWidth: Double,
): Double {
    if (worldWidth <= 0.0) {
        return x
    }

    val center = viewportWidth / 2.0
    var candidate = x
    while (candidate < -worldWidth) {
        candidate += worldWidth
    }
    while (candidate > viewportWidth + worldWidth) {
        candidate -= worldWidth
    }

    var best = candidate
    var distance = abs(best - center)

    val right = candidate + worldWidth
    val rightDistance = abs(right - center)
    if (rightDistance < distance) {
        best = right
        distance = rightDistance
    }

    val left = candidate - worldWidth
    val leftDistance = abs(left - center)
    if (leftDistance < distance) {
        best = left
    }

    return best
}
