import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import com.nutonic.Dependencies
import com.nutonic.NutonicAppWithDependencies
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.defaultNutonicServerOrigin

@Composable
internal fun NutonicWebHost() {
    val dependencies =
        remember {
            object : Dependencies() {
                override val nutonicApiClient: NutonicApiClient = NutonicApiClient(defaultNutonicServerOrigin())
            }
        }

    Surface(
        modifier = Modifier.fillMaxSize(),
    ) {
        NutonicAppWithDependencies(
            dependencies = dependencies,
        )
    }
}
