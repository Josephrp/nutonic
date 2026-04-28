package com.nutonic.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.Button
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.nutonic.api.ApiResult
import com.nutonic.api.CommunityLeaderboardPostBody
import com.nutonic.api.CommunityLeaderboardRow
import com.nutonic.api.FeatureFlags
import com.nutonic.api.NutonicApiClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.datetime.Clock
import kotlinx.datetime.Instant

/**
 * Shared community / lab leaderboard surface for map-scoped fetch and optional demo posts.
 * Reused from RANK and SCAN so map hub and global tab stay aligned on dimensions and copy.
 */
@Composable
fun CommunityLeaderboardPanel(
    nutonicApiClient: NutonicApiClient,
    mapId: String,
    onMapIdChange: ((String) -> Unit)?,
    featureFlags: FeatureFlags?,
    sectionTitle: String,
    /** When server `features.ranked` is on, show **GET …?tier=ranked** (RANK / SCAN follow-up). */
    showRankedVerifiedFetch: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<CommunityLeaderboardRow>>(emptyList()) }
    var rankedRows by remember { mutableStateOf<List<CommunityLeaderboardRow>>(emptyList()) }
    var status by remember { mutableStateOf<String?>(null) }
    var rankedStatus by remember { mutableStateOf<String?>(null) }
    var lastFetched by remember { mutableStateOf<Instant?>(null) }
    var rankedFetched by remember { mutableStateOf<Instant?>(null) }

    val getEnabled = featureFlags?.communityLbGet != false
    val postEnabled = featureFlags?.communityLbPost != false
    val rankedFetchEnabled = showRankedVerifiedFetch && featureFlags?.ranked == true

    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        CommunityLeaderboardPanelIntro(
            sectionTitle = sectionTitle,
            featureFlags = featureFlags,
            getEnabled = getEnabled,
            postEnabled = postEnabled,
            mapId = mapId,
            onMapIdChange = onMapIdChange,
        )
        CommunityLeaderboardGetButton(
            scope = scope,
            nutonicApiClient = nutonicApiClient,
            mapId = mapId,
            getEnabled = getEnabled,
            onResult = {
                rows = it.rows
                lastFetched = it.lastFetched
                status = it.status
            },
        )
        if (showRankedVerifiedFetch) {
            CommunityLeaderboardRankedTierFetchButton(
                scope = scope,
                nutonicApiClient = nutonicApiClient,
                mapId = mapId,
                rankedFetchEnabled = rankedFetchEnabled,
                onResult = {
                    rankedRows = it.rows
                    rankedFetched = it.lastFetched
                    rankedStatus = it.status
                },
            )
        }
        CommunityLeaderboardPostButton(
            scope = scope,
            nutonicApiClient = nutonicApiClient,
            mapId = mapId,
            postEnabled = postEnabled,
            onResult = { status = it },
        )
        CommunityLeaderboardPanelFooter(
            lastFetched = lastFetched,
            status = status,
            rows = rows,
        )
        if (showRankedVerifiedFetch) {
            Text(
                text = "Server-verified ranked leaderboard",
                style = MaterialTheme.typography.subtitle2,
                color = MaterialTheme.colors.primary,
            )
            CommunityLeaderboardPanelFooter(
                lastFetched = rankedFetched,
                status = rankedStatus,
                rows = rankedRows,
            )
        }
    }
}

@Composable
private fun CommunityLeaderboardPanelIntro(
    sectionTitle: String,
    featureFlags: FeatureFlags?,
    getEnabled: Boolean,
    postEnabled: Boolean,
    mapId: String,
    onMapIdChange: ((String) -> Unit)?,
) {
    Text(
        text = sectionTitle,
        style = MaterialTheme.typography.subtitle1,
        color = MaterialTheme.colors.primary,
    )
    Text(
        text =
            "Community scores are optional lab aggregates when the host enables them; " +
                "they are not server-verified ranked results.",
        style = MaterialTheme.typography.caption,
        color = MaterialTheme.colors.onBackground,
    )
    if (featureFlags != null && (!getEnabled || !postEnabled)) {
        Text(
            text = "Some community score features are disabled on this server.",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
    }
    if (onMapIdChange != null) {
        OutlinedTextField(
            value = mapId,
            onValueChange = onMapIdChange,
            label = { Text("Map id") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
    } else {
        Text(
            text = "Map: $mapId",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
    }
}

private data class GetLeaderboardUiResult(
    val rows: List<CommunityLeaderboardRow>,
    val lastFetched: Instant?,
    val status: String?,
)

@Composable
private fun CommunityLeaderboardGetButton(
    scope: CoroutineScope,
    nutonicApiClient: NutonicApiClient,
    mapId: String,
    getEnabled: Boolean,
    onResult: (GetLeaderboardUiResult) -> Unit,
) {
    Button(
        onClick = {
            scope.launch {
                onResult(GetLeaderboardUiResult(emptyList(), null, "Fetching community leaderboard..."))
                when (val r = nutonicApiClient.getLeaderboard(mapId)) {
                    is ApiResult.Ok ->
                        onResult(GetLeaderboardUiResult(r.value, Clock.System.now(), null))

                    is ApiResult.HttpFailure ->
                        onResult(GetLeaderboardUiResult(emptyList(), null, r.userMessage))

                    is ApiResult.NetworkFailure ->
                        onResult(GetLeaderboardUiResult(emptyList(), null, "Network unavailable. Try again when online."))
                }
            }
        },
        enabled = getEnabled,
        modifier =
            Modifier
                .fillMaxWidth()
                .testTag("communityLeaderboardFetchButton"),
    ) {
        Text("Refresh community scores")
    }
}

@Composable
private fun CommunityLeaderboardRankedTierFetchButton(
    scope: CoroutineScope,
    nutonicApiClient: NutonicApiClient,
    mapId: String,
    rankedFetchEnabled: Boolean,
    onResult: (GetLeaderboardUiResult) -> Unit,
) {
    Button(
        onClick = {
            scope.launch {
                onResult(GetLeaderboardUiResult(emptyList(), null, "Fetching server-verified ranked leaderboard..."))
                when (val r = nutonicApiClient.getLeaderboard(mapId, tier = "ranked")) {
                    is ApiResult.Ok ->
                        onResult(GetLeaderboardUiResult(r.value, Clock.System.now(), null))

                    is ApiResult.HttpFailure ->
                        onResult(GetLeaderboardUiResult(emptyList(), null, r.userMessage))

                    is ApiResult.NetworkFailure ->
                        onResult(GetLeaderboardUiResult(emptyList(), null, "Network unavailable. Try again when online."))
                }
            }
        },
        enabled = rankedFetchEnabled,
        modifier =
            Modifier
                .fillMaxWidth()
                .testTag("rankedLeaderboardTierFetchButton"),
    ) {
        Text("Refresh ranked leaderboard")
    }
}

@Composable
private fun CommunityLeaderboardPostButton(
    scope: CoroutineScope,
    nutonicApiClient: NutonicApiClient,
    mapId: String,
    postEnabled: Boolean,
    onResult: (String?) -> Unit,
) {
    Button(
        onClick = {
            scope.launch {
                onResult("Sending demo score...")
                when (val t = nutonicApiClient.postAuthToken()) {
                    is ApiResult.Ok -> {
                        val key = "kmp-${Clock.System.now()}"
                        val body =
                            CommunityLeaderboardPostBody(
                                displayHandle = "kmp_client",
                                playerRole = "HUMAN",
                                scorePoints = 42,
                                distanceKm = 1.25,
                            )
                        when (
                            val p =
                                nutonicApiClient.postLeaderboard(
                                    mapId = mapId,
                                    body = body,
                                    bearerAccessToken = t.value.accessToken,
                                    idempotencyKey = key,
                                )
                        ) {
                            is ApiResult.Ok ->
                                onResult("Posted row for $mapId (${p.value.displayHandle})")

                            is ApiResult.HttpFailure -> onResult(p.userMessage)
                            is ApiResult.NetworkFailure -> onResult("Network unavailable. Could not send demo score.")
                        }
                    }

                    is ApiResult.HttpFailure -> onResult(t.userMessage)
                    is ApiResult.NetworkFailure -> onResult("Network unavailable. Sign-in token request failed.")
                }
            }
        },
        enabled = postEnabled,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text("Post demo score (signed in)")
    }
}

@Composable
private fun CommunityLeaderboardPanelFooter(
    lastFetched: Instant?,
    status: String?,
    rows: List<CommunityLeaderboardRow>,
) {
    lastFetched?.let {
        Text(
            "Last refresh (UTC): $it",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
    }
    status?.let {
        Text(
            it,
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.error,
        )
    }
    rows.forEach { row ->
        val distance =
            if (row.distanceKm != null) {
                " · ${row.distanceKm} km"
            } else {
                ""
            }
        Text(
            "${row.displayHandle} · ${row.playerRole} · ${row.scorePoints} pts$distance",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
    }
}
