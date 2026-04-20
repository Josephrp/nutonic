package com.nutonic.view

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import com.nutonic.AndroidNutonicAppContext
import com.nutonic.Dependencies
import com.nutonic.NutonicAppWithDependencies
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.defaultNutonicServerOrigin

@Composable
fun NutonicAndroidHost(
    nutonicServerOrigin: String = defaultNutonicServerOrigin(),
) {
    val context: Context = LocalContext.current
    SideEffect {
        AndroidNutonicAppContext.bind(context)
    }
    val dependencies =
        remember(context, nutonicServerOrigin) {
            object : Dependencies() {
                override val nutonicApiClient: NutonicApiClient = NutonicApiClient(nutonicServerOrigin)
            }
        }
    NutonicAppWithDependencies(dependencies)
}
