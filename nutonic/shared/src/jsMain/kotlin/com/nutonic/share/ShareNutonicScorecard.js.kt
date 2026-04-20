package com.nutonic.share

import com.nutonic.filter.PlatformContext
import kotlinx.browser.document
import kotlinx.browser.window
import org.w3c.dom.HTMLTextAreaElement

@Suppress("UNUSED_PARAMETER")
/**
 * Returns `true` when the browser accepted a share/clipboard handoff request.
 * This is intentionally best-effort: native `navigator.share` and clipboard APIs are async,
 * so `true` means "handoff started" rather than "user completed share".
 */
actual fun shareNutonicScorecard(
    context: PlatformContext,
    text: String,
): Boolean {
    val navigatorDynamic = window.navigator.asDynamic()

    // Best-effort native share sheet (async promise; fire-and-forget for non-suspending API).
    try {
        val shareFn = navigatorDynamic.share
        if (shareFn != null) {
            shareFn.call(navigatorDynamic, js("{ text: text }"))
            return true
        }
    } catch (_: Throwable) {
        // fall through to clipboard paths
    }

    // Clipboard API path (also async; still a useful signal for caller/UI).
    try {
        val clipboard = navigatorDynamic.clipboard
        if (clipboard != null && clipboard.writeText != null) {
            clipboard.writeText(text)
            return true
        }
    } catch (_: Throwable) {
        // fall through to legacy execCommand
    }

    // Legacy synchronous fallback.
    val body = document.body ?: return false
    return try {
        val textarea = document.createElement("textarea") as HTMLTextAreaElement
        textarea.value = text
        textarea.style.position = "fixed"
        textarea.style.left = "-10000px"
        body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        val copied = document.execCommand("copy")
        body.removeChild(textarea)
        copied
    } catch (_: Throwable) {
        false
    }
}
