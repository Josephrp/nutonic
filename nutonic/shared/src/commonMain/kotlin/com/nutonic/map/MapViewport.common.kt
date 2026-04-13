package com.nutonic.map

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

enum class BasemapMode {
    SATELLITE,
    ROADMAP,
    HYBRID,
}

enum class MapGuessState {
    PROVISIONAL,
    LOCKED,
}

@Immutable
data class LatLon(
    val latitude: Double,
    val longitude: Double,
) {
    fun normalized(): LatLon =
        copy(
            latitude = latitude.coerceIn(-90.0, 90.0),
            longitude = normalizeLongitude(longitude),
        )
}

@Immutable
data class MapCameraState(
    val center: LatLon,
    val zoomLevel: Double,
) {
    fun normalized(bounds: ViewportBounds?): MapCameraState {
        val boundedCenter = bounds?.clamp(center) ?: center.normalized()
        val normalizedZoom = zoomLevel.coerceIn(MIN_MAP_ZOOM_LEVEL, MAX_MAP_ZOOM_LEVEL)
        return copy(center = boundedCenter, zoomLevel = normalizedZoom)
    }
}

@Immutable
data class ViewportBounds(
    val minLatitude: Double,
    val maxLatitude: Double,
    val minLongitude: Double,
    val maxLongitude: Double,
) {
    init {
        require(minLatitude <= maxLatitude) {
            "minLatitude must be <= maxLatitude"
        }
        require(minLongitude <= maxLongitude) {
            "minLongitude must be <= maxLongitude"
        }
    }

    fun clamp(value: LatLon): LatLon =
        value
            .normalized()
            .let {
                LatLon(
                    latitude = it.latitude.coerceIn(minLatitude, maxLatitude),
                    longitude = it.longitude.coerceIn(minLongitude, maxLongitude),
                )
            }
}

@Immutable
data class SelfGuessMarker(
    val coordinate: LatLon,
    val state: MapGuessState,
)

const val MIN_MAP_ZOOM_LEVEL: Double = 1.0
const val MAX_MAP_ZOOM_LEVEL: Double = 20.0

@Composable
expect fun MapViewport(
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
)

internal fun MapCameraState.isApproximately(other: MapCameraState?): Boolean {
    if (other == null) {
        return false
    }
    return center.isApproximately(other.center) && abs(zoomLevel - other.zoomLevel) < 0.02
}

internal fun LatLon.isApproximately(other: LatLon): Boolean =
    abs(latitude - other.latitude) < 0.00001 && abs(normalizeLongitude(longitude - other.longitude)) < 0.00001

internal fun normalizeLongitude(longitude: Double): Double {
    var normalized = longitude
    while (normalized < -180.0) {
        normalized += 360.0
    }
    while (normalized > 180.0) {
        normalized -= 360.0
    }
    return max(-180.0, min(180.0, normalized))
}
