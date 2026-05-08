package com.nutonic.share

import com.nutonic.filter.PlatformContext
import java.awt.Toolkit
import java.awt.datatransfer.StringSelection

@Suppress("UNUSED_PARAMETER")
actual suspend fun shareNutonicScorecard(
    context: PlatformContext,
    text: String,
): Boolean =
    try {
        Toolkit.getDefaultToolkit().systemClipboard.setContents(StringSelection(text), null)
        true
    } catch (_: Throwable) {
        false
    }
