package com.nutonic.platform

import com.nutonic.vlm.IosVlmBridge

/**
 * iOS-only registry for host-provided services (Swift side).
 *
 * NOTE: This is intentionally mutable + process-wide because the iOS app builds a single `shared.framework`
 * and instantiates the Compose UI via `MainViewController()` without dependency injection parameters.
 */
internal object IosServiceRegistry {
    var vlmBridge: IosVlmBridge? = null
}

