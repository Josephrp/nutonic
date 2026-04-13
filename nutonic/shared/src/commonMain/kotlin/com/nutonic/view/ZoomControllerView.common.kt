package com.nutonic.view

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.nutonic.model.ScalableState

@Composable
expect fun ZoomControllerView(
    modifier: Modifier,
    scalableState: ScalableState,
)
