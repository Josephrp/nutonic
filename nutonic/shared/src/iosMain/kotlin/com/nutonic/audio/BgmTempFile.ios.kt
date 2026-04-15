@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class)

package com.nutonic.audio

import kotlinx.cinterop.addressOf
import kotlinx.cinterop.usePinned
import platform.Foundation.NSTemporaryDirectory
import platform.posix.fclose
import platform.posix.fopen
import platform.posix.fwrite

internal fun writeBgmWavToTemp(bytes: ByteArray, suffix: String): String? {
    val dir = NSTemporaryDirectory()
    val path =
        if (dir.endsWith("/")) {
            "${dir}nutonic-bgm-$suffix.wav"
        } else {
            "$dir/nutonic-bgm-$suffix.wav"
        }
    val f = fopen(path, "wb") ?: return null
    try {
        val written =
            bytes.usePinned { pinned ->
                fwrite(pinned.addressOf(0), 1uL, bytes.size.toULong(), f)
            }
        if (written != bytes.size.toULong()) {
            return null
        }
    } finally {
        fclose(f)
    }
    return path
}
