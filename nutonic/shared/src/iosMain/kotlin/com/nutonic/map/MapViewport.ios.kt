package com.nutonic.map

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.interop.UIKitView
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.ObjCAction
import kotlinx.cinterop.useContents
import platform.CoreLocation.CLLocationCoordinate2DMake
import platform.Foundation.NSSelectorFromString
import platform.MapKit.MKCoordinateRegionMakeWithDistance
import platform.MapKit.MKMapTypeHybrid
import platform.MapKit.MKMapTypeSatellite
import platform.MapKit.MKMapTypeStandard
import platform.MapKit.MKMapView
import platform.MapKit.MKMapViewDelegateProtocol
import platform.MapKit.MKPointAnnotation
import platform.UIKit.UITapGestureRecognizer
import platform.darwin.NSObject
import kotlin.math.ln
import kotlin.math.pow

@OptIn(ExperimentalForeignApi::class)
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
    val mapView = remember { MKMapView() }
    val annotationStore = remember { IosAnnotationStore() }

    val updatedBounds = rememberUpdatedState(viewportBounds)
    val updatedOnCameraChange = rememberUpdatedState(onCameraChange)
    val updatedOnProvisionalGuess = rememberUpdatedState(onProvisionalGuess)
    val updatedEnabled = rememberUpdatedState(enabled)

    val delegate =
        remember {
            IosMapViewportDelegate(
                viewportBounds = { updatedBounds.value },
                onCameraChange = { updatedOnCameraChange.value(it) },
            )
        }

    val tapHandler =
        remember {
            IosMapTapHandler(
                mapViewProvider = { mapView },
                viewportBounds = { updatedBounds.value },
                enabled = { updatedEnabled.value },
                onProvisionalGuess = { updatedOnProvisionalGuess.value(it) },
            )
        }

    DisposableEffect(mapView, delegate, tapHandler) {
        mapView.delegate = delegate
        val recognizer =
            UITapGestureRecognizer(
                target = tapHandler,
                action = NSSelectorFromString(IosMapTapHandler::handleTap.name + ":"),
            )
        mapView.addGestureRecognizer(recognizer)

        onDispose {
            mapView.removeGestureRecognizer(recognizer)
            mapView.delegate = null
        }
    }

    UIKitView(
        modifier = modifier,
        factory = { mapView },
        update = { view ->
            val boundedCamera = cameraState.normalized(viewportBounds)
            applyMapType(view, basemapMode)
            applyCameraIfNeeded(view, boundedCamera)
            updateAnnotations(view, annotationStore, selfGuess, peerMarker, aiMarker)
        },
    )
}

@OptIn(ExperimentalForeignApi::class)
private fun applyCameraIfNeeded(
    mapView: MKMapView,
    cameraState: MapCameraState,
) {
    val currentCenter =
        mapView.centerCoordinate.useContents {
            LatLon(latitude, longitude).normalized()
        }
    val currentZoom =
        mapView.region.useContents {
            longitudeDeltaToZoom(span.longitudeDelta)
        }
    val currentState = MapCameraState(currentCenter, currentZoom)

    if (cameraState.isApproximately(currentState)) {
        return
    }

    val center = CLLocationCoordinate2DMake(cameraState.center.latitude, cameraState.center.longitude)
    val distance = zoomToRegionMeters(cameraState.zoomLevel)
    mapView.setRegion(
        MKCoordinateRegionMakeWithDistance(
            centerCoordinate = center,
            latitudinalMeters = distance,
            longitudinalMeters = distance,
        ),
        animated = false,
    )
}

private fun applyMapType(
    mapView: MKMapView,
    basemapMode: BasemapMode,
) {
    mapView.mapType =
        when (basemapMode) {
            BasemapMode.SATELLITE -> MKMapTypeSatellite
            BasemapMode.ROADMAP -> MKMapTypeStandard
            BasemapMode.HYBRID -> MKMapTypeHybrid
        }
}

@OptIn(ExperimentalForeignApi::class)
private fun updateAnnotations(
    mapView: MKMapView,
    store: IosAnnotationStore,
    selfGuess: SelfGuessMarker?,
    peerMarker: LatLon?,
    aiMarker: LatLon?,
) {
    store.annotations.forEach { mapView.removeAnnotation(it) }

    val next =
        buildList {
            selfGuess?.let {
                add(
                    mkAnnotation(
                        coordinate = it.coordinate.normalized(),
                        title =
                            when (it.state) {
                                MapGuessState.PROVISIONAL -> "YOU (provisional)"
                                MapGuessState.LOCKED -> "YOU (locked)"
                            },
                    ),
                )
            }
            peerMarker?.let { add(mkAnnotation(it.normalized(), "PEER")) }
            aiMarker?.let { add(mkAnnotation(it.normalized(), "AI")) }
        }

    next.forEach { mapView.addAnnotation(it) }
    store.annotations = next
}

@OptIn(ExperimentalForeignApi::class)
private fun mkAnnotation(
    coordinate: LatLon,
    title: String,
): MKPointAnnotation =
    MKPointAnnotation(
        coordinate = CLLocationCoordinate2DMake(coordinate.latitude, coordinate.longitude),
        title = title,
        subtitle = null,
    )

@OptIn(ExperimentalForeignApi::class)
private class IosMapViewportDelegate(
    private val viewportBounds: () -> ViewportBounds?,
    private val onCameraChange: (MapCameraState) -> Unit,
) : NSObject(),
    MKMapViewDelegateProtocol {
    private var lastEmitted: MapCameraState? = null

    override fun mapViewDidChangeVisibleRegion(mapView: MKMapView) {
        val center =
            mapView.centerCoordinate.useContents {
                LatLon(latitude, longitude).normalized()
            }
        val zoom =
            mapView.region.useContents {
                longitudeDeltaToZoom(span.longitudeDelta)
            }

        val next = MapCameraState(center, zoom).normalized(viewportBounds())
        if (!next.isApproximately(lastEmitted)) {
            lastEmitted = next
            onCameraChange(next)
        }
    }
}

@OptIn(ExperimentalForeignApi::class)
private class IosMapTapHandler(
    private val mapViewProvider: () -> MKMapView,
    private val viewportBounds: () -> ViewportBounds?,
    private val enabled: () -> Boolean,
    private val onProvisionalGuess: (LatLon) -> Unit,
) : NSObject() {
    @Suppress("unused")
    @ObjCAction
    fun handleTap(gesture: UITapGestureRecognizer) {
        if (!enabled()) {
            return
        }

        val mapView = mapViewProvider()
        val point = gesture.locationInView(mapView)
        val coordinate = mapView.convertPoint(point, toCoordinateFromView = mapView)
        val rawTap =
            coordinate.useContents {
                LatLon(latitude, longitude).normalized()
            }
        val clampedTap = viewportBounds()?.clamp(rawTap) ?: rawTap
        onProvisionalGuess(clampedTap)
    }
}

private class IosAnnotationStore {
    var annotations: List<MKPointAnnotation> = emptyList()
}

private fun zoomToRegionMeters(zoomLevel: Double): Double {
    val normalizedZoom = zoomLevel.coerceIn(MIN_MAP_ZOOM_LEVEL, MAX_MAP_ZOOM_LEVEL)
    return (40_075_000.0 / 2.0.pow(normalizedZoom)).coerceIn(75.0, 40_000_000.0)
}

private fun longitudeDeltaToZoom(longitudeDelta: Double): Double {
    val safeDelta = longitudeDelta.coerceIn(0.0001, 360.0)
    val zoom = ln(360.0 / safeDelta) / ln(2.0)
    return zoom.coerceIn(MIN_MAP_ZOOM_LEVEL, MAX_MAP_ZOOM_LEVEL)
}
