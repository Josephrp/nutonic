@file:OptIn(org.jetbrains.compose.resources.ExperimentalResourceApi::class)

package com.nutonic.audio

import com.nutonic.resources.Res
import kotlinx.coroutines.delay
import org.khronos.webgl.Uint8Array
import org.w3c.dom.Audio
import org.w3c.dom.url.URL
import org.w3c.files.Blob
import org.w3c.files.BlobPropertyBag

actual class PlatformBgmPlayer actual constructor() {
    private var audio: Audio? = null
    private var objectUrl: String? = null

    actual suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
        crossfadeMs: Int,
    ) {
        val old = audio
        val oldUrl = objectUrl
        audio = null
        objectUrl = null
        if (old != null) {
            if (crossfadeMs > 0) {
                fadeOutAudio(old, (crossfadeMs / 2).coerceAtLeast(1))
            } else {
                try {
                    old.pause()
                } catch (_: Throwable) {
                }
            }
            oldUrl?.let { u ->
                try {
                    URL.revokeObjectURL(u)
                } catch (_: Throwable) {
                }
            }
        }
        if (!masterEnabled) {
            return
        }
        val bytes =
            try {
                Res.readBytes(track.composeResourcePath())
            } catch (_: Throwable) {
                return
            }
        val u8 = Uint8Array(bytes.size)
        for (i in bytes.indices) {
            u8.asDynamic()[i] = bytes[i]
        }
        val blob = Blob(arrayOf(u8), BlobPropertyBag(type = "audio/wav"))
        val url = URL.createObjectURL(blob)
        objectUrl = url
        val a = Audio(url)
        a.loop = true
        if (crossfadeMs > 0) {
            a.volume = 0.0
            a.asDynamic().play()
            fadeInAudio(a, (crossfadeMs / 2).coerceAtLeast(1))
        } else {
            a.volume = 1.0
            a.asDynamic().play()
        }
        audio = a
    }

    private suspend fun fadeOutAudio(
        a: Audio,
        durationMs: Int,
    ) {
        val steps = (durationMs / 50).coerceAtLeast(2)
        try {
            repeat(steps) { i ->
                a.volume = 1.0 - (i + 1.0) / steps
                delay(50)
            }
        } catch (_: Throwable) {
        }
        try {
            a.pause()
        } catch (_: Throwable) {
        }
    }

    private suspend fun fadeInAudio(
        a: Audio,
        durationMs: Int,
    ) {
        val steps = (durationMs / 50).coerceAtLeast(2)
        try {
            repeat(steps) { i ->
                a.volume = (i + 1.0) / steps
                delay(50)
            }
        } catch (_: Throwable) {
        }
    }
}
