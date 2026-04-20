package com.nutonic.view

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.ApplicationScope
import androidx.compose.ui.window.Window
import androidx.compose.ui.window.WindowPosition
import androidx.compose.ui.window.WindowState
import com.nutonic.Dependencies
import com.nutonic.NutonicAppWithDependencies
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.defaultNutonicServerOrigin
import com.nutonic.resources.Res
import com.nutonic.resources.ic_nutonic_round
import org.jetbrains.compose.resources.painterResource
import java.awt.Dimension
import java.awt.Toolkit

@Composable
fun ApplicationScope.NutonicDesktopHost() {
    val dependencies =
        remember {
            object : Dependencies() {
                override val nutonicApiClient: NutonicApiClient = NutonicApiClient(defaultNutonicServerOrigin())
            }
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
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
        ) {
            NutonicAppWithDependencies(
                dependencies = dependencies,
            )
        }
    }
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
