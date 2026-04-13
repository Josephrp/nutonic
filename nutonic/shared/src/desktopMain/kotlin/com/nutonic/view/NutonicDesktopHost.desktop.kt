package com.nutonic.view

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.type
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.ApplicationScope
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.WindowState
import com.nutonic.*
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.defaultNutonicServerOrigin
import com.nutonic.filter.PlatformContext
import com.nutonic.model.PictureData
import com.nutonic.resources.Res
import com.nutonic.resources.ic_nutonic_round
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import org.jetbrains.compose.resources.painterResource
import java.awt.Dimension
import java.awt.Toolkit

class GalleryNavigationEventBus {
    private val _events =
        MutableSharedFlow<NutonicGalleryExternalEvent>(
            replay = 0,
            onBufferOverflow = BufferOverflow.DROP_OLDEST,
            extraBufferCapacity = 1,
        )
    val events = _events.asSharedFlow()

    fun produceEvent(event: NutonicGalleryExternalEvent) {
        _events.tryEmit(event)
    }
}

@Composable
fun ApplicationScope.NutonicDesktopHost() {
    val ioScope = rememberCoroutineScope { ioDispatcher }
    val toastState = remember { mutableStateOf<ToastState>(ToastState.Hidden) }
    val galleryNavigationEventBus = remember { GalleryNavigationEventBus() }
    val dependencies =
        remember {
            desktopNutonicDependencies(toastState, ioScope, galleryNavigationEventBus.events)
        }

    Window(
        onCloseRequest = ::exitApplication,
        title = "NU:TONIC",
        state =
            WindowState(
                position = WindowPosition.Aligned(Alignment.Center),
                size = getPreferredWindowSize(720, 857),
            ),
        icon = painterResource(Res.drawable.ic_nutonic_round),
        // https://youtrack.jetbrains.com/issue/CMP-2741
        onKeyEvent = {
            if (it.type == KeyEventType.KeyUp) {
                when (it.key) {
                    Key.DirectionLeft ->
                        galleryNavigationEventBus.produceEvent(
                            NutonicGalleryExternalEvent.Previous,
                        )

                    Key.DirectionRight ->
                        galleryNavigationEventBus.produceEvent(
                            NutonicGalleryExternalEvent.Next,
                        )

                    Key.Escape ->
                        galleryNavigationEventBus.produceEvent(
                            NutonicGalleryExternalEvent.ReturnBack,
                        )
                }
            }
            false
        },
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
        ) {
            NutonicAppWithDependencies(
                dependencies = dependencies,
            )
            Toast(toastState)
        }
    }
}

private fun desktopNutonicDependencies(
    toastState: MutableState<ToastState>,
    ioScope: CoroutineScope,
    events: SharedFlow<NutonicGalleryExternalEvent>,
) = object : Dependencies() {
    override val nutonicApiClient: NutonicApiClient = NutonicApiClient(defaultNutonicServerOrigin())
    override val notification: Notification =
        object : PopupNotification(localization) {
            override fun showPopUpMessage(text: String) {
                toastState.value = ToastState.Shown(text)
            }
        }
    override val imageStorage: DesktopImageStorage = DesktopImageStorage(ioScope)
    override val sharePicture: SharePicture =
        object : SharePicture {
            override fun share(
                context: PlatformContext,
                picture: PictureData,
            ) {
                // On Desktop share feature not supported
            }
        }
    override val externalEvents = events
}

private fun getPreferredWindowSize(
    desiredWidth: Int,
    desiredHeight: Int,
): DpSize {
    val screenSize: Dimension = Toolkit.getDefaultToolkit().screenSize
    val preferredWidth: Int = (screenSize.width * 0.8f).toInt()
    val preferredHeight: Int = (screenSize.height * 0.8f).toInt()
    val width: Int = if (desiredWidth < preferredWidth) desiredWidth else preferredWidth
    val height: Int = if (desiredHeight < preferredHeight) desiredHeight else preferredHeight
    return DpSize(width.dp, height.dp)
}
