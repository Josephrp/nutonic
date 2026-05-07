package com.nutonic

import androidx.compose.ui.window.ComposeUIViewController
import com.nutonic.platform.IosServiceRegistry
import com.nutonic.vlm.IosVlmBridge
import platform.UIKit.UIViewController

@Suppress("FunctionName", "unused")
fun MainViewController(): UIViewController =
    ComposeUIViewController {
        NutonicIosHost()
    }

/**
 * iOS host app must call this before creating [MainViewController] so platform services (for example VLM) are available.
 *
 * This avoids linking Kotlin/Native against upstream SDKs that are currently version-skewed vs Swift equivalents.
 */
@Suppress("unused")
fun nutonicInitIosServices(
    vlmBridge: IosVlmBridge?,
) {
    IosServiceRegistry.vlmBridge = vlmBridge
}
