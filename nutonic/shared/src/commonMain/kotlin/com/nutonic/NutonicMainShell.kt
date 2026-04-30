package com.nutonic

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.LinearProgressIndicator
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Slider
import androidx.compose.material.Switch
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.nutonic.api.ApiResult
import com.nutonic.api.FeatureFlags
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.ProJobStatusOut
import com.nutonic.api.ProReadinessOut
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.cache.ProOverlayGuessRepository
import com.nutonic.leaderboard.GuessRecordOutboxRepository
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRepository
import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.ShellDetail
import com.nutonic.screens.CommunityLeaderboardPanel
import com.nutonic.screens.GameRolePicker
import com.nutonic.screens.ProCoordinateDashboardDetail
import com.nutonic.screens.RankedPlaySession
import com.nutonic.screens.ShellDetailScreen
import com.nutonic.screens.WorldMapGameplayDetail
import com.nutonic.screens.pro.ProBriefComposerScreen
import com.nutonic.screens.pro.ProFireWatchScreen
import com.nutonic.screens.pro.ProFloodPulseScreen
import com.nutonic.screens.pro.ProLandShiftScreen
import com.nutonic.screens.pro.ProOceanScoutScreen
import com.nutonic.settings.SettingsRepository
import com.nutonic.shell.ScanHubScreen
import com.nutonic.style.NutonicColors
import com.nutonic.style.nutonicOnSurfaceMuted
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard
import com.nutonic.style.NutonicPrimaryButton
import kotlinx.coroutines.launch

@Composable
fun NutonicMainShell(
    shell: NutonicRoute.Shell,
    onChangeShell: (NutonicRoute.Shell) -> Unit,
    settingsRepository: SettingsRepository,
    nutonicApiClient: NutonicApiClient? = null,
    serverFeatureFlags: FeatureFlags? = null,
    contentCacheRepository: ContentCacheRepository? = null,
    localNonRankedLeaderboardRepository: LocalNonRankedLeaderboardRepository? = null,
    guessRecordOutboxRepository: GuessRecordOutboxRepository? = null,
) {
    /** Shared map id for SCAN hub pick, RANK community panel, and results → RANK deep link. */
    var mapContextId by rememberSaveable { mutableStateOf("poi_0000") }

    /** Title from catalog row when known (SCAN list); cleared when map id is edited elsewhere (e.g. RANK text field). */
    var mapContextTitle by rememberSaveable { mutableStateOf<String?>(null) }

    /** Server-ranked round from `POST /api/v1/ranked/rounds/start`; cleared on non-ranked play or back (W6). */
    var rankedPlaySession by remember { mutableStateOf<RankedPlaySession?>(null) }
    var proSelectedJob by remember { mutableStateOf<ProJobStatusOut?>(null) }
    val proOverlayGuessRepository = remember { ProOverlayGuessRepository() }

    fun setMapContext(
        id: String,
        title: String?,
    ) {
        mapContextId = id
        mapContextTitle = title
    }

    fun goDetail(d: ShellDetail) {
        onChangeShell(shell.copy(detail = d))
    }

    fun goProMiniApp(
        d: ShellDetail,
        job: ProJobStatusOut?,
    ) {
        proSelectedJob = job
        goDetail(d)
    }

    fun clearDetail() {
        onChangeShell(shell.copy(detail = null))
    }

    fun selectTab(tab: MainTab) {
        onChangeShell(NutonicRoute.Shell(tab = tab, detail = null))
    }

    val detail = shell.detail
    Column(modifier = Modifier.fillMaxSize().background(MaterialTheme.colors.background)) {
        BoxMax(
            modifier =
                Modifier
                    .weight(1f)
                    .fillMaxWidth(),
        ) {
            if (detail != null) {
                when (detail) {
                    ShellDetail.WorldMapGameplay ->
                        WorldMapGameplayDetail(
                            mapId = mapContextId,
                            mapTitle = mapContextTitle,
                            playerRole = settingsRepository.settings.playerRole,
                            clientSettings = settingsRepository.settings,
                            contentCacheRepository = contentCacheRepository,
                            localLeaderboardRepository = localNonRankedLeaderboardRepository,
                            nutonicApiClient = nutonicApiClient,
                            guessRecordOutboxRepository = guessRecordOutboxRepository,
                            proOverlayGuessRepository = proOverlayGuessRepository,
                            rankedSession = rankedPlaySession,
                            onBack = {
                                rankedPlaySession = null
                                clearDetail()
                            },
                        )
                    ShellDetail.FinalResults ->
                        FinalResultsWithLocalSummary(
                            mapId = mapContextId,
                            mapTitle = mapContextTitle,
                            localLeaderboardRepository = localNonRankedLeaderboardRepository,
                            onBack = { clearDetail() },
                            onNavigateToRankForMap = { mapId ->
                                onChangeShell(
                                    NutonicRoute.Shell(
                                        tab = MainTab.Rank,
                                        detail = null,
                                        rankFocusMapId = mapId,
                                    ),
                                )
                            },
                        )
                    ShellDetail.SetupProtocol ->
                        SetupProtocolDetail(
                            settingsRepository = settingsRepository,
                            onBack = { clearDetail() },
                        )
                    ShellDetail.RankGlobal ->
                        RankGlobalDetail(
                            nutonicApiClient = nutonicApiClient,
                            serverFeatureFlags = serverFeatureFlags,
                            mapContextId = mapContextId,
                            onMapContextIdChange = { setMapContext(it, null) },
                            onBack = { clearDetail() },
                        )

                    ShellDetail.ProCoordinateDashboard ->
                        ProCoordinateDashboardDetail(
                            nutonicApiClient = nutonicApiClient,
                            serverFeatureFlags = serverFeatureFlags,
                            currentMapId = mapContextId,
                            onBack = { clearDetail() },
                            onOpenMiniApp = ::goProMiniApp,
                            onOpenGameplay = { goDetail(ShellDetail.WorldMapGameplay) },
                            onPublishGameplayOverlay = { overlay ->
                                proOverlayGuessRepository.publish(overlay)
                            },
                        )
                    ShellDetail.ProFireWatch ->
                        ProFireWatchScreen(
                            job = proSelectedJob,
                            nutonicApiClient = nutonicApiClient,
                            onBack = { clearDetail() },
                            onOpenBriefComposer = { goProMiniApp(ShellDetail.ProBriefComposer, proSelectedJob) },
                        )
                    ShellDetail.ProOceanScout ->
                        ProOceanScoutScreen(
                            job = proSelectedJob,
                            nutonicApiClient = nutonicApiClient,
                            onBack = { clearDetail() },
                            onOpenBriefComposer = { goProMiniApp(ShellDetail.ProBriefComposer, proSelectedJob) },
                        )
                    ShellDetail.ProLandShift ->
                        ProLandShiftScreen(
                            job = proSelectedJob,
                            nutonicApiClient = nutonicApiClient,
                            onBack = { clearDetail() },
                            onOpenBriefComposer = { goProMiniApp(ShellDetail.ProBriefComposer, proSelectedJob) },
                        )
                    ShellDetail.ProFloodPulse ->
                        ProFloodPulseScreen(
                            job = proSelectedJob,
                            nutonicApiClient = nutonicApiClient,
                            onBack = { clearDetail() },
                            onOpenBriefComposer = { goProMiniApp(ShellDetail.ProBriefComposer, proSelectedJob) },
                        )
                    ShellDetail.ProBriefComposer ->
                        ProBriefComposerScreen(
                            job = proSelectedJob,
                            nutonicApiClient = nutonicApiClient,
                            onBack = { clearDetail() },
                        )

                    else -> ShellDetailScreen(detail = detail, onBack = { clearDetail() })
                }
            } else {
                when (shell.tab) {
                    MainTab.ScanHub ->
                        ScanHubScreen(
                            onOpenDetail = ::goDetail,
                            nutonicApiClient = nutonicApiClient,
                            serverFeatureFlags = serverFeatureFlags,
                            mapContextId = mapContextId,
                            onMapContextSelect = ::setMapContext,
                            contentCacheRepository = contentCacheRepository,
                            rankedEnabled = serverFeatureFlags?.ranked == true,
                            onRankedSessionStarted = { rankedPlaySession = it },
                            onClearRankedSession = { rankedPlaySession = null },
                            guessRecordOutboxRepository = guessRecordOutboxRepository,
                        )
                    MainTab.Intel ->
                        IntelTabRoot(
                            onOpenDetail = ::goDetail,
                            onJumpToScanPlay = { selectTab(MainTab.ScanHub) },
                            lastPlayedMapId = mapContextId,
                            lastPlayedMapTitle = mapContextTitle,
                        )
                    MainTab.Rank ->
                        RankTabRoot(
                            onOpenDetail = ::goDetail,
                            nutonicApiClient = nutonicApiClient,
                            serverFeatureFlags = serverFeatureFlags,
                            shell = shell,
                            mapContextId = mapContextId,
                            onMapContextIdChange = { setMapContext(it, null) },
                            onConsumeRankFocus = {
                                if (shell.rankFocusMapId != null) {
                                    onChangeShell(shell.copy(rankFocusMapId = null))
                                }
                            },
                        )
                    MainTab.Setup ->
                        SetupTabRoot(
                            settingsRepository = settingsRepository,
                            onOpenDetail = ::goDetail,
                        )

                    MainTab.Pro ->
                        ProTabRoot(
                            onOpenDetail = ::goDetail,
                            nutonicApiClient = nutonicApiClient,
                            serverFeatureFlags = serverFeatureFlags,
                            currentMapId = mapContextId,
                            proOverlayCount = proOverlayGuessRepository.all().size,
                        )
                }
            }
        }
        NutonicBottomBar(
            selected = shell.tab,
            onSelect = { selectTab(it) },
        )
    }
}

@Composable
private fun FinalResultsWithLocalSummary(
    mapId: String,
    mapTitle: String?,
    localLeaderboardRepository: LocalNonRankedLeaderboardRepository?,
    onBack: () -> Unit,
    onNavigateToRankForMap: (String) -> Unit,
) {
    var summary by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(mapId, localLeaderboardRepository) {
        val repo = localLeaderboardRepository
        if (repo == null) {
            summary = null
            return@LaunchedEffect
        }
        val row = repo.rowsForMap(mapId).firstOrNull()
        summary =
            row?.let { r ->
                val ai = r.aiDistanceToTruthKm?.let { km -> "$km km" } ?: "—"
                "Last local round: ${r.humanScorePoints} pts · ${r.humanDistanceKm} km vs truth · AI vs truth $ai"
            } ?: "No completed local rounds for this map yet."
    }
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Final results", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            text =
                buildString {
                    append("Map ")
                    append(mapId)
                    mapTitle?.takeIf { it.isNotBlank() }?.let { title ->
                        append(" · ")
                        append(title)
                    }
                },
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Round recap", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                summary ?: "No completed local rounds for this map yet.",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
        NutonicPrimaryButton(
            text = "Open rankings for this map",
            onClick = { onNavigateToRankForMap(mapId) },
            modifier = Modifier.fillMaxWidth(),
        )
        NutonicGhostButton(
            text = "Back",
            onClick = onBack,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun BoxMax(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    androidx.compose.foundation.layout.Box(modifier = modifier) {
        content()
    }
}

@Composable
private fun IntelTabRoot(
    onOpenDetail: (ShellDetail) -> Unit,
    onJumpToScanPlay: () -> Unit,
    lastPlayedMapId: String,
    lastPlayedMapTitle: String?,
) {
    val tierLabel = "Field Operative"
    val tierProgress = 0.42f
    val xpDisplay = 1240
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(MainTab.Intel.label, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Progress, continuity, and one-tap return to SCAN (solo / async on a shared map_id).",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("XP summary", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                "XP $xpDisplay · $tierLabel",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Rank progress", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                "${(tierProgress * 100).toInt()}% toward next tier",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
            LinearProgressIndicator(
                progress = tierProgress,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                color = MaterialTheme.colors.primary,
                backgroundColor = NutonicColors.surfaceContainerLow,
            )
        }
        NutonicPrimaryButton(
            text = "Play now — open SCAN",
            onClick = onJumpToScanPlay,
            modifier = Modifier.fillMaxWidth(),
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Memory stability", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("87% — recent rounds look steady.", style = MaterialTheme.typography.body2)
            Text("Derived locally for comfort; not an anti-cheat signal.", style = MaterialTheme.typography.caption)
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Current session", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            val mapLine =
                lastPlayedMapTitle?.let { t -> "$t ($lastPlayedMapId)" }
                    ?: "Map $lastPlayedMapId"
            Text("Last focus: $mapLine", style = MaterialTheme.typography.body2)
            Text("Resume play from SCAN; open world map when a round is active there.", style = MaterialTheme.typography.caption)
            NutonicGhostButton(
                text = "Open world map (from SCAN)",
                onClick = { onOpenDetail(ShellDetail.WorldMapGameplay) },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Daily protocols", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("• Complete one non-ranked run (+50 XP)", style = MaterialTheme.typography.body2)
            Text("• Review ranked briefing (+25 XP)", style = MaterialTheme.typography.body2)
            Text("• Share one scorecard (+15 XP)", style = MaterialTheme.typography.body2)
        }
    }
}

@Composable
private fun RankTabRoot(
    onOpenDetail: (ShellDetail) -> Unit,
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
    shell: NutonicRoute.Shell,
    mapContextId: String,
    onMapContextIdChange: (String) -> Unit,
    onConsumeRankFocus: () -> Unit,
) {
    LaunchedEffect(shell.rankFocusMapId) {
        val focus = shell.rankFocusMapId ?: return@LaunchedEffect
        onMapContextIdChange(focus)
        onConsumeRankFocus()
    }

    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(MainTab.Rank.label, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Browse global rankings and choose a map to focus.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicPrimaryButton(
            text = "Global leaderboard & map focus",
            onClick = { onOpenDetail(ShellDetail.RankGlobal) },
            modifier = Modifier.fillMaxWidth(),
        )
        if (nutonicApiClient == null) {
            Text(
                "Connect the game client to load live leaderboards (offline catalog still works in SCAN).",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        } else {
            CommunityLeaderboardPanel(
                nutonicApiClient = nutonicApiClient,
                mapId = mapContextId,
                onMapIdChange = onMapContextIdChange,
                featureFlags = serverFeatureFlags,
                sectionTitle = "RANK · community leaderboard",
                showRankedVerifiedFetch = serverFeatureFlags?.ranked == true,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
    }
}

@Composable
private fun SetupTabRoot(
    settingsRepository: SettingsRepository,
    onOpenDetail: (ShellDetail) -> Unit,
) {
    val s = settingsRepository.settings
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(MainTab.Setup.label, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Profile, accessibility, audio, and comfort controls.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Identity & role", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            OutlinedTextField(
                value = s.displayName,
                onValueChange = { v -> settingsRepository.update { it.copy(displayName = v.take(32)) } },
                label = { Text("Display name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 8.dp),
            )
            Text(
                "Choose a role for your current play style. You can change it anytime.",
                style = MaterialTheme.typography.caption,
                color = nutonicOnSurfaceMuted(),
            )
            GameRolePicker(
                selectedRole = s.playerRole,
                onSelectRole = { id -> settingsRepository.update { it.copy(playerRole = id) } },
                modifier = Modifier.padding(top = 8.dp),
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Accessibility", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Tune motion and contrast for comfort.", style = MaterialTheme.typography.caption)
            RowToggle(
                label = "Reduced motion",
                checked = s.reducedMotion,
                onCheckedChange = { v -> settingsRepository.update { it.copy(reducedMotion = v) } },
            )
            RowToggle(
                label = "High contrast",
                checked = s.highContrast,
                onCheckedChange = { v -> settingsRepository.update { it.copy(highContrast = v) } },
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Audio", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Music follows the header music toggle.", style = MaterialTheme.typography.caption)
            RowToggle(
                label = "Music",
                checked = s.musicMasterEnabled,
                onCheckedChange = { v -> settingsRepository.update { it.copy(musicMasterEnabled = v) } },
            )
            Text("Music volume", style = MaterialTheme.typography.caption, modifier = Modifier.padding(top = 6.dp))
            Slider(
                value = s.musicVolume,
                onValueChange = { v -> settingsRepository.update { it.copy(musicVolume = v) } },
                valueRange = 0f..1f,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        NutonicPrimaryButton(
            text = "Privacy, telemetry & local data",
            onClick = { onOpenDetail(ShellDetail.SetupProtocol) },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun RowToggle(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, modifier = Modifier.weight(1f), color = MaterialTheme.colors.onBackground)
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

@Composable
private fun SetupProtocolDetail(
    settingsRepository: SettingsRepository,
    onBack: () -> Unit,
) {
    val s = settingsRepository.settings
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Setup protocol", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Manage privacy, sync behavior, and comfort settings for this device.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Profile", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            OutlinedTextField(
                value = s.displayName,
                onValueChange = { v -> settingsRepository.update { it.copy(displayName = v.take(32)) } },
                label = { Text("Display name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 8.dp),
            )
            Text("Current role: ${s.playerRole}", style = MaterialTheme.typography.body2)
            RowToggle(
                label = "Show rank badge",
                checked = s.showRankBadge,
                onCheckedChange = { v -> settingsRepository.update { it.copy(showRankBadge = v) } },
            )
            Text(
                "Role affects presentation style only and can be changed any time.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Gameplay and hints", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            RowToggle(
                label = "Show non-AI hints",
                checked = s.showNonAiHints,
                onCheckedChange = { v -> settingsRepository.update { it.copy(showNonAiHints = v) } },
            )
            RowToggle(
                label = "Show location assist text",
                checked = s.showAiGroundHints,
                onCheckedChange = { v -> settingsRepository.update { it.copy(showAiGroundHints = v) } },
            )
            RowToggle(
                label = "Show timer",
                checked = s.showTimer,
                onCheckedChange = { v -> settingsRepository.update { it.copy(showTimer = v) } },
            )
            RowToggle(
                label = "Show score preview",
                checked = s.showScorePreview,
                onCheckedChange = { v -> settingsRepository.update { it.copy(showScorePreview = v) } },
            )
            RowToggle(
                label = "Confirm before submit",
                checked = s.confirmBeforeSubmit,
                onCheckedChange = { v -> settingsRepository.update { it.copy(confirmBeforeSubmit = v) } },
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Models and assist", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            RowToggle(
                label = "Auto-refetch leaderboard",
                checked = s.autoRefetchLeaderboard,
                onCheckedChange = { v -> settingsRepository.update { it.copy(autoRefetchLeaderboard = v) } },
            )
            Text("Ranked protection rules still apply.", style = MaterialTheme.typography.caption)
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Map display", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            RowToggle(
                label = "Show coordinate readout",
                checked = s.showCoordinateReadout,
                onCheckedChange = { v -> settingsRepository.update { it.copy(showCoordinateReadout = v) } },
            )
            RowToggle(
                label = "Remember last viewport",
                checked = s.rememberLastViewport,
                onCheckedChange = { v -> settingsRepository.update { it.copy(rememberLastViewport = v) } },
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Accessibility", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            RowToggle(
                label = "Reduced motion",
                checked = s.reducedMotion,
                onCheckedChange = { v -> settingsRepository.update { it.copy(reducedMotion = v) } },
            )
            RowToggle(
                label = "High contrast",
                checked = s.highContrast,
                onCheckedChange = { v -> settingsRepository.update { it.copy(highContrast = v) } },
            )
            RowToggle(
                label = "Large data rendering",
                checked = s.largeDataRendering,
                onCheckedChange = { v -> settingsRepository.update { it.copy(largeDataRendering = v) } },
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Audio", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            RowToggle(
                label = "Music",
                checked = s.musicMasterEnabled,
                onCheckedChange = { v -> settingsRepository.update { it.copy(musicMasterEnabled = v) } },
            )
            RowToggle(
                label = "Mute when backgrounded",
                checked = s.muteWhenBackgrounded,
                onCheckedChange = { v -> settingsRepository.update { it.copy(muteWhenBackgrounded = v) } },
            )
            Text("Music volume", style = MaterialTheme.typography.caption, modifier = Modifier.padding(top = 6.dp))
            Slider(
                value = s.musicVolume,
                onValueChange = { v -> settingsRepository.update { it.copy(musicVolume = v) } },
                valueRange = 0f..1f,
                modifier = Modifier.fillMaxWidth(),
            )
            Text("SFX volume", style = MaterialTheme.typography.caption)
            Slider(
                value = s.sfxVolume,
                onValueChange = { v -> settingsRepository.update { it.copy(sfxVolume = v) } },
                valueRange = 0f..1f,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Narrative and notes", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            RowToggle(
                label = "Open narrative overlay by default",
                checked = s.overlayDefaultOpen,
                onCheckedChange = { v -> settingsRepository.update { it.copy(overlayDefaultOpen = v) } },
            )
            RowToggle(
                label = "Preserve narrative notes",
                checked = s.preserveNarrativeNotes,
                onCheckedChange = { v -> settingsRepository.update { it.copy(preserveNarrativeNotes = v) } },
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Local data and sync", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                "Scores and guesses are saved locally first and sync when the network is available.",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
            RowToggle(
                label = "Allow analytics",
                checked = s.allowAnalytics,
                onCheckedChange = { v -> settingsRepository.update { it.copy(allowAnalytics = v) } },
            )
            RowToggle(
                label = "Allow optional community sync",
                checked = s.allowOptionalCommunitySync,
                onCheckedChange = { v -> settingsRepository.update { it.copy(allowOptionalCommunitySync = v) } },
            )
            Text(
                "If sync is delayed, your progress remains available on this device.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Account and security", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Biometric unlock and remembered sign-in are not required for this reference build.", style = MaterialTheme.typography.body2)
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Danger zone", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Destructive reset actions are hidden in this build to avoid accidental data loss.", style = MaterialTheme.typography.body2)
        }
        NutonicGhostButton(
            text = "Back",
            onClick = onBack,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun RankGlobalDetail(
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
    mapContextId: String,
    onMapContextIdChange: (String) -> Unit,
    onBack: () -> Unit,
) {
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Global rankings", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Review global and map-scoped rankings, then jump back to the selected map context.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        if (nutonicApiClient == null) {
            Text(
                "Connect to the game server to load global rankings.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        } else {
            CommunityLeaderboardPanel(
                nutonicApiClient = nutonicApiClient,
                mapId = mapContextId,
                onMapIdChange = onMapContextIdChange,
                featureFlags = serverFeatureFlags,
                sectionTitle = "Global and map rankings",
                showRankedVerifiedFetch = serverFeatureFlags?.ranked == true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        NutonicGhostButton(
            text = "Back",
            onClick = onBack,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun ProTabRoot(
    onOpenDetail: (ShellDetail) -> Unit,
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
    currentMapId: String,
    proOverlayCount: Int,
) {
    val scope = rememberCoroutineScope()
    val proEnabled = serverFeatureFlags?.proJobs == true
    var probeStatus by remember { mutableStateOf("Idle") }
    var readiness by remember { mutableStateOf<ProReadinessOut?>(null) }
    var recentJobs by remember { mutableStateOf<List<ProJobStatusOut>>(emptyList()) }
    var recentStatus by remember { mutableStateOf("Not loaded") }

    LaunchedEffect(proEnabled, nutonicApiClient) {
        val client = nutonicApiClient
        if (proEnabled && client != null) {
            refreshProTabProbeAndJobs(
                client = client,
                onProbe = { probeStatus = it },
                onReadiness = { readiness = it },
                onRecentStatus = { recentStatus = it },
                onJobs = { recentJobs = it },
            )
        }
    }
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(MainTab.Pro.label, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Coordinate analysis workspace for advanced map insight and mission briefs.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Orchestration", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                "Run analysis jobs from one place, then review outputs and launch mini-app workflows.",
                style = MaterialTheme.typography.body2,
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Coordinate strip", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("WGS84 presets: Vienna, Brussels, Paris", style = MaterialTheme.typography.body2)
            Text("Use presets, refine coordinates, and export results from the dashboard.", style = MaterialTheme.typography.caption)
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("TiM / on-device VLM health", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Server probe: $probeStatus", style = MaterialTheme.typography.body2)
            readiness?.let {
                Text(
                    "PRO ready: ${if (it.ready) "yes" else "degraded"} · VLM bundle: ${it.vlmModelBundleId ?: "not available"}",
                    style = MaterialTheme.typography.body2,
                )
                if (it.degradedReasons.isNotEmpty()) {
                    Text("Needs attention: ${it.degradedReasons.joinToString()}", style = MaterialTheme.typography.caption)
                }
            }
            Text("Current gameplay map: $currentMapId · PRO overlays shared: $proOverlayCount", style = MaterialTheme.typography.caption)
            NutonicGhostButton(
                text = "Refresh PRO server probe",
                enabled = nutonicApiClient != null,
                onClick = {
                    val client = nutonicApiClient ?: return@NutonicGhostButton
                    scope.launch {
                        refreshProTabProbeAndJobs(
                            client = client,
                            onProbe = { probeStatus = it },
                            onReadiness = { readiness = it },
                            onRecentStatus = { recentStatus = it },
                            onJobs = { recentJobs = it },
                        )
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Recent PRO jobs", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(recentStatus, style = MaterialTheme.typography.caption)
            if (recentJobs.isEmpty()) {
                Text("No recent jobs for this session.", style = MaterialTheme.typography.body2)
            }
            recentJobs.take(5).forEach { job ->
                Text(
                    "${job.jobId.take(8)} · ${job.analysisProfile ?: job.profile.orEmpty()} · ${job.status} · ${job.progressPct ?: 0}%",
                    style = MaterialTheme.typography.body2,
                )
            }
        }
        if (!proEnabled) {
            Text(
                "PRO features are not available on this server yet.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.error,
            )
        }
        NutonicPrimaryButton(
            text = "Open PRO coordinate dashboard",
            onClick = { onOpenDetail(ShellDetail.ProCoordinateDashboard) },
            enabled = proEnabled,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

private suspend fun refreshProTabProbeAndJobs(
    client: NutonicApiClient,
    onProbe: (String) -> Unit,
    onReadiness: (ProReadinessOut?) -> Unit,
    onRecentStatus: (String) -> Unit,
    onJobs: (List<ProJobStatusOut>) -> Unit,
) {
    onRecentStatus("Requesting session token...")
    val token =
        when (val auth = client.postAuthToken()) {
            is ApiResult.Ok -> auth.value.accessToken
            is ApiResult.HttpFailure -> {
                onRecentStatus(auth.userMessage)
                return
            }
            is ApiResult.NetworkFailure -> {
                onRecentStatus("Network unavailable. Try again when online.")
                return
            }
        }
    when (val readiness = client.getProReadiness(token)) {
        is ApiResult.Ok -> {
            onReadiness(readiness.value)
            onProbe(
                if (readiness.value.ready) {
                    "Ready"
                } else {
                    "Degraded: ${readiness.value.degradedReasons.joinToString().ifBlank { "unknown" }}"
                },
            )
        }
        is ApiResult.HttpFailure -> {
            onReadiness(null)
            onProbe(readiness.userMessage)
        }
        is ApiResult.NetworkFailure -> {
            onReadiness(null)
            onProbe("Network unavailable")
        }
    }
    when (val jobs = client.listProJobs(token, limit = 5)) {
        is ApiResult.Ok -> {
            onJobs(jobs.value)
            onRecentStatus("Loaded ${jobs.value.size} recent job(s).")
        }
        is ApiResult.HttpFailure -> onRecentStatus(jobs.userMessage)
        is ApiResult.NetworkFailure -> onRecentStatus("Network unavailable. Could not load recent jobs.")
    }
}

@Composable
private fun NutonicBottomBar(
    selected: MainTab,
    onSelect: (MainTab) -> Unit,
) {
    val barColor = NutonicColors.surfaceContainerLow
    val primaryLine = NutonicColors.primary
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .background(barColor)
                .padding(bottom = 8.dp, top = 4.dp),
        horizontalArrangement = Arrangement.SpaceEvenly,
        verticalAlignment = Alignment.Bottom,
    ) {
        MainTab.ordered.forEach { tab ->
            val isSelected = tab == selected
            val isScan = tab == MainTab.ScanHub
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier =
                    Modifier
                        .weight(1f)
                        .clickable { onSelect(tab) }
                        .padding(vertical = 4.dp),
            ) {
                if (isSelected) {
                    androidx.compose.foundation.layout.Box(
                        modifier =
                            Modifier
                                .padding(bottom = 4.dp)
                                .size(width = 24.dp, height = 2.dp)
                                .background(primaryLine),
                    )
                } else {
                    Spacer(modifier = Modifier.height(6.dp))
                }
                if (isScan) {
                    androidx.compose.foundation.layout.Box(
                        modifier =
                            Modifier
                                .offset(y = (-10).dp)
                                .size(48.dp)
                                .background(NutonicColors.primaryContainer, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = tab.label,
                            style = MaterialTheme.typography.overline,
                            color = NutonicColors.surfaceContainerLowest,
                        )
                    }
                } else {
                    Text(
                        text = tab.label,
                        color =
                            if (isSelected) {
                                MaterialTheme.colors.primary
                            } else {
                                nutonicOnSurfaceMuted()
                            },
                        fontSize = 11.sp,
                        fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
                    )
                }
            }
        }
    }
}
