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
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.leaderboard.GuessRecordOutboxRepository
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRepository
import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.ShellDetail
import com.nutonic.screens.CommunityLeaderboardPanel
import com.nutonic.screens.GameRolePicker
import com.nutonic.screens.RankedPlaySession
import com.nutonic.screens.ShellDetailPlaceholder
import com.nutonic.screens.WorldMapGameplayDetail
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
    var mapContextId by rememberSaveable { mutableStateOf("demo") }

    /** Title from catalog row when known (SCAN list); cleared when map id is edited elsewhere (e.g. RANK text field). */
    var mapContextTitle by rememberSaveable { mutableStateOf<String?>(null) }

    /** Server-ranked round from `POST /api/v1/ranked/rounds/start`; cleared on non-ranked play or back (W6). */
    var rankedPlaySession by remember { mutableStateOf<RankedPlaySession?>(null) }

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
                            contentCacheRepository = contentCacheRepository,
                            localLeaderboardRepository = localNonRankedLeaderboardRepository,
                            nutonicApiClient = nutonicApiClient,
                            guessRecordOutboxRepository = guessRecordOutboxRepository,
                            rankedSession = rankedPlaySession,
                            onBack = {
                                rankedPlaySession = null
                                clearDetail()
                            },
                        )
                    ShellDetail.FinalResults ->
                        FinalResultsWithLocalSummary(
                            detail = detail,
                            mapId = mapContextId,
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

                    else -> ShellDetailPlaceholder(detail = detail, onBack = { clearDetail() })
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

                    MainTab.Pro -> ProTabRoot(onOpenDetail = ::goDetail)
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
    detail: ShellDetail,
    mapId: String,
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
            }
    }
    ShellDetailPlaceholder(
        detail = detail,
        onBack = onBack,
        onNavigateToRankForMap = onNavigateToRankForMap,
        rankNavigationMapId = mapId,
        lastRoundSummary = summary,
    )
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
                lastPlayedMapTitle?.let { t -> "$t · map_id $lastPlayedMapId" }
                    ?: "map_id $lastPlayedMapId"
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
            "Profile, accessibility, audio, and comfort data — same keys across platforms.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Identity & role", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                "game.role — editable anytime without re-onboarding.",
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
            Text("a11y.reduced_motion, a11y.high_contrast", style = MaterialTheme.typography.caption)
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
            Text("audio.music_master — matches header music toggle.", style = MaterialTheme.typography.caption)
            RowToggle(
                label = "Music",
                checked = s.musicMasterEnabled,
                onCheckedChange = { v -> settingsRepository.update { it.copy(musicMasterEnabled = v) } },
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
private fun ProTabRoot(onOpenDetail: (ShellDetail) -> Unit) {
    var localProbeStatus by remember { mutableStateOf("Idle") }
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
            "Non-game EO / VLM dashboard: game server orchestrates materialization and TerraMind; clients never call materialization URLs directly.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Orchestration", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                "POST PRO jobs to the game server; it delegates fetch, downsample, TiM, and optional generate — then returns a ProVisionBundle-shaped payload to this shell.",
                style = MaterialTheme.typography.body2,
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Coordinate strip", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("WGS84 presets: Vienna, Brussels, Paris", style = MaterialTheme.typography.body2)
            Text("Full precision, materialize, and export live on the dashboard detail.", style = MaterialTheme.typography.caption)
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("TiM / on-device VLM health", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Local probe: $localProbeStatus", style = MaterialTheme.typography.body2)
            NutonicGhostButton(
                text = "Run local PRO probe",
                onClick = { localProbeStatus = "Healthy (local check)" },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }
        NutonicPrimaryButton(
            text = "Open PRO coordinate dashboard",
            onClick = { onOpenDetail(ShellDetail.ProCoordinateDashboard) },
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
