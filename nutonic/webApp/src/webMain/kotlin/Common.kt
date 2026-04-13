import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import com.nutonic.*
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.defaultNutonicServerOrigin
import com.nutonic.ioDispatcher
import com.nutonic.view.Toast
import com.nutonic.view.ToastState
import kotlinx.coroutines.CoroutineScope

@Composable
internal fun NutonicWebHost() {
    val toastState = remember { mutableStateOf<ToastState>(ToastState.Hidden) }
    val ioScope: CoroutineScope = rememberCoroutineScope { ioDispatcher }
    val dependencies = remember(ioScope) { getDependencies(toastState) }

    Surface(
        modifier = Modifier.fillMaxSize(),
    ) {
        NutonicAppWithDependencies(
            dependencies = dependencies,
        )
        Toast(toastState)
    }
}

fun getDependencies(toastState: MutableState<ToastState>) =
    object : Dependencies() {
        override val nutonicApiClient: NutonicApiClient = NutonicApiClient(defaultNutonicServerOrigin())
        override val imageStorage: ImageStorage = WebImageStorage()
        override val sharePicture = WebSharePicture()
        override val notification = WebPopupNotification(toastState, localization)
    }
