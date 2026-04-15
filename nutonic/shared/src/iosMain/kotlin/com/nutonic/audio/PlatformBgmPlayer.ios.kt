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
import platform.AVFAudio.AVAudioPlayer
import platform.Foundation.NSError
import platform.Foundation.NSURL

actual class PlatformBgmPlayer actual constructor() {
    private var player: AVAudioPlayer? = null

    actual suspend fun applyDesiredTrack(
        track: NutonicBgmTrack,
        masterEnabled: Boolean,
    ) {
        player?.stop()
        player = null
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
        p.play()
        player = p
    }
}
