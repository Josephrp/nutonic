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
import androidx.compose.material.Button
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
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.nutonic.api.ApiResult
import com.nutonic.api.FeatureFlags
import com.nutonic.api.MapSummary
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.RankedRoundStartIn
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.cache.ManifestSyncResult
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRepository
import com.nutonic.model.PictureData
import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.ShellDetail
import com.nutonic.screens.CommunityLeaderboardPanel
import com.nutonic.screens.GameRolePicker
import com.nutonic.screens.RankedPlaySession
import com.nutonic.screens.ShellDetailPlaceholder
import com.nutonic.screens.WorldMapGameplayDetail
import com.nutonic.settings.SettingsRepository
import kotlinx.coroutines.launch

private enum class AppRoot {
    Shell,
    LegacyGallery,
}

@Composable
fun NutonicMainShell(
    pictures: SnapshotStateList<PictureData>,
    shell: NutonicRoute.Shell,
    onChangeShell: (NutonicRoute.Shell) -> Unit,
    settingsRepository: SettingsRepository,
    nutonicApiClient: NutonicApiClient? = null,
    serverFeatureFlags: FeatureFlags? = null,
    contentCacheRepository: ContentCacheRepository? = null,
    localNonRankedLeaderboardRepository: LocalNonRankedLeaderboardRepository? = null,
) {
    var root by rememberSaveable { mutableStateOf(AppRoot.Shell) }

    /** Shared `map_id` for SCAN hub pick, RANK community panel, and results → RANK deep link (`IMP-071`). */
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

    when (root) {
        AppRoot.LegacyGallery -> {
            Column(modifier = Modifier.fillMaxSize()) {
                Row(
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .background(MaterialTheme.colors.surface)
                            .padding(horizontal = 8.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Button(onClick = { root = AppRoot.Shell }) {
                        Text("Back to NU:TONIC shell")
                    }
                }
                NutonicPhotoGalleryFlow(pictures)
            }
        }

        AppRoot.Shell -> {
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
                                ScanHubRoot(
                                    onOpenDetail = ::goDetail,
                                    nutonicApiClient = nutonicApiClient,
                                    serverFeatureFlags = serverFeatureFlags,
                                    mapContextId = mapContextId,
                                    onMapContextSelect = ::setMapContext,
                                    contentCacheRepository = contentCacheRepository,
                                    rankedEnabled = serverFeatureFlags?.ranked == true,
                                    onRankedSessionStarted = { rankedPlaySession = it },
                                    onClearRankedSession = { rankedPlaySession = null },
                                )
                            MainTab.Intel -> IntelTabRoot(onOpenDetail = ::goDetail)
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
                                    onOpenLegacyGallery = { root = AppRoot.LegacyGallery },
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

private fun manifestLineForSync(m: ManifestSyncResult): String =
    when (m) {
        is ManifestSyncResult.Updated ->
            "Manifest: updated ${m.document.contentVersion} (ETag ${m.etag.take(16)}…)"
        is ManifestSyncResult.NotModified ->
            "Manifest: up to date (${m.document.contentVersion})"
        is ManifestSyncResult.UsedStaleCache ->
            "Manifest: using cached ${m.document.contentVersion} (${m.reason})"
        is ManifestSyncResult.Failed -> "Manifest: ${m.reason}"
    }

private fun mapsFromManifestSync(m: ManifestSyncResult): List<MapSummary>? =
    when (m) {
        is ManifestSyncResult.Updated -> m.document.maps
        is ManifestSyncResult.NotModified -> m.document.maps
        is ManifestSyncResult.UsedStaleCache -> m.document.maps
        is ManifestSyncResult.Failed -> null
    }

/**
 * Single hydration pass: refresh manifest first, then use [CacheManifestDocument.maps] when present
 * so SCAN catalog tracks the same snapshot as gameplay (`rules/13`); falls back to `GET /api/v1/maps`.
 */
private suspend fun scanHubRefreshCatalog(
    client: NutonicApiClient,
    contentCacheRepository: ContentCacheRepository?,
    mapContextId: String,
    onManifestLine: (String?) -> Unit,
    onMapsStatus: (String?) -> Unit,
    onMaps: (List<MapSummary>) -> Unit,
    onMapContextSelect: (String, String?) -> Unit,
) {
    val sync = contentCacheRepository?.refreshManifest()
    onManifestLine(sync?.let(::manifestLineForSync))

    val fromManifest = sync?.let(::mapsFromManifestSync)
    if (!fromManifest.isNullOrEmpty()) {
        onMaps(fromManifest)
        onMapsStatus(null)
        val ids = fromManifest.map { it.mapId }
        if (mapContextId !in ids) {
            val first = fromManifest.first()
            onMapContextSelect(first.mapId, first.title)
        }
        return
    }

    onMapsStatus("Fetching maps…")
    when (val r = client.getMaps()) {
        is ApiResult.Ok -> {
            onMaps(r.value)
            onMapsStatus(null)
            val ids = r.value.map { it.mapId }
            if (mapContextId !in ids && r.value.isNotEmpty()) {
                val first = r.value.first()
                onMapContextSelect(first.mapId, first.title)
            }
        }

        is ApiResult.HttpFailure -> {
            onMaps(emptyList())
            onMapsStatus(r.userMessage)
            val fb = contentCacheRepository?.cachedMapsOrNull()
            if (!fb.isNullOrEmpty()) {
                onMaps(fb)
                onMapsStatus("${r.userMessage} Showing catalog from last manifest cache.")
            }
        }

        is ApiResult.NetworkFailure -> {
            onMaps(emptyList())
            onMapsStatus("Network: ${r.debugMessage}")
            val fb = contentCacheRepository?.cachedMapsOrNull()
            if (!fb.isNullOrEmpty()) {
                onMaps(fb)
                onMapsStatus("Network: ${r.debugMessage} Showing catalog from last manifest cache.")
            }
        }
    }
}

@Composable
private fun ScanHubRoot(
    onOpenDetail: (ShellDetail) -> Unit,
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
    mapContextId: String,
    onMapContextSelect: (String, String?) -> Unit,
    contentCacheRepository: ContentCacheRepository?,
    rankedEnabled: Boolean,
    onRankedSessionStarted: (RankedPlaySession) -> Unit,
    onClearRankedSession: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var maps by remember { mutableStateOf<List<MapSummary>>(emptyList()) }
    var mapsStatus by remember { mutableStateOf<String?>(null) }
    var manifestLine by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(nutonicApiClient, contentCacheRepository) {
        val client = nutonicApiClient ?: return@LaunchedEffect
        scanHubRefreshCatalog(
            client = client,
            contentCacheRepository = contentCacheRepository,
            mapContextId = mapContextId,
            onManifestLine = { manifestLine = it },
            onMapsStatus = { mapsStatus = it },
            onMaps = { maps = it },
            onMapContextSelect = onMapContextSelect,
        )
    }

    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            text = MainTab.ScanHub.label,
            style = MaterialTheme.typography.h5,
            color = MaterialTheme.colors.primary,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = "SCAN hub — mission, map pick, leaderboard slice, play entry (rules/07 #4b–4c, #5)",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NavStubButton("Mission selection (#4c)") { onOpenDetail(ShellDetail.MissionSelection) }
        NavStubButton("Map / level selection (#4b)") { onOpenDetail(ShellDetail.MapLevelSelection) }
        NavStubButton("World map gameplay (#5)") {
            onClearRankedSession()
            onOpenDetail(ShellDetail.WorldMapGameplay)
        }
        NavStubButton("Success overlay (#6)") { onOpenDetail(ShellDetail.SuccessOverlay) }
        NavStubButton("Final results (#7)") { onOpenDetail(ShellDetail.FinalResults) }

        if (nutonicApiClient == null) {
            Text(
                "Map catalog fetch needs a wired NutonicApiClient (same origin as game server).",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        } else {
            manifestLine?.let { line ->
                Text(
                    line,
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.onBackground,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
            Text(
                "Map catalog: manifest refresh first, then `GET /api/v1/maps` only if needed (IMP-080 / IMP-072).",
                style = MaterialTheme.typography.subtitle1,
                color = MaterialTheme.colors.primary,
                modifier = Modifier.padding(top = 16.dp),
            )
            Button(
                onClick = {
                    scope.launch {
                        scanHubRefreshCatalog(
                            client = nutonicApiClient,
                            contentCacheRepository = contentCacheRepository,
                            mapContextId = mapContextId,
                            onManifestLine = { manifestLine = it },
                            onMapsStatus = { mapsStatus = it },
                            onMaps = { maps = it },
                            onMapContextSelect = onMapContextSelect,
                        )
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Refresh map list from server")
            }
            mapsStatus?.let {
                Text(it, style = MaterialTheme.typography.body2, color = MaterialTheme.colors.error)
            }
            if (maps.isNotEmpty()) {
                Text(
                    "Tap a map to drive the hub leaderboard (`rules/05`, same panel as RANK).",
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.onBackground,
                    modifier = Modifier.padding(top = 8.dp),
                )
                maps.forEach { m ->
                    val selected = m.mapId == mapContextId
                    Text(
                        "${if (selected) "▸ " else ""}${m.mapId} — ${m.title}" +
                            m.engineVersion?.let { ev -> " (engine $ev)" }.orEmpty(),
                        style = MaterialTheme.typography.body2,
                        color =
                            if (selected) {
                                MaterialTheme.colors.primary
                            } else {
                                MaterialTheme.colors.onBackground
                            },
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .clickable { onMapContextSelect(m.mapId, m.title) }
                                .padding(vertical = 6.dp),
                    )
                }
                Button(
                    onClick = {
                        onClearRankedSession()
                        onOpenDetail(ShellDetail.WorldMapGameplay)
                    },
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                ) {
                    Text("Play selected map — world map (#5, IMP-073)")
                }
                if (rankedEnabled) {
                    Button(
                        onClick = {
                            scope.launch {
                                val client = nutonicApiClient ?: return@launch
                                when (val tok = client.postAuthToken()) {
                                    is ApiResult.Ok -> {
                                        when (
                                            val st =
                                                client.postRankedRoundStart(
                                                    RankedRoundStartIn(mapId = mapContextId),
                                                    tok.value.accessToken,
                                                )
                                        ) {
                                            is ApiResult.Ok -> {
                                                val out = st.value
                                                onRankedSessionStarted(
                                                    RankedPlaySession(
                                                        roundId = out.roundId,
                                                        roundTicket = out.roundTicket,
                                                        clue = out.clue,
                                                    ),
                                                )
                                                onOpenDetail(ShellDetail.WorldMapGameplay)
                                            }

                                            is ApiResult.HttpFailure ->
                                                mapsStatus =
                                                    "Ranked start failed: ${st.userMessage}"

                                            is ApiResult.NetworkFailure ->
                                                mapsStatus =
                                                    "Ranked start failed: ${st.debugMessage}"
                                        }
                                    }

                                    is ApiResult.HttpFailure ->
                                        mapsStatus = "Auth failed: ${tok.userMessage}"

                                    is ApiResult.NetworkFailure ->
                                        mapsStatus = "Auth failed: ${tok.debugMessage}"
                                }
                            }
                        },
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    ) {
                        Text("Start ranked server round (IMP-090)")
                    }
                }
            }
            CommunityLeaderboardPanel(
                nutonicApiClient = nutonicApiClient,
                mapId = mapContextId,
                onMapIdChange = null,
                featureFlags = serverFeatureFlags,
                sectionTitle = "SCAN hub · community leaderboard preview",
                showRankedVerifiedFetch = serverFeatureFlags?.ranked == true,
                modifier = Modifier.padding(top = 16.dp),
            )
        }
    }
}

@Composable
private fun IntelTabRoot(onOpenDetail: (ShellDetail) -> Unit) {
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(MainTab.Intel.label, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "INTEL tab shell — open dashboard checklist surface",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NavStubButton("Dashboard (#4)") { onOpenDetail(ShellDetail.IntelDashboard) }
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
            "RANK tab — global boards + map_id pick (rules/01)",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NavStubButton("Global / map leaderboard flow") { onOpenDetail(ShellDetail.RankGlobal) }
        if (nutonicApiClient == null) {
            Text(
                "Game server client not wired on this entry point (NutonicApiClient is null).",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        } else {
            CommunityLeaderboardPanel(
                nutonicApiClient = nutonicApiClient,
                mapId = mapContextId,
                onMapIdChange = onMapContextIdChange,
                featureFlags = serverFeatureFlags,
                sectionTitle = "RANK · community leaderboard (same composable as SCAN hub)",
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
    onOpenLegacyGallery: () -> Unit,
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
            "SETUP — accessibility toggles affect theme (IMP-051, CLIENT-SETTINGS-SPEC §4)",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        Text(
            "Role (change anytime)",
            style = MaterialTheme.typography.subtitle1,
            color = MaterialTheme.colors.primary,
        )
        GameRolePicker(
            selectedRole = s.playerRole,
            onSelectRole = { id -> settingsRepository.update { it.copy(playerRole = id) } },
        )
        RowToggle(
            label = "Reduced motion (`a11y.reduced_motion`)",
            checked = s.reducedMotion,
            onCheckedChange = { v -> settingsRepository.update { it.copy(reducedMotion = v) } },
        )
        RowToggle(
            label = "High contrast (`a11y.high_contrast`)",
            checked = s.highContrast,
            onCheckedChange = { v -> settingsRepository.update { it.copy(highContrast = v) } },
        )
        RowToggle(
            label = "Music master (`audio.music_master_enabled`)",
            checked = s.musicMasterEnabled,
            onCheckedChange = { v -> settingsRepository.update { it.copy(musicMasterEnabled = v) } },
        )
        NavStubButton("Full protocol / security screen (#8)") { onOpenDetail(ShellDetail.SetupProtocol) }
        Button(onClick = onOpenLegacyGallery) {
            Text("Open legacy sample gallery")
        }
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
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(MainTab.Pro.label, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "PRO — coordinate dashboard + on-device VLM port (rules/06, PRO spec)",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NavStubButton("PRO dashboard placeholder") { onOpenDetail(ShellDetail.ProCoordinateDashboard) }
    }
}

@Composable
private fun NavStubButton(
    text: String,
    onClick: () -> Unit,
) {
    Button(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Text(text)
    }
}

@Composable
private fun NutonicBottomBar(
    selected: MainTab,
    onSelect: (MainTab) -> Unit,
) {
    val barColor = MaterialTheme.colors.surface
    val primaryLine = MaterialTheme.colors.primary
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
                                .background(MaterialTheme.colors.primaryVariant, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = tab.label,
                            style = MaterialTheme.typography.overline,
                            color = MaterialTheme.colors.onPrimary,
                        )
                    }
                } else {
                    Text(
                        text = tab.label,
                        color =
                            if (isSelected) {
                                MaterialTheme.colors.primary
                            } else {
                                MaterialTheme.colors.onSurface.copy(alpha = 0.75f)
                            },
                        fontSize = 11.sp,
                        fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
                    )
                }
            }
        }
    }
}
