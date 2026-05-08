package com.nutonic.share

import com.nutonic.filter.PlatformContext
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine
import kotlinx.browser.document
import kotlinx.browser.window
import org.w3c.dom.HTMLTextAreaElement

private suspend fun awaitJsPromise(p: dynamic) {
    val isThenable = js("p != null && typeof p.then === 'function'") as Boolean
    if (!isThenable) {
        return
    }
    suspendCoroutine { cont ->
        p.then(
            { _: dynamic -> cont.resume(Unit) },
            { err: dynamic ->
                cont.resumeWithException(Throwable(err?.toString() ?: "share rejected"))
            },
        )
    }
}

@Suppress("UNUSED_PARAMETER")
actual suspend fun shareNutonicScorecard(
    context: PlatformContext,
    text: String,
): Boolean {
    val navigatorDynamic = window.navigator.asDynamic()

    try {
        val shareFn = navigatorDynamic.share
        if (shareFn != null) {
            val options = js("{}")
            options.asDynamic().text = text
            val result = shareFn.call(navigatorDynamic, options)
            awaitJsPromise(result)
            return true
        }
    } catch (_: Throwable) {
        // fall through to clipboard paths
    }

    try {
        val clipboard = navigatorDynamic.clipboard
        if (clipboard != null && clipboard.writeText != null) {
            val writePromise = clipboard.writeText(text)
            awaitJsPromise(writePromise)
            return true
        }
    } catch (_: Throwable) {
        // fall through to legacy execCommand
    }

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
