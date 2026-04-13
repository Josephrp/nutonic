package com.nutonic.view

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.nutonic.PlatformStorableImage
import com.nutonic.model.PictureData

@Composable
expect fun CameraView(
    modifier: Modifier,
    onCapture: (picture: PictureData.Camera, image: PlatformStorableImage) -> Unit,
)
