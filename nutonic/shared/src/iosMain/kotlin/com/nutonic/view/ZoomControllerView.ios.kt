package com.nutonic.view

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.nutonic.model.ScalableState

@Composable
actual fun ZoomControllerView(
    modifier: Modifier,
    scalableState: ScalableState,
) {
    // No need for additional ZoomControllerView for iOS
}
