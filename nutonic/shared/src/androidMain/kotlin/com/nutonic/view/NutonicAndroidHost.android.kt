package com.nutonic.view

import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.LocalContext
import com.nutonic.AndroidNutonicAppContext
import com.nutonic.Dependencies
import com.nutonic.Notification
import com.nutonic.NutonicAppWithDependencies
import com.nutonic.NutonicGalleryExternalEvent
import com.nutonic.PopupNotification
import com.nutonic.SharePicture
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.defaultNutonicServerOrigin
import com.nutonic.filter.PlatformContext
import com.nutonic.ioDispatcher
import com.nutonic.model.PictureData
import com.nutonic.storage.AndroidImageStorage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun NutonicAndroidHost(
    externalEvents: Flow<NutonicGalleryExternalEvent>,
    nutonicServerOrigin: String = defaultNutonicServerOrigin(),
) {
    val context: Context = LocalContext.current
    SideEffect {
        AndroidNutonicAppContext.bind(context)
    }
    val ioScope = rememberCoroutineScope { ioDispatcher }
    val dependencies =
        remember(context, ioScope, nutonicServerOrigin) {
            androidNutonicDependencies(context, ioScope, externalEvents, nutonicServerOrigin)
        }
    NutonicAppWithDependencies(dependencies)
}

private fun androidNutonicDependencies(
    context: Context,
    ioScope: CoroutineScope,
    externalEvents: Flow<NutonicGalleryExternalEvent>,
    nutonicServerOrigin: String,
) = object : Dependencies() {
    override val nutonicApiClient: NutonicApiClient = NutonicApiClient(nutonicServerOrigin)
    override val notification: Notification =
        object : PopupNotification(localization) {
            override fun showPopUpMessage(text: String) {
                Toast.makeText(context, text, Toast.LENGTH_SHORT).show()
            }
        }
    override val imageStorage: AndroidImageStorage = AndroidImageStorage(pictures, ioScope, context)
    override val sharePicture: SharePicture =
        object : SharePicture {
            override fun share(
                context: PlatformContext,
                picture: PictureData,
            ) {
                ioScope.launch {
                    val shareIntent: Intent =
                        Intent().apply {
                            action = Intent.ACTION_SEND
                            putExtra(
                                Intent.EXTRA_STREAM,
                                imageStorage.getUri(context.androidContext, picture),
                            )
                            putExtra(
                                Intent.EXTRA_TEXT,
                                picture.description,
                            )
                            type = "image/jpeg"
                            flags = Intent.FLAG_GRANT_READ_URI_PERMISSION
                        }
                    withContext(Dispatchers.Main) {
                        context.androidContext.startActivity(Intent.createChooser(shareIntent, null))
                    }
                }
            }
        }
    override val externalEvents: Flow<NutonicGalleryExternalEvent> = externalEvents
}
