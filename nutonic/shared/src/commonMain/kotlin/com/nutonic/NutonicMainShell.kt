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
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.cache.ProOverlayGuess
import com.nutonic.cache.ProOverlayGuessRepository
import com.nutonic.leaderboard.GuessRecordOutboxRepository
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRow
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRepository
import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.ShellDetail
import com.nutonic.progress.PlayerProgressRepository
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
import kotlin.math.round
import kotlin.math.sqrt
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
    playerProgressRepository: PlayerProgressRepository? = null,
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
                            playerProgressRepository = playerProgressRepository,
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
                            displayHandle = settingsRepository.settings.displayName.trim().ifBlank { "Operative" },
                            playerRole = settingsRepository.settings.playerRole,
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
                            onNavigateToRank = { selectTab(MainTab.Rank) },
                            operatorDisplayName = settingsRepository.settings.displayName,
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
                    MainTab.Rank ->
                        RankTabRoot(
                            onOpenDetail = ::goDetail,
                            onJumpToScanPlay = { selectTab(MainTab.ScanHub) },
                            nutonicApiClient = nutonicApiClient,
                            serverFeatureFlags = serverFeatureFlags,
                            shell = shell,
                            mapContextId = mapContextId,
                            mapContextTitle = mapContextTitle,
                            onMapContextIdChange = { setMapContext(it, null) },
                            onConsumeRankFocus = {
                                if (shell.rankFocusMapId != null) {
                                    onChangeShell(shell.copy(rankFocusMapId = null))
                                }
                            },
                            settingsRepository = settingsRepository,
                            localNonRankedLeaderboardRepository = localNonRankedLeaderboardRepository,
                            playerProgressRepository = playerProgressRepository,
                        )
                    MainTab.Setup ->
                        SetupTabRoot(
                            settingsRepository = settingsRepository,
                            onOpenDetail = ::goDetail,
                        )

                    MainTab.Pro ->
                        ProTabDashboardBody(
                            serverFeatureFlags = serverFeatureFlags,
                            nutonicApiClient = nutonicApiClient,
                            mapContextId = mapContextId,
                            onLeavePro = { selectTab(MainTab.ScanHub) },
                            onOpenMiniApp = ::goProMiniApp,
                            onOpenGameplay = { goDetail(ShellDetail.WorldMapGameplay) },
                            onPublishGameplayOverlay = { overlay ->
                                proOverlayGuessRepository.publish(overlay)
                            },
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
private fun RankTabRoot(
    onOpenDetail: (ShellDetail) -> Unit,
    onJumpToScanPlay: () -> Unit,
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
    shell: NutonicRoute.Shell,
    mapContextId: String,
    mapContextTitle: String?,
    onMapContextIdChange: (String) -> Unit,
    onConsumeRankFocus: () -> Unit,
    settingsRepository: SettingsRepository,
    localNonRankedLeaderboardRepository: LocalNonRankedLeaderboardRepository?,
    playerProgressRepository: PlayerProgressRepository?,
) {
    val settings = settingsRepository.settings
    val progress = playerProgressRepository?.progress
    var localRows by remember { mutableStateOf<List<LocalNonRankedLeaderboardRow>>(emptyList()) }

    LaunchedEffect(shell.rankFocusMapId) {
        val focus = shell.rankFocusMapId ?: return@LaunchedEffect
        onMapContextIdChange(focus)
        onConsumeRankFocus()
    }

    LaunchedEffect(mapContextId, localNonRankedLeaderboardRepository) {
        val repo = localNonRankedLeaderboardRepository
        localRows =
            if (repo == null) {
                emptyList()
            } else {
                repo.rowsForMap(mapContextId)
            }
    }

    val bestScore = localRows.maxOfOrNull { it.humanScorePoints }
    val lastRound = localRows.firstOrNull()
    val stabilityLine =
        if (localRows.size < 2) {
            "Finish at least two non-ranked rounds on this map to see score spread."
        } else {
            val pts = localRows.take(8).map { it.humanScorePoints.toDouble() }
            val mean = pts.average()
            val variance = pts.map { (it - mean) * (it - mean) }.average()
            val sd = sqrt(variance)
            "Recent local scores: σ ≈ ${round(sd).toInt()} pts over ${pts.size} round(s)."
        }

    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(MainTab.Rank.label, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Your progress on this device and community boards for the focused map.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        val name = settings.displayName.trim()
        if (name.isNotEmpty()) {
            Text(
                "Operator: $name",
                style = MaterialTheme.typography.subtitle2,
                color = MaterialTheme.colors.primary,
            )
        }
        NutonicPrimaryButton(
            text = "Play now — open SCAN",
            onClick = onJumpToScanPlay,
            modifier = Modifier.fillMaxWidth(),
        )
        if (progress != null) {
            NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
                Text("Career (this device)", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
                Text(
                    "${progress.roundsCompleted} non-ranked round(s) completed · ${progress.lifetimeScorePoints} lifetime pts",
                    style = MaterialTheme.typography.body2,
                    color = MaterialTheme.colors.onBackground,
                )
                Text(
                    "${progress.mapsPlayed.size} map(s) touched · ${progress.screenVisitCounts.size} experience surface(s) tracked",
                    style = MaterialTheme.typography.caption,
                    color = nutonicOnSurfaceMuted(),
                )
                progress.lastRoundScorePoints?.let { lp ->
                    Text(
                        "Last round: $lp pts on ${progress.lastRoundMapId ?: "?"}",
                        style = MaterialTheme.typography.caption,
                        color = nutonicOnSurfaceMuted(),
                    )
                }
            }
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Local rounds (this map)", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                "${localRows.size} saved round(s) on $mapContextId",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
            bestScore?.let {
                Text(
                    "Best score: $it pts",
                    style = MaterialTheme.typography.body2,
                    color = MaterialTheme.colors.onBackground,
                )
            }
            lastRound?.let {
                val handle = it.displayHandle.trim().ifBlank { settings.displayName.trim() }.ifBlank { "—" }
                Text(
                    "Latest ($handle): ${it.humanScorePoints} pts · ${it.humanDistanceKm} km vs truth",
                    style = MaterialTheme.typography.caption,
                    color = nutonicOnSurfaceMuted(),
                )
            }
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Score consistency", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                stabilityLine,
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Current focus", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            val mapLine =
                mapContextTitle?.let { t -> "$t ($mapContextId)" }
                    ?: "Map $mapContextId"
            Text(
                "Selected: $mapLine",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
            Text(
                "Resume play from SCAN, or open the world map here.",
                style = MaterialTheme.typography.caption,
                color = nutonicOnSurfaceMuted(),
            )
            NutonicGhostButton(
                text = "Open world map",
                onClick = { onOpenDetail(ShellDetail.WorldMapGameplay) },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }
        NutonicPrimaryButton(
            text = "Global leaderboard & map focus",
            onClick = { onOpenDetail(ShellDetail.RankGlobal) },
            modifier = Modifier.fillMaxWidth(),
        )
        if (nutonicApiClient == null) {
            Text(
                "Connect the game client to load live leaderboards.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        } else {
            CommunityLeaderboardPanel(
                nutonicApiClient = nutonicApiClient,
                mapId = mapContextId,
                onMapIdChange = onMapContextIdChange,
                featureFlags = serverFeatureFlags,
                sectionTitle = "Community leaderboard",
                showRankedVerifiedFetch = serverFeatureFlags?.ranked == true,
                displayHandle = settings.displayName.trim().ifBlank { "Operative" },
                playerRole = settings.playerRole,
                autoRefetchOnOpen = settings.autoRefetchLeaderboard,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
    }
}

@Composable
private fun ProTabDashboardBody(
    serverFeatureFlags: FeatureFlags?,
    nutonicApiClient: NutonicApiClient?,
    mapContextId: String,
    onLeavePro: () -> Unit,
    onOpenMiniApp: (ShellDetail, ProJobStatusOut?) -> Unit,
    onOpenGameplay: () -> Unit,
    onPublishGameplayOverlay: (ProOverlayGuess) -> Unit,
) {
    val proEnabled = serverFeatureFlags?.proJobs == true
    if (!proEnabled) {
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
                "PRO analysis jobs are not enabled on this server.",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.error,
            )
            NutonicGhostButton(text = "Back to SCAN", onClick = onLeavePro, modifier = Modifier.fillMaxWidth())
        }
    } else {
        ProCoordinateDashboardDetail(
            nutonicApiClient = nutonicApiClient,
            serverFeatureFlags = serverFeatureFlags,
            currentMapId = mapContextId,
            onBack = onLeavePro,
            onOpenMiniApp = onOpenMiniApp,
            onOpenGameplay = onOpenGameplay,
            onPublishGameplayOverlay = onPublishGameplayOverlay,
        )
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
            Text(
                "Biometric unlock and remembered sign-in are not required for this reference build.",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Danger zone", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                "Destructive reset actions are hidden in this build to avoid accidental data loss.",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
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
private fun RankGlobalDetail(
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
    mapContextId: String,
    onMapContextIdChange: (String) -> Unit,
    onBack: () -> Unit,
    displayHandle: String,
    playerRole: String?,
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
                displayHandle = displayHandle,
                playerRole = playerRole,
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
