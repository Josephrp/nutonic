package com.nutonic.map

import kotlin.test.Test
import kotlin.test.assertEquals

class MapViewportContractTest {
    @Test
    fun boundsClamp_limitsLatitudeLongitude() {
        val bounds =
            ViewportBounds(
                minLatitude = 10.0,
                maxLatitude = 20.0,
                minLongitude = -5.0,
                maxLongitude = 5.0,
            )

        val clamped = bounds.clamp(LatLon(latitude = 50.0, longitude = -40.0))

        assertEquals(20.0, clamped.latitude)
        assertEquals(-5.0, clamped.longitude)
    }

    @Test
    fun cameraNormalized_clampsZoomAndBounds() {
        val bounds =
            ViewportBounds(
                minLatitude = -10.0,
                maxLatitude = 10.0,
                minLongitude = -20.0,
                maxLongitude = 20.0,
            )

        val camera =
            MapCameraState(
                center = LatLon(latitude = 70.0, longitude = 50.0),
                zoomLevel = 100.0,
            )

        val normalized = camera.normalized(bounds)

        assertEquals(10.0, normalized.center.latitude)
        assertEquals(20.0, normalized.center.longitude)
        assertEquals(MAX_MAP_ZOOM_LEVEL, normalized.zoomLevel)
    }

    @Test
    fun latLonNormalized_wrapsLongitude() {
        val normalized = LatLon(latitude = 3.0, longitude = 195.0).normalized()

        assertEquals(3.0, normalized.latitude)
        assertEquals(-165.0, normalized.longitude)
    }
}
