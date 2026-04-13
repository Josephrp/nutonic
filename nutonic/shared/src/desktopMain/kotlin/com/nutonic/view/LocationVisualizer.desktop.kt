package com.nutonic.view

import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.ui.Modifier
import com.nutonic.model.GpsPosition

@Composable
actual fun LocationVisualizer(
    modifier: Modifier,
    gps: GpsPosition,
    title: String,
    parentScrollEnableState: MutableState<Boolean>,
) {
    com.nutonic.map.MapView(
        modifier,
        userAgent = "ComposeMapViewExample",
        latitude = gps.latitude,
        longitude = gps.longitude,
        startScale = 12_000.0,
    )
}
