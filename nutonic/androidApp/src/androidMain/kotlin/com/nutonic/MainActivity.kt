package com.nutonic

import android.os.Bundle
import androidx.activity.addCallback
import androidx.activity.compose.setContent
import androidx.appcompat.app.AppCompatActivity
import com.nutonic.view.NutonicAndroidHost
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow

class MainActivity : AppCompatActivity() {
    val externalEvents =
        MutableSharedFlow<NutonicGalleryExternalEvent>(
            replay = 0,
            extraBufferCapacity = 1,
            onBufferOverflow = BufferOverflow.DROP_OLDEST,
        )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            NutonicAndroidHost(
                externalEvents = externalEvents,
                nutonicServerOrigin = BuildConfig.NUTONIC_SERVER_ORIGIN,
            )
        }
        onBackPressedDispatcher.addCallback {
            externalEvents.tryEmit(NutonicGalleryExternalEvent.ReturnBack)
        }
    }
}
