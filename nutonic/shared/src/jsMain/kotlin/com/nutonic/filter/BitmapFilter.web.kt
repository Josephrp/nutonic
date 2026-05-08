package com.nutonic.filter

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.*
import com.nutonic.utils.applyBlurFilter
import com.nutonic.utils.applyGrayScaleFilter
import com.nutonic.utils.applyPixelFilter

actual fun grayScaleFilter(
    bitmap: ImageBitmap,
    context: PlatformContext,
): ImageBitmap = applyGrayScaleFilter(bitmap.asSkiaBitmap()).asComposeImageBitmap()

actual fun pixelFilter(
    bitmap: ImageBitmap,
    context: PlatformContext,
): ImageBitmap = applyPixelFilter(bitmap.asSkiaBitmap()).asComposeImageBitmap()

actual fun blurFilter(
    bitmap: ImageBitmap,
    context: PlatformContext,
): ImageBitmap = applyBlurFilter(bitmap.asSkiaBitmap()).asComposeImageBitmap()

actual class PlatformContext

@Composable
actual fun getPlatformContext(): PlatformContext = PlatformContext()
