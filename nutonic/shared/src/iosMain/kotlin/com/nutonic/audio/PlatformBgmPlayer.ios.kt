@file:OptIn(
    kotlinx.cinterop.ExperimentalForeignApi::class,
    org.jetbrains.compose.resources.ExperimentalResourceApi::class,
)

package com.nutonic.audio

import com.nutonic.resources.Res
import kotlinx.cinterop.ObjCObjectVar
import kotlinx.cinterop.alloc
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.coroutines.delay
import platform.AVFAudio.AVAudioPlayer
import platform.Foundation.NSError
import platform.Foundation.NSURL

actual class PlatformBgmPlayer actual constructor() {
    private var player: AVAudioPlayer? = null

    actual suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
        crossfadeMs: Int,
    ) {
        val old = player
        player = null
        if (old != null) {
            if (crossfadeMs > 0) {
                fadeOutPlayer(old, (crossfadeMs / 2).coerceAtLeast(1))
            } else {
                old.stop()
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
        val path = writeBgmWavToTemp(bytes, track.trackId) ?: return
        val url = NSURL.fileURLWithPath(path)
        val p =
            memScoped {
                val err = alloc<ObjCObjectVar<NSError?>>()
                AVAudioPlayer(contentsOfURL = url, error = err.ptr)
            }
        p.numberOfLoops = -1
        p.prepareToPlay()
        if (crossfadeMs > 0) {
            p.volume = 0f
            p.play()
            fadeInPlayer(p, (crossfadeMs / 2).coerceAtLeast(1))
        } else {
            p.volume = 1f
            p.play()
        }
        player = p
    }

    private suspend fun fadeOutPlayer(
        p: AVAudioPlayer,
        durationMs: Int,
    ) {
        val steps = (durationMs / 50).coerceAtLeast(2)
        try {
            repeat(steps) { i ->
                p.volume = 1f - (i + 1f) / steps
                delay(50)
            }
        } catch (_: Throwable) {
        }
        p.stop()
    }

    private suspend fun fadeInPlayer(
        p: AVAudioPlayer,
        durationMs: Int,
    ) {
        val steps = (durationMs / 50).coerceAtLeast(2)
        try {
            repeat(steps) { i ->
                p.volume = (i + 1f) / steps
                delay(50)
            }
        } catch (_: Throwable) {
        }
    }
}
