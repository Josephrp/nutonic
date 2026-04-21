package com.nutonic.shell

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import com.nutonic.api.FeatureFlags
import com.nutonic.api.MapSummary
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.RankedRoundStartIn
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.leaderboard.GuessRecordOutboxRepository
import com.nutonic.navigation.ShellDetail
import com.nutonic.screens.CommunityLeaderboardPanel
import com.nutonic.screens.RankedPlaySession
import com.nutonic.style.NutonicColors
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard
import com.nutonic.style.NutonicPrimaryButton
import kotlinx.coroutines.launch

@Composable
fun ScanHubScreen(
    onOpenDetail: (ShellDetail) -> Unit,
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
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
            text = "Choose mission, map, and rank context before launch.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        NutonicGlassCard(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        ) {
            Text(
                text = "Mission selection",
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
                val title = if (selected) "✓ ${mission.title}" else mission.title
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
                text = "Selected mission: ${selectedMission.title}",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        }

        if (nutonicApiClient == null) {
            Text(
                "Connect the game client on this host to load the live map list (bundled maps still work offline).",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        } else {
            NutonicGlassCard(
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            ) {
                manifestLine?.let { line ->
                    Text(
                        line,
                        style = MaterialTheme.typography.caption,
                        color = MaterialTheme.colors.onBackground,
                        modifier = Modifier.padding(bottom = 8.dp),
                    )
                }
                Text(
                    "Map / level selection",
                    style = MaterialTheme.typography.subtitle1,
                    color = MaterialTheme.colors.primary,
                )
                NutonicGhostButton(
                    text = "Refresh map list from server",
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
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
                mapsStatus?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.body2,
                        color = MaterialTheme.colors.error,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
                if (maps.isNotEmpty()) {
                    Text(
                        "Tap a map to set SCAN play context and the leaderboard preview.",
                        style = MaterialTheme.typography.caption,
                        color = MaterialTheme.colors.onBackground,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                    maps.forEach { m ->
                        val selected = m.mapId == mapContextId
                        Card(
                            modifier =
                                Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 6.dp)
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
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 14.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = m.title,
                                        style = MaterialTheme.typography.subtitle2,
                                        color = MaterialTheme.colors.primary,
                                    )
                                    Text(
                                        text =
                                            buildString {
                                                append("Map ")
                                                append(m.mapId)
                                                m.engineVersion?.let { ev -> append(" · engine ").append(ev) }
                                            },
                                        style = MaterialTheme.typography.caption,
                                        color = MaterialTheme.colors.onBackground,
                                    )
                                }
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = "›",
                                    style = MaterialTheme.typography.h6,
                                    color = MaterialTheme.colors.primary,
                                )
                            }
                        }
                    }
                    Text(
                        text = "Play entry",
                        style = MaterialTheme.typography.subtitle1,
                        color = MaterialTheme.colors.primary,
                        modifier = Modifier.padding(top = 12.dp),
                    )
                    NutonicPrimaryButton(
                        text = "Play selected mission on map",
                        onClick = {
                            onClearRankedSession()
                            onOpenDetail(ShellDetail.WorldMapGameplay)
                        },
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
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
                        )
                    }
                    NutonicGhostButton(
                        text = "Open final results preview",
                        onClick = { onOpenDetail(ShellDetail.FinalResults) },
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
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
