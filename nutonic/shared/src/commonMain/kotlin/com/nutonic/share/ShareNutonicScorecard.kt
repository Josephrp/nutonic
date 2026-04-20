package com.nutonic.share

import com.nutonic.filter.PlatformContext

/**
 * Shares a short plain-text scorecard (IMP-084). Returns whether the platform handled it
 * (chooser shown, clipboard set, or iOS sheet presented).
 */
expect fun shareNutonicScorecard(
    context: PlatformContext,
    text: String,
): Boolean
