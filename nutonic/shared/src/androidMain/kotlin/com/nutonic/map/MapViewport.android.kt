package com.nutonic.map

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import com.google.android.gms.maps.CameraUpdateFactory
import com.google.android.gms.maps.model.BitmapDescriptorFactory
import com.google.android.gms.maps.model.CameraPosition
import com.google.android.gms.maps.model.LatLng
import com.google.android.gms.maps.model.LatLngBounds
import com.google.maps.android.compose.GoogleMap
import com.google.maps.android.compose.MapProperties
import com.google.maps.android.compose.MapType
import com.google.maps.android.compose.MapUiSettings
import com.google.maps.android.compose.Marker
import com.google.maps.android.compose.MarkerState
import com.google.maps.android.compose.rememberCameraPositionState
import kotlin.math.abs

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
    val initialPosition =
        CameraPosition.fromLatLngZoom(
            boundedExternalCamera.center.toLatLng(),
            boundedExternalCamera.zoomLevel.toFloat(),
        )
    val cameraPositionState =
        rememberCameraPositionState {
            position = initialPosition
        }

    var lastEmittedCamera by remember { mutableStateOf<MapCameraState?>(null) }

    LaunchedEffect(
        boundedExternalCamera.center.latitude,
        boundedExternalCamera.center.longitude,
        boundedExternalCamera.zoomLevel,
    ) {
        val target =
            CameraPosition.fromLatLngZoom(
                boundedExternalCamera.center.toLatLng(),
                boundedExternalCamera.zoomLevel.toFloat(),
            )
        if (!cameraPositionState.position.isApproximately(target)) {
            cameraPositionState.move(CameraUpdateFactory.newCameraPosition(target))
        }
    }

    LaunchedEffect(cameraPositionState, viewportBounds) {
        snapshotFlow { cameraPositionState.position }.collect { position ->
            val nextCamera =
                MapCameraState(
                    center = LatLon(position.target.latitude, position.target.longitude),
                    zoomLevel = position.zoom.toDouble(),
                ).normalized(viewportBounds)

            if (!nextCamera.isApproximately(lastEmittedCamera)) {
                lastEmittedCamera = nextCamera
                onCameraChange(nextCamera)
            }
        }
    }

    val properties =
        MapProperties(
            mapType = basemapMode.toAndroidMapType(),
            latLngBoundsForCameraTarget = viewportBounds?.toLatLngBounds(),
        )

    GoogleMap(
        modifier = modifier,
        cameraPositionState = cameraPositionState,
        properties = properties,
        uiSettings = MapUiSettings(zoomControlsEnabled = false, myLocationButtonEnabled = false),
        onMapClick = { tapped ->
            if (!enabled) {
                return@GoogleMap
            }
            val rawTap = LatLon(tapped.latitude, tapped.longitude).normalized()
            val clamped = viewportBounds?.clamp(rawTap) ?: rawTap
            onProvisionalGuess(clamped)
        },
    ) {
        selfGuess?.let {
            Marker(
                state = MarkerState(it.coordinate.toLatLng()),
                title = when (it.state) {
                    MapGuessState.PROVISIONAL -> "Your provisional guess"
                    MapGuessState.LOCKED -> "Your locked guess"
                },
                icon = BitmapDescriptorFactory.defaultMarker(it.state.toMarkerHue()),
            )
        }
        peerMarker?.let {
            Marker(
                state = MarkerState(it.normalized().toLatLng()),
                title = "Peer hint",
                icon = BitmapDescriptorFactory.defaultMarker(BitmapDescriptorFactory.HUE_AZURE),
            )
        }
        aiMarker?.let {
            Marker(
                state = MarkerState(it.normalized().toLatLng()),
                title = "AI guess",
                icon = BitmapDescriptorFactory.defaultMarker(BitmapDescriptorFactory.HUE_GREEN),
            )
        }
    }
}

private fun BasemapMode.toAndroidMapType(): MapType =
    when (this) {
        BasemapMode.SATELLITE -> MapType.SATELLITE
        BasemapMode.ROADMAP -> MapType.NORMAL
        BasemapMode.HYBRID -> MapType.HYBRID
    }

private fun MapGuessState.toMarkerHue(): Float =
    when (this) {
        MapGuessState.PROVISIONAL -> BitmapDescriptorFactory.HUE_ORANGE
        MapGuessState.LOCKED -> BitmapDescriptorFactory.HUE_RED
    }

private fun ViewportBounds.toLatLngBounds(): LatLngBounds =
    LatLngBounds(
        LatLng(minLatitude, minLongitude),
        LatLng(maxLatitude, maxLongitude),
    )

private fun LatLon.toLatLng(): LatLng = LatLng(latitude, longitude)

private fun CameraPosition.isApproximately(other: CameraPosition): Boolean =
    abs(target.latitude - other.target.latitude) < 0.00001 &&
        abs(target.longitude - other.target.longitude) < 0.00001 &&
        abs(zoom - other.zoom) < 0.02


