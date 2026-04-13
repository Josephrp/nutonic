package com.nutonic

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.Modifier
import com.nutonic.api.ApiResult
import com.nutonic.api.FeatureFlags
import com.nutonic.api.NutonicApiClient
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.cache.createManifestBlobStore
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRepository
import com.nutonic.persistence.createLocalLeaderboardBlobStore
import com.nutonic.model.PictureData
import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.decodeNutonicRoute
import com.nutonic.navigation.encode
import com.nutonic.screens.AuthenticationScreenPlaceholder
import com.nutonic.screens.NutonicMusicMasterTopBar
import com.nutonic.screens.RoleSelectionScreenPlaceholder
import com.nutonic.screens.SplashScreenPlaceholder
import com.nutonic.settings.MemorySettingsRepository
import com.nutonic.style.NutonicTheme

@Composable
fun NutonicApp(
    pictures: SnapshotStateList<PictureData>,
    nutonicApiClient: NutonicApiClient? = null,
) {
    var routeToken by rememberSaveable { mutableStateOf(NutonicRoute.Splash.encode()) }
    val settingsRepo = remember { MemorySettingsRepository() }
    val settings = settingsRepo.settings
    var serverFeatureFlags by remember { mutableStateOf<FeatureFlags?>(null) }
    val manifestBlobStore = remember { createManifestBlobStore() }
    val contentCacheRepository =
        remember(nutonicApiClient, manifestBlobStore) {
            nutonicApiClient?.let { ContentCacheRepository(it, manifestBlobStore) }
        }
    val localNonRankedLeaderboardRepository =
        remember {
            LocalNonRankedLeaderboardRepository(createLocalLeaderboardBlobStore())
        }

    LaunchedEffect(nutonicApiClient) {
        serverFeatureFlags = null
        val client = nutonicApiClient ?: return@LaunchedEffect
        serverFeatureFlags =
            when (val r = client.getConfig()) {
                is ApiResult.Ok -> r.value.features
                else -> null
            }
    }

    NutonicTheme(
        reducedMotion = settings.reducedMotion,
        highContrast = settings.highContrast,
    ) {
        val route = decodeNutonicRoute(routeToken)
        val navigate: (NutonicRoute) -> Unit = { routeToken = it.encode() }

        Column(Modifier.fillMaxSize()) {
            NutonicMusicMasterTopBar(
                musicMasterEnabled = settings.musicMasterEnabled,
                onMusicMasterChange = { v -> settingsRepo.update { it.copy(musicMasterEnabled = v) } },
            )
            Box(
                modifier =
                    Modifier
                        .weight(1f)
                        .fillMaxWidth(),
            ) {
                when (route) {
                    NutonicRoute.Splash -> {
                        SplashScreenPlaceholder(onInitialize = { navigate(NutonicRoute.RoleSelection) })
                    }

                    NutonicRoute.RoleSelection -> {
                        RoleSelectionScreenPlaceholder(
                            selectedRole = settings.playerRole,
                            onSelectRole = { id -> settingsRepo.update { it.copy(playerRole = id) } },
                            onContinue = { navigate(NutonicRoute.Shell(MainTab.ScanHub)) },
                            onOpenOptionalAuth = { navigate(NutonicRoute.Authentication) },
                        )
                    }

                    NutonicRoute.Authentication -> {
                        AuthenticationScreenPlaceholder(
                            onSkip = { navigate(NutonicRoute.Shell(MainTab.ScanHub)) },
                        )
                    }

                    is NutonicRoute.Shell -> {
                        NutonicMainShell(
                            pictures = pictures,
                            shell = route,
                            onChangeShell = { navigate(it) },
                            settingsRepository = settingsRepo,
                            nutonicApiClient = nutonicApiClient,
                            serverFeatureFlags = serverFeatureFlags,
                            contentCacheRepository = contentCacheRepository,
                            localNonRankedLeaderboardRepository = localNonRankedLeaderboardRepository,
                        )
                    }
                }
            }
        }
    }
}
