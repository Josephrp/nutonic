@file:OptIn(org.jetbrains.compose.resources.ExperimentalResourceApi::class)

package com.nutonic.audio

import android.media.MediaPlayer
import com.nutonic.AndroidNutonicAppContext
import com.nutonic.resources.Res
import java.io.File
import kotlinx.coroutines.delay

actual class PlatformBgmPlayer actual constructor() {
    private var mediaPlayer: MediaPlayer? = null
    private var tempFile: File? = null

    actual suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
        crossfadeMs: Int,
    ) {
        val oldPlayer = mediaPlayer
        val oldFile = tempFile
        mediaPlayer = null
        tempFile = null
        if (oldPlayer != null) {
            if (crossfadeMs > 0) {
                fadeOutMediaPlayer(oldPlayer, (crossfadeMs / 2).coerceAtLeast(1))
            } else {
                try {
                    oldPlayer.stop()
                } catch (_: Throwable) {
                }
                oldPlayer.release()
            }
            oldFile?.delete()
        }
        if (!masterEnabled) {
            return
        }
        val ctx = AndroidNutonicAppContext.application ?: return
        val bytes =
            try {
                Res.readBytes(track.composeResourcePath())
            } catch (_: Throwable) {
                return
            }
        val f =
            File.createTempFile("nutonic-bgm-", ".wav", ctx.cacheDir).apply {
                deleteOnExit()
                writeBytes(bytes)
            }
        tempFile = f
        try {
            val mp =
                MediaPlayer().apply {
                    setDataSource(f.absolutePath)
                    isLooping = true
                    setVolume(0f, 0f)
                    prepare()
                    start()
                }
            mediaPlayer = mp
            if (crossfadeMs > 0) {
                fadeInMediaPlayer(mp, (crossfadeMs / 2).coerceAtLeast(1))
            } else {
                mp.setVolume(1f, 1f)
            }
        } catch (_: Throwable) {
            try {
                mediaPlayer?.stop()
            } catch (_: Throwable) {
            }
            mediaPlayer?.release()
            mediaPlayer = null
            tempFile?.delete()
            tempFile = null
        }
    }

    private suspend fun fadeOutMediaPlayer(
        mp: MediaPlayer,
        durationMs: Int,
    ) {
        val steps = (durationMs / 50).coerceAtLeast(2)
        try {
            repeat(steps) { i ->
                val v = 1f - (i + 1f) / steps
                mp.setVolume(v.coerceIn(0f, 1f), v.coerceIn(0f, 1f))
                delay(50)
            }
        } catch (_: Throwable) {
        }
        try {
            mp.stop()
        } catch (_: Throwable) {
        }
        mp.release()
    }

    private suspend fun fadeInMediaPlayer(
        mp: MediaPlayer,
        durationMs: Int,
    ) {
        val steps = (durationMs / 50).coerceAtLeast(2)
        try {
            repeat(steps) { i ->
                val v = (i + 1f) / steps
                mp.setVolume(v.coerceIn(0f, 1f), v.coerceIn(0f, 1f))
                delay(50)
            }
        } catch (_: Throwable) {
        }
    }

}
