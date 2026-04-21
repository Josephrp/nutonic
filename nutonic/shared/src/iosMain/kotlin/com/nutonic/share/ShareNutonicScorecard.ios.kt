package com.nutonic.share

import com.nutonic.filter.PlatformContext
import platform.UIKit.UIActivityViewController
import platform.UIKit.UIApplication
import platform.UIKit.UIWindow

actual suspend fun shareNutonicScorecard(
    context: PlatformContext,
    text: String,
): Boolean {
    val window =
        UIApplication.sharedApplication.keyWindow
            ?: UIApplication.sharedApplication.windows.lastOrNull() as? UIWindow
            ?: return false
    val root = window.rootViewController ?: return false
    val activity =
        UIActivityViewController(
            activityItems = listOf(text),
            applicationActivities = null,
        )
    root.presentViewController(
        viewControllerToPresent = activity,
        animated = true,
        completion = null,
    )
    return true
}
