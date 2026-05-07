@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class)

package com.nutonic.vlm

import platform.Foundation.NSError

/**
 * Swift-implemented bridge for iOS on-device VLM.
 *
 * Implement this in the host `iosApp` using the Swift Leap SDK (`leap-ios`) and inject it via
 * `NutonicInitIosServices(vlmBridge: ...)` before creating the Compose view controller.
 *
 * Kotlin/Native exports this interface to ObjC/Swift as a protocol; Swift should implement the protocol.
 */
interface IosVlmBridge {
    /**
     * Execute one multi-image VLM call.
     *
     * - `prompt`: fully assembled user prompt (already includes server injection + user ask).
     * - `images`: ordered image bytes (PNG/JPEG); same order as roles.
     * - `roles`: semantic role labels for each image (e.g. `sentinel_rgb`, `sentinel_fc`, overlays...).
     * - `completion`: called exactly once; on success `text` is non-null and `error` is null.
     */
    fun run(
        prompt: String,
        images: List<ByteArray>,
        roles: List<String>,
        completion: (text: String?, error: NSError?) -> Unit,
    )
}

