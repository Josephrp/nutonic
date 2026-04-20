package com.nutonic.share

import android.content.Intent
import com.nutonic.filter.PlatformContext

actual fun shareNutonicScorecard(
    context: PlatformContext,
    text: String,
): Boolean {
    val intent =
        Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
        }
    val chooser = Intent.createChooser(intent, null).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
    context.androidContext.startActivity(chooser)
    return true
}
