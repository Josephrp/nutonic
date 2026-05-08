@file:OptIn(org.jetbrains.compose.resources.ExperimentalResourceApi::class)

package com.nutonic.audio

import com.nutonic.resources.Res
import java.io.ByteArrayInputStream
import javax.sound.sampled.AudioSystem
import javax.sound.sampled.Clip
import javax.sound.sampled.FloatControl
import kotlinx.coroutines.delay

actual class PlatformBgmPlayer actual constructor() {
    private var clip: Clip? = null

    actual suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
        crossfadeMs: Int,
    ) {
        val previous = clip
        clip = null
        if (previous != null) {
            if (crossfadeMs > 0) {
                fadeOutClip(previous, (crossfadeMs / 2).coerceAtLeast(1))
            } else {
                stopClip(previous)
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
        try {
            val stream = AudioSystem.getAudioInputStream(ByteArrayInputStream(bytes))
            val c = AudioSystem.getClip()
            c.open(stream)
            c.loop(Clip.LOOP_CONTINUOUSLY)
            if (crossfadeMs > 0) {
                runCatching {
                    val control = c.getControl(FloatControl.Type.MASTER_GAIN) as FloatControl
                    control.value = control.minimum
                }
                c.start()
                fadeInClip(c, (crossfadeMs / 2).coerceAtLeast(1))
            } else {
                c.start()
            }
            clip = c
        } catch (_: Throwable) {
            // Headless CI / no mixer: skip playback; assets still validate at build time.
        }
    }

    private suspend fun fadeOutClip(
        c: Clip,
        durationMs: Int,
    ) {
        try {
            val control = runCatching { c.getControl(FloatControl.Type.MASTER_GAIN) as FloatControl }.getOrNull()
            if (control == null) {
                delay(durationMs.toLong().coerceAtMost(400L))
                stopClip(c)
                return
            }
            val min = control.minimum
            val max = control.maximum
            val start = control.value.coerceIn(min, max)
            val steps = (durationMs / 40).coerceAtLeast(2)
            repeat(steps) { i ->
                val t = (i + 1).toFloat() / steps
                control.value = start + (min - start) * t
                delay(40)
            }
        } catch (_: Throwable) {
        }
        stopClip(c)
    }

    private suspend fun fadeInClip(
        c: Clip,
        durationMs: Int,
    ) {
        try {
            val control = runCatching { c.getControl(FloatControl.Type.MASTER_GAIN) as FloatControl }.getOrNull()
            if (control == null) {
                delay(durationMs.toLong().coerceAtMost(400L))
                return
            }
            val min = control.minimum
            val max = control.maximum
            val steps = (durationMs / 40).coerceAtLeast(2)
            repeat(steps) { i ->
                val t = (i + 1).toFloat() / steps
                control.value = min + (max - min) * t
                delay(40)
            }
        } catch (_: Throwable) {
        }
    }

    private fun stopClip(c: Clip) {
        try {
            c.stop()
        } catch (_: Throwable) {
        }
        c.close()
    }
}
