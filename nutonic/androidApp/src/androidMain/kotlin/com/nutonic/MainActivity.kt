package com.nutonic

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.appcompat.app.AppCompatActivity
import com.nutonic.view.NutonicAndroidHost

class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            NutonicAndroidHost(
                nutonicServerOrigin = BuildConfig.NUTONIC_SERVER_ORIGIN,
            )
        }
    }
}
