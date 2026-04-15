@file:OptIn(org.jetbrains.compose.resources.ExperimentalResourceApi::class)

package com.nutonic.audio

import android.media.MediaPlayer
import com.nutonic.AndroidNutonicAppContext
import com.nutonic.resources.Res
import java.io.File

actual class PlatformBgmPlayer actual constructor() {
    private var mediaPlayer: MediaPlayer? = null
    private var tempFile: File? = null

    actual suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
    ) {
        releaseInternal()
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
            mediaPlayer =
                MediaPlayer().apply {
                    setDataSource(f.absolutePath)
                    isLooping = true
                    prepare()
                    start()
                }
        } catch (_: Throwable) {
            releaseInternal()
        }
    }

    private fun releaseInternal() {
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
