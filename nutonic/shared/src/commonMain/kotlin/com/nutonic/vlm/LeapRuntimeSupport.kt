package com.nutonic.vlm

/**
 * True when the build embeds Liquid Leap for on-device VLM (Android, iOS arm64,
 * iOS simulator arm64, JVM desktop). Web/JS is false until a wasm runtime is wired.
 */
internal expect fun supportsLiquidLeapOnDeviceVlm(): Boolean
