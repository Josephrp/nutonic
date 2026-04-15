@file:OptIn(org.jetbrains.compose.resources.ExperimentalResourceApi::class)

package com.nutonic.audio

import com.nutonic.resources.Res
import java.io.ByteArrayInputStream
import javax.sound.sampled.AudioSystem
import javax.sound.sampled.Clip

actual class PlatformBgmPlayer actual constructor() {
    private var clip: Clip? = null

    actual suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
    ) {
        stopInternal()
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
            c.start()
            clip = c
        } catch (_: Throwable) {
            // Headless CI / no mixer: skip playback; assets still validate at build time.
        }
    }

    private fun stopInternal() {
        try {
            clip?.stop()
        } catch (_: Throwable) {
        }
        clip?.close()
        clip = null
    }
}
