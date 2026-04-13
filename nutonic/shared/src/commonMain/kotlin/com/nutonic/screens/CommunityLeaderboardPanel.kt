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
 * Shared community / lab leaderboard surface for **map-scoped** `GET`/`POST` (`rules/05`, `IMP-071`).
 * Reused from RANK and SCAN so map hub and global tab stay aligned on dimensions and copy.
 */
@Composable
fun CommunityLeaderboardPanel(
    nutonicApiClient: NutonicApiClient,
    mapId: String,
    onMapIdChange: ((String) -> Unit)?,
    featureFlags: FeatureFlags?,
    sectionTitle: String,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<CommunityLeaderboardRow>>(emptyList()) }
    var status by remember { mutableStateOf<String?>(null) }
    var lastFetched by remember { mutableStateOf<Instant?>(null) }
    var lastDebug by remember { mutableStateOf<String?>(null) }

    val getEnabled = featureFlags?.communityLbGet != false
    val postEnabled = featureFlags?.communityLbPost != false

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
        CommunityLeaderboardDebugSessionButton(
            scope = scope,
            nutonicApiClient = nutonicApiClient,
            onResult = {
                lastDebug = it.lastDebug
                status = it.status
            },
        )
        CommunityLeaderboardPostButton(
            scope = scope,
            nutonicApiClient = nutonicApiClient,
            mapId = mapId,
            postEnabled = postEnabled,
            onResult = { status = it },
        )
        CommunityLeaderboardPanelFooter(
            lastFetched = lastFetched,
            lastDebug = lastDebug,
            status = status,
            rows = rows,
        )
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
            "Presentation-only aggregate when the server enables it " +
                "(`rules/05`; not ranked verification).",
        style = MaterialTheme.typography.caption,
        color = MaterialTheme.colors.onBackground,
    )
    if (featureFlags != null && (!getEnabled || !postEnabled)) {
        Text(
            text =
                buildString {
                    append("Server flags: ")
                    append("GET=${featureFlags.communityLbGet}, ")
                    append("POST=${featureFlags.communityLbPost}.")
                },
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
    }
    if (onMapIdChange != null) {
        OutlinedTextField(
            value = mapId,
            onValueChange = onMapIdChange,
            label = { Text("map_id (GET/POST path)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
    } else {
        Text(
            text = "map_id: $mapId",
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
                onResult(GetLeaderboardUiResult(emptyList(), null, "Fetching community leaderboard…"))
                when (val r = nutonicApiClient.getLeaderboard(mapId)) {
                    is ApiResult.Ok ->
                        onResult(GetLeaderboardUiResult(r.value, Clock.System.now(), null))

                    is ApiResult.HttpFailure ->
                        onResult(GetLeaderboardUiResult(emptyList(), null, r.userMessage))

                    is ApiResult.NetworkFailure ->
                        onResult(GetLeaderboardUiResult(emptyList(), null, "Network: ${r.debugMessage}"))
                }
            }
        },
        enabled = getEnabled,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text("GET community leaderboard")
    }
}

private data class DebugSessionUiResult(
    val lastDebug: String?,
    val status: String?,
)

@Composable
private fun CommunityLeaderboardDebugSessionButton(
    scope: CoroutineScope,
    nutonicApiClient: NutonicApiClient,
    onResult: (DebugSessionUiResult) -> Unit,
) {
    Button(
        onClick = {
            scope.launch {
                onResult(DebugSessionUiResult(null, "Issuing token…"))
                when (val t = nutonicApiClient.postAuthToken()) {
                    is ApiResult.Ok -> {
                        when (val d = nutonicApiClient.getDebugSession(t.value.accessToken)) {
                            is ApiResult.Ok ->
                                onResult(
                                    DebugSessionUiResult(
                                        "debug/session ok · session_id=${d.value.sessionId}",
                                        null,
                                    ),
                                )

                            is ApiResult.HttpFailure ->
                                onResult(DebugSessionUiResult(null, d.userMessage))

                            is ApiResult.NetworkFailure ->
                                onResult(DebugSessionUiResult(null, "Network: ${d.debugMessage}"))
                        }
                    }

                    is ApiResult.HttpFailure -> onResult(DebugSessionUiResult(null, t.userMessage))
                    is ApiResult.NetworkFailure ->
                        onResult(DebugSessionUiResult(null, "Network: ${t.debugMessage}"))
                }
            }
        },
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text("POST /auth/token then GET /debug/session")
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
                onResult("POST leaderboard row…")
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
                            is ApiResult.NetworkFailure -> onResult("Network: ${p.debugMessage}")
                        }
                    }

                    is ApiResult.HttpFailure -> onResult(t.userMessage)
                    is ApiResult.NetworkFailure -> onResult("Network: ${t.debugMessage}")
                }
            }
        },
        enabled = postEnabled,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text("POST lab leaderboard row (JWT + Idempotency-Key)")
    }
}

@Composable
private fun CommunityLeaderboardPanelFooter(
    lastFetched: Instant?,
    lastDebug: String?,
    status: String?,
    rows: List<CommunityLeaderboardRow>,
) {
    lastFetched?.let {
        Text(
            "Last GET (UTC): $it",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
    }
    lastDebug?.let {
        Text(
            it,
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
