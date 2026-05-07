package com.nutonic.vlm

import com.nutonic.platform.IosServiceRegistry
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import platform.Foundation.NSError

/**
 * iOS `ProOnDeviceVlmEngine` backed by a Swift host bridge (typically `leap-ios`).
 *
 * This prevents Kotlin/Native dependency skew vs the Swift Leap SDK and avoids manifest parsing differences.
 */
internal class IosSwiftBridgeProOnDeviceVlmEngine : ProOnDeviceVlmEngine {
    override suspend fun prepareModel(
        cacheRecord: ProVlmCacheRecord,
        bundleBytes: ByteArray?,
    ) {
        // Swift bridge manages its own caching/loading. `bundleBytes` is not used on iOS in this path.
        if (bundleBytes != null) {
            require(bundleBytes.isNotEmpty()) { "Model bundle is empty" }
        }
    }

    override suspend fun run(input: ProVlmPreparedInput): ProOnDeviceVlmRunResult {
        val bridge =
            IosServiceRegistry.vlmBridge
                ?: return ProOnDeviceVlmRunResult.Unsupported(
                    "iOS VLM is not initialized (call nutonicInitIosServices before MainViewController).",
                )

        val images: List<ByteArray> = input.images.map { it.bytes }
        val roles: List<String> = input.images.map { it.role.ifBlank { "image" } }

        return try {
            val text =
                suspendCancellableCoroutine { cont ->
                    bridge.run(
                        prompt = input.prompt,
                        images = images,
                        roles = roles,
                    ) { outText: String?, error: NSError? ->
                        if (!cont.isActive) return@run
                        when {
                            error != null -> cont.resumeWithException(RuntimeException(error.localizedDescription))
                            outText == null -> cont.resumeWithException(RuntimeException("iOS VLM bridge returned null text"))
                            else -> cont.resume(outText)
                        }
                    }
                }
            ProOnDeviceVlmRunResult.Ok(text)
        } catch (e: Exception) {
            ProOnDeviceVlmRunResult.Failed(e.message ?: "iOS VLM bridge failed")
        }
    }
}
