package com.nutonic.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Card
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.nutonic.api.GuessRecordOut
import com.nutonic.api.RankedSubmitOut
import com.nutonic.filter.PlatformContext
import com.nutonic.share.shareNutonicScorecard
import com.nutonic.style.nutonicOnSurfaceMuted
import kotlinx.coroutines.launch

private sealed interface ShareScorecardState {
    data object Idle : ShareScorecardState

    data object Loading : ShareScorecardState

    data class Completed(
        val message: String,
        val success: Boolean,
    ) : ShareScorecardState
}

@Composable
internal fun RoundSuccessOverlay(
    mapId: String,
    mapTitle: String?,
    locationId: String,
    operatorDisplayName: String,
    scorePoints: Int?,
    distanceKm: Double?,
    aiDistanceToTruthKm: Double?,
    rankedOutcome: RankedSubmitOut?,
    serverVerified: Boolean,
    telemetryAck: GuessRecordOut?,
    syncStatusLine: String?,
    platformContext: PlatformContext,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    var shareState by remember { mutableStateOf<ShareScorecardState>(ShareScorecardState.Idle) }
    Card(
        modifier = modifier,
        backgroundColor = MaterialTheme.colors.surface.copy(alpha = 0.95f),
        elevation = 8.dp,
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Round complete", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(
                text = "Operator: $operatorDisplayName",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
            Text(
                text =
                    buildString {
                        append("Map ")
                        append(mapId)
                        mapTitle?.takeIf { it.isNotBlank() }?.let { append(" · ").append(it) }
                    },
                style = MaterialTheme.typography.caption,
                color = nutonicOnSurfaceMuted(alpha = 0.85f),
            )
            Text("Location $locationId", style = MaterialTheme.typography.caption, color = nutonicOnSurfaceMuted())
            if (serverVerified && rankedOutcome != null) {
                Text(
                    "Ranked · server-verified · ${rankedOutcome.scorePoints} pts · ${rankedOutcome.distanceKm.format(2)} km",
                    style = MaterialTheme.typography.body2,
                    color = MaterialTheme.colors.secondary,
                )
            }
            val resolvedPts = telemetryAck?.scorePoints ?: scorePoints
            val resolvedKm = telemetryAck?.distanceKm ?: distanceKm
            if (!serverVerified && resolvedPts != null && resolvedKm != null) {
                Text(
                    "$resolvedPts pts · ${resolvedKm.format(2)} km from local manifest truth",
                    style = MaterialTheme.typography.body2,
                    color = MaterialTheme.colors.onBackground,
                )
            }
            aiDistanceToTruthKm?.let { aiKm ->
                Text(
                    "AI marker vs truth: ${aiKm.format(2)} km (comparison only)",
                    style = MaterialTheme.typography.caption,
                    color = nutonicOnSurfaceMuted(alpha = 0.9f),
                )
            }
            telemetryAck?.let { ack ->
                Text(
                    buildString {
                        append("Telemetry row #${ack.id}")
                        ack.displayHandle?.takeIf { it.isNotBlank() }?.let { h -> append(" · ").append(h) }
                    },
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.secondary,
                )
            }
            syncStatusLine?.takeIf { it.isNotBlank() }?.let { line ->
                Text(line, style = MaterialTheme.typography.caption, color = MaterialTheme.colors.onBackground)
            }
            when (val state = shareState) {
                ShareScorecardState.Idle -> Unit
                ShareScorecardState.Loading ->
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(modifier = Modifier.width(14.dp).height(14.dp), strokeWidth = 2.dp)
                        Text(
                            "Preparing share options…",
                            style = MaterialTheme.typography.caption,
                            color = MaterialTheme.colors.secondary,
                        )
                    }

                is ShareScorecardState.Completed ->
                    Text(
                        state.message,
                        style = MaterialTheme.typography.caption,
                        color = if (state.success) MaterialTheme.colors.secondary else MaterialTheme.colors.error,
                    )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    modifier = Modifier.testTag("worldMapShareScoreStub"),
                    enabled = shareState !is ShareScorecardState.Loading,
                    onClick = {
                        shareState = ShareScorecardState.Loading
                        scope.launch {
                            val body =
                                buildString {
                                    appendLine("NU:TONIC scorecard")
                                    append("Operator: ").appendLine(operatorDisplayName)
                                    append("Map: ").appendLine(mapId)
                                    mapTitle?.takeIf { it.isNotBlank() }?.let { append("Title: ").appendLine(it) }
                                    append("Location: ").appendLine(locationId)
                                    val pts = telemetryAck?.scorePoints ?: scorePoints
                                    val km = telemetryAck?.distanceKm ?: distanceKm
                                    if (pts != null && km != null) {
                                        appendLine("$pts pts · ${km.format(2)} km from truth")
                                    }
                                    aiDistanceToTruthKm?.let {
                                        appendLine("AI vs truth: ${it.format(2)} km")
                                    }
                                    if (serverVerified) {
                                        appendLine("Mode: ranked (server-verified)")
                                    } else {
                                        appendLine("Mode: non-ranked (local truth)")
                                    }
                                    telemetryAck?.let { appendLine("Telemetry id: ${it.id}") }
                                }
                            val ok = shareNutonicScorecard(platformContext, body.trim())
                            shareState =
                                if (ok) {
                                    ShareScorecardState.Completed(
                                        message = "Share options opened or clipboard updated.",
                                        success = true,
                                    )
                                } else {
                                    ShareScorecardState.Completed(
                                        message = "Sharing unavailable on this device right now.",
                                        success = false,
                                    )
                                }
                        }
                    },
                ) {
                    Text("Share scorecard")
                }
                TextButton(modifier = Modifier.testTag("worldMapSuccessDismissButton"), onClick = onDismiss) {
                    Text("Dismiss")
                }
            }
        }
    }
}
