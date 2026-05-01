package com.nutonic.shell

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.Card
import androidx.compose.material.MaterialTheme
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
import com.nutonic.MainTab
import com.nutonic.api.ApiResult
import com.nutonic.api.MapSummary
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.RankedRoundStartIn
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.leaderboard.GuessRecordOutboxRepository
import com.nutonic.navigation.ShellDetail
import com.nutonic.screens.RankedPlaySession
import com.nutonic.style.NutonicColors
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard
import com.nutonic.style.NutonicPrimaryButton
import kotlinx.coroutines.launch

private const val MAPS_PER_PAGE = 3

@Composable
fun ScanHubScreen(
    onOpenDetail: (ShellDetail) -> Unit,
    onNavigateToRank: () -> Unit,
    operatorDisplayName: String,
    nutonicApiClient: NutonicApiClient?,
    mapContextId: String,
    onMapContextSelect: (String, String?) -> Unit,
    contentCacheRepository: ContentCacheRepository?,
    rankedEnabled: Boolean,
    onRankedSessionStarted: (RankedPlaySession) -> Unit,
    onClearRankedSession: () -> Unit,
    guessRecordOutboxRepository: GuessRecordOutboxRepository? = null,
) {
    val scope = rememberCoroutineScope()
    var maps by remember { mutableStateOf<List<MapSummary>>(emptyList()) }
    var mapsStatus by remember { mutableStateOf<String?>(null) }
    var manifestLine by remember { mutableStateOf<String?>(null) }
    var selectedMissionId by rememberSaveable { mutableStateOf("mission_recon") }
    var catalogDetailsOpen by rememberSaveable { mutableStateOf(false) }

    LaunchedEffect(nutonicApiClient, contentCacheRepository) {
        val client = nutonicApiClient ?: return@LaunchedEffect
        refreshScanHubCatalog(
            client = client,
            contentCacheRepository = contentCacheRepository,
            mapContextId = mapContextId,
            onManifestLine = { manifestLine = it },
            onMapsStatus = { mapsStatus = it },
            onMaps = { maps = it },
            onMapContextSelect = onMapContextSelect,
        )
    }

    LaunchedEffect(nutonicApiClient, guessRecordOutboxRepository) {
        val client = nutonicApiClient ?: return@LaunchedEffect
        val outbox = guessRecordOutboxRepository ?: return@LaunchedEffect
        outbox.flushPending(client)
    }

    val selectedMap = maps.firstOrNull { it.mapId == mapContextId }
    val missionOptions = remember(selectedMap?.mapId, selectedMap?.title) { buildScanMissionOptions(selectedMap) }
    LaunchedEffect(missionOptions) {
        val ids = missionOptions.map { it.missionId }
        if (selectedMissionId !in ids) {
            selectedMissionId = missionOptions.first().missionId
        }
    }
    val selectedMission = missionOptions.firstOrNull { it.missionId == selectedMissionId } ?: missionOptions.first()

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
            text = "Pick how you want to play, choose a map, then jump in.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        val greet = operatorDisplayName.trim()
        if (greet.isNotEmpty()) {
            Text(
                text = "Welcome, $greet",
                style = MaterialTheme.typography.subtitle2,
                color = MaterialTheme.colors.primary,
            )
        }
        NutonicGlassCard(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        ) {
            Text(
                text = "Mission",
                style = MaterialTheme.typography.subtitle1,
                color = MaterialTheme.colors.primary,
            )
            Text(
                text = selectedMission.narrative,
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
                modifier = Modifier.padding(top = 6.dp, bottom = 8.dp),
            )
            missionOptions.forEach { mission ->
                val selected = mission.missionId == selectedMissionId
                val title = if (selected) "[Selected] ${mission.title}" else mission.title
                if (selected) {
                    NutonicPrimaryButton(
                        text = title,
                        onClick = { selectedMissionId = mission.missionId },
                        modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp),
                    )
                } else {
                    NutonicGhostButton(
                        text = title,
                        onClick = { selectedMissionId = mission.missionId },
                        modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp),
                    )
                }
            }
            Text(
                text = "Selected: ${selectedMission.title}",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        }

        if (nutonicApiClient == null) {
            Text(
                "Connect this client to your game server to refresh maps from the network. Offline bundles still work.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        } else {
            NutonicGlassCard(
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            ) {
                Text(
                    "Maps",
                    style = MaterialTheme.typography.subtitle1,
                    color = MaterialTheme.colors.primary,
                )
                Text(
                    "Swipe sideways to browse. Tap a card to select it for play.",
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.onBackground,
                    modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
                )
                NutonicGhostButton(
                    text = "Refresh map list",
                    onClick = {
                        scope.launch {
                            refreshScanHubCatalog(
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
                )
                Row(
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .padding(top = 6.dp)
                            .clickable { catalogDetailsOpen = !catalogDetailsOpen },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        if (catalogDetailsOpen) "Hide catalog details" else "Show catalog details",
                        style = MaterialTheme.typography.caption,
                        color = MaterialTheme.colors.primary,
                    )
                }
                if (catalogDetailsOpen) {
                    manifestLine?.let { line ->
                        Text(
                            line,
                            style = MaterialTheme.typography.caption,
                            color = MaterialTheme.colors.onBackground,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                }
                mapsStatus?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.body2,
                        color = MaterialTheme.colors.error,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
                if (maps.isNotEmpty()) {
                    val mapPages = remember(maps) { maps.chunked(MAPS_PER_PAGE) }
                    val selectedPageIndex =
                        remember(mapContextId, maps) {
                            val idx = maps.indexOfFirst { it.mapId == mapContextId }
                            if (idx < 0) 0 else idx / MAPS_PER_PAGE
                        }
                    val pagerState =
                        rememberPagerState(
                            initialPage =
                                selectedPageIndex.coerceIn(
                                    0,
                                    (mapPages.size - 1).coerceAtLeast(0),
                                ),
                            pageCount = { mapPages.size },
                        )
                    LaunchedEffect(mapContextId, maps) {
                        val target =
                            selectedPageIndex.coerceIn(0, (mapPages.size - 1).coerceAtLeast(0))
                        if (mapPages.isNotEmpty() && pagerState.currentPage != target) {
                            pagerState.scrollToPage(target)
                        }
                    }
                    HorizontalPager(
                        state = pagerState,
                        modifier =
                            Modifier
                                .fillMaxWidth()
                                .height(280.dp)
                                .padding(top = 12.dp),
                    ) { page ->
                        val chunk = mapPages.getOrElse(page) { emptyList() }
                        Column(
                            modifier = Modifier.fillMaxWidth(),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            chunk.forEach { m ->
                                val selected = m.mapId == mapContextId
                                Card(
                                    modifier =
                                        Modifier
                                            .fillMaxWidth()
                                            .clickable { onMapContextSelect(m.mapId, m.title) },
                                    backgroundColor =
                                        if (selected) {
                                            NutonicColors.surfaceContainerHigh.copy(alpha = 0.85f)
                                        } else {
                                            NutonicColors.surfaceContainerLow.copy(alpha = 0.55f)
                                        },
                                    elevation = 0.dp,
                                ) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 12.dp),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(
                                                text = m.title.ifBlank { m.mapId },
                                                style = MaterialTheme.typography.subtitle2,
                                                color = MaterialTheme.colors.primary,
                                            )
                                            Text(
                                                text = m.mapId,
                                                style = MaterialTheme.typography.caption,
                                                color = MaterialTheme.colors.onBackground,
                                            )
                                        }
                                        Text(
                                            text = if (selected) "●" else "›",
                                            style = MaterialTheme.typography.h6,
                                            color = MaterialTheme.colors.primary,
                                        )
                                    }
                                }
                            }
                        }
                    }
                    Text(
                        text = "Page ${pagerState.currentPage + 1} of ${mapPages.size} · swipe for more maps",
                        style = MaterialTheme.typography.caption,
                        color = MaterialTheme.colors.onBackground,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                    NutonicPrimaryButton(
                        text = "View leaderboards (RANK)",
                        onClick = onNavigateToRank,
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                    )
                    Text(
                        text = "Play",
                        style = MaterialTheme.typography.subtitle1,
                        color = MaterialTheme.colors.primary,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                    NutonicPrimaryButton(
                        text = "Play on selected map",
                        onClick = {
                            onClearRankedSession()
                            onOpenDetail(ShellDetail.WorldMapGameplay)
                        },
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
                    if (rankedEnabled) {
                        NutonicGhostButton(
                            text = "Start ranked round",
                            onClick = {
                                scope.launch {
                                    val client = nutonicApiClient
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
                                                        "Ranked start failed due to network. Try again when online."
                                            }
                                        }

                                        is ApiResult.HttpFailure ->
                                            mapsStatus = "Session token failed: ${tok.userMessage}"

                                        is ApiResult.NetworkFailure ->
                                            mapsStatus = "Network unavailable. Try again when online."
                                    }
                                }
                            },
                            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        )
                    }
                    NutonicGhostButton(
                        text = "Round summary preview",
                        onClick = { onOpenDetail(ShellDetail.FinalResults) },
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
                }
            }
        }
    }
}
