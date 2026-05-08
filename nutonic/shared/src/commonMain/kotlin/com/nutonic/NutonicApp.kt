package com.nutonic

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.nutonic.api.ApiResult
import com.nutonic.api.FeatureFlags
import com.nutonic.api.NutonicApiClient
import com.nutonic.audio.LocalNutonicBgmOverlay
import com.nutonic.audio.NutonicBgmTrack
import com.nutonic.audio.PlatformBgmPlayer
import com.nutonic.audio.resolveNutonicBgmTrack
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.cache.createManifestBlobStore
import com.nutonic.leaderboard.GuessRecordOutboxRepository
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRepository
import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.ShellDetail
import com.nutonic.navigation.decodeNutonicRoute
import com.nutonic.navigation.encode
import com.nutonic.persistence.createGuessSyncOutboxBlobStore
import com.nutonic.persistence.createLocalLeaderboardBlobStore
import com.nutonic.persistence.createPlayerProgressBlobStore
import com.nutonic.persistence.createSettingsBlobStore
import com.nutonic.screens.NutonicMusicMasterTopBar
import com.nutonic.screens.RoleSelectionScreen
import com.nutonic.screens.SplashScreen
import com.nutonic.progress.PlayerProgressRepository
import com.nutonic.settings.PersistedSettingsRepository
import com.nutonic.style.NutonicMotion
import com.nutonic.style.NutonicTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel

@Composable
fun NutonicApp(
    nutonicApiClient: NutonicApiClient? = null,
) {
    var routeToken by rememberSaveable { mutableStateOf(NutonicRoute.Splash.encode()) }
    val appScope = remember { CoroutineScope(SupervisorJob() + Dispatchers.Default) }
    DisposableEffect(Unit) {
        onDispose { appScope.cancel() }
    }
    val settingsRepo = remember(appScope) { PersistedSettingsRepository(createSettingsBlobStore(), appScope) }
    val playerProgressRepo = remember(appScope) { PlayerProgressRepository(createPlayerProgressBlobStore(), appScope) }
    val settings = settingsRepo.settings

    LaunchedEffect(Unit) {
        settingsRepo.hydrate()
        playerProgressRepo.hydrate()
    }

    LaunchedEffect(routeToken) {
        recordRouteVisits(playerProgressRepo, decodeNutonicRoute(routeToken))
    }
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
    val guessRecordOutboxRepository =
        remember {
            GuessRecordOutboxRepository(createGuessSyncOutboxBlobStore())
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

    LaunchedEffect(nutonicApiClient, routeToken) {
        val client = nutonicApiClient ?: return@LaunchedEffect
        guessRecordOutboxRepository.flushPending(client)
    }

    NutonicTheme(
        reducedMotion = settings.reducedMotion,
        highContrast = settings.highContrast,
    ) {
        val route = decodeNutonicRoute(routeToken)
        val navigate: (NutonicRoute) -> Unit = { routeToken = it.encode() }

        val bgmOverlayTrack = remember { mutableStateOf<NutonicBgmTrack?>(null) }
        val bgmPlayer = remember { PlatformBgmPlayer() }
        LaunchedEffect(routeToken) {
            bgmOverlayTrack.value = null
        }
        val routeBgm = resolveNutonicBgmTrack(route)
        val effectiveBgm = bgmOverlayTrack.value ?: routeBgm
        LaunchedEffect(effectiveBgm, settings.musicMasterEnabled) {
            bgmPlayer.applyDesiredTrack(
                effectiveBgm,
                settings.musicMasterEnabled,
                NutonicMotion.crossfadeMs,
            )
        }

        CompositionLocalProvider(LocalNutonicBgmOverlay provides bgmOverlayTrack) {
            Column(
                Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colors.background),
            ) {
                NutonicMusicMasterTopBar(
                    musicMasterEnabled = settings.musicMasterEnabled,
                    onMusicMasterChange = { v -> settingsRepo.update { it.copy(musicMasterEnabled = v) } },
                )
                Box(
                    modifier =
                        Modifier
                            .weight(1f)
                            .fillMaxWidth()
                            .background(MaterialTheme.colors.background),
                ) {
                    when (route) {
                        NutonicRoute.Splash -> {
                            SplashScreen(onInitialize = { navigate(NutonicRoute.RoleSelection) })
                        }

                        NutonicRoute.RoleSelection -> {
                            RoleSelectionScreen(
                                displayName = settings.displayName,
                                onDisplayNameChange = { v -> settingsRepo.update { it.copy(displayName = v.take(32)) } },
                                selectedRole = settings.playerRole,
                                onSelectRole = { id -> settingsRepo.update { it.copy(playerRole = id) } },
                                onContinue = {
                                    settingsRepo.update {
                                        val handle = it.displayName.trim().ifBlank { "Operative" }
                                        it.copy(displayName = handle.take(32))
                                    }
                                    navigate(NutonicRoute.Shell(MainTab.ScanHub))
                                },
                            )
                        }

                        is NutonicRoute.Shell -> {
                            NutonicMainShell(
                                shell = route,
                                onChangeShell = { navigate(it) },
                                settingsRepository = settingsRepo,
                                nutonicApiClient = nutonicApiClient,
                                serverFeatureFlags = serverFeatureFlags,
                                contentCacheRepository = contentCacheRepository,
                                localNonRankedLeaderboardRepository = localNonRankedLeaderboardRepository,
                                guessRecordOutboxRepository = guessRecordOutboxRepository,
                                playerProgressRepository = playerProgressRepo,
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun recordRouteVisits(
    progress: PlayerProgressRepository,
    route: NutonicRoute,
) {
    when (route) {
        NutonicRoute.Splash -> progress.recordScreenVisit("splash")
        NutonicRoute.RoleSelection -> progress.recordScreenVisit("role_selection")
        is NutonicRoute.Shell -> {
            progress.recordScreenVisit("shell_tab:${route.tab.id}")
            when (route.detail) {
                null -> Unit
                ShellDetail.WorldMapGameplay -> progress.recordScreenVisit("xp_world_map_gameplay")
                ShellDetail.FinalResults -> progress.recordScreenVisit("xp_final_results")
                ShellDetail.IntelDashboard -> progress.recordScreenVisit("xp_intel_dashboard")
                ShellDetail.RankGlobal -> progress.recordScreenVisit("xp_rank_global")
                ShellDetail.SetupProtocol -> progress.recordScreenVisit("xp_setup_protocol")
                ShellDetail.ProCoordinateDashboard -> progress.recordScreenVisit("xp_pro_dashboard")
                ShellDetail.ProFireWatch -> progress.recordScreenVisit("xp_pro_firewatch")
                ShellDetail.ProOceanScout -> progress.recordScreenVisit("xp_pro_oceanscout")
                ShellDetail.ProLandShift -> progress.recordScreenVisit("xp_pro_landshift")
                ShellDetail.ProFloodPulse -> progress.recordScreenVisit("xp_pro_floodpulse")
                ShellDetail.ProBriefComposer -> progress.recordScreenVisit("xp_pro_brief_composer")
            }
        }
    }
}
