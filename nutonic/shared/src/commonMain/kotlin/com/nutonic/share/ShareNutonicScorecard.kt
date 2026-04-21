package com.nutonic.share

import com.nutonic.filter.PlatformContext

/**
 * Shares a short plain-text scorecard. Suspends until the platform handoff completes where
 * the underlying API is async (Web `navigator.share` / clipboard); on Android/iOS/desktop
 * this resolves after the synchronous sheet or clipboard call returns.
 */
expect suspend fun shareNutonicScorecard(
    context: PlatformContext,
    text: String,
): Boolean
