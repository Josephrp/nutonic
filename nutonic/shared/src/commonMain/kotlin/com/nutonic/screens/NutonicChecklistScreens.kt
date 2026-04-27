package com.nutonic.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.nutonic.navigation.ShellDetail
import com.nutonic.nutonicClientVersionLabel
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard
import com.nutonic.style.NutonicPrimaryButton

@Composable
fun ChecklistScreenChrome(
    title: String,
    supportText: String,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    extra: @Composable () -> Unit = {},
) {
    Column(
        modifier = modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.h5,
            color = MaterialTheme.colors.primary,
            fontWeight = FontWeight.Bold,
            textAlign = TextAlign.Center,
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = supportText,
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
            textAlign = TextAlign.Center,
        )
        extra()
        if (onBack != null) {
            Spacer(modifier = Modifier.height(24.dp))
            NutonicGhostButton(text = "Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
fun SplashScreen(
    onInitialize: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val version = nutonicClientVersionLabel()
    ChecklistScreenChrome(
        title = "NU:TONIC",
        supportText = "Initialize uplink and enter the SCAN shell.",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(24.dp))
            NutonicPrimaryButton(text = "Initialize", onClick = onInitialize, modifier = Modifier.fillMaxWidth())
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "System status: Ready",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "Client $version",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        },
    )
}

@Composable
fun RoleSelectionScreen(
    selectedRole: String?,
    onSelectRole: (String) -> Unit,
    onContinue: () -> Unit,
    onOpenOptionalAuth: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val protocolVersion = nutonicClientVersionLabel()
    val roles =
        remember {
            listOf(
                Triple("HUMAN", "Human", "Baseline SCAN pacing with familiar controls and assists."),
                Triple("ASTRONAUT", "Astronaut", "Balanced telemetry load - good for mixed recon and ranked warmups."),
                Triple("ALIEN", "Alien", "Aggressive assist cadence for players who want faster hint unlocks."),
            )
        }
    ChecklistScreenChrome(
        title = "Choose your role",
        supportText = "Pick the protocol identity for this session.",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(12.dp))
            roles.forEach { (id, title, perk) ->
                NutonicGlassCard(
                    modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp),
                ) {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.subtitle1,
                        color = MaterialTheme.colors.primary,
                    )
                    Text(
                        text = perk,
                        style = MaterialTheme.typography.body2,
                        color = MaterialTheme.colors.onBackground,
                        modifier = Modifier.padding(top = 6.dp, bottom = 10.dp),
                    )
                    if (selectedRole == id) {
                        NutonicPrimaryButton(
                            text = "Selected",
                            onClick = {},
                            enabled = false,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    } else {
                        NutonicGhostButton(
                            text = "Choose $title",
                            onClick = { onSelectRole(id) },
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(8.dp))
            NutonicPrimaryButton(
                text = "Continue",
                onClick = onContinue,
                enabled = selectedRole != null,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(modifier = Modifier.height(8.dp))
            NutonicGhostButton(
                text = "Sign in (optional)",
                onClick = onOpenOptionalAuth,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "Protocol version: $protocolVersion",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        },
    )
}

/** Human / Astronaut / Alien picker for compact surfaces (e.g. SETUP tab). */
@Composable
fun GameRolePicker(
    selectedRole: String?,
    onSelectRole: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("HUMAN" to "Human", "ASTRONAUT" to "Astronaut", "ALIEN" to "Alien").forEach { (id, label) ->
            val sel = selectedRole == id
            if (sel) {
                NutonicPrimaryButton(
                    text = "[Selected] $label",
                    onClick = { onSelectRole(id) },
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                NutonicGhostButton(
                    text = label,
                    onClick = { onSelectRole(id) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

@Composable
fun AuthenticationScreen(
    onSkip: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var identity by remember { mutableStateOf("") }
    var credential by remember { mutableStateOf("") }
    var statusLine by remember { mutableStateOf("Offline-friendly mode: sign-in is optional.") }
    ChecklistScreenChrome(
        title = "Authentication",
        supportText = "Sign in to sync identity-backed features, or skip for local-first SCAN play.",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(16.dp))
            OutlinedTextField(
                value = identity,
                onValueChange = { identity = it },
                label = { Text("Identity (email or handle)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(modifier = Modifier.height(8.dp))
            OutlinedTextField(
                value = credential,
                onValueChange = { credential = it },
                label = { Text("Credential token (optional)") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(modifier = Modifier.height(10.dp))
            Text(
                text = statusLine,
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
            Spacer(modifier = Modifier.height(10.dp))
            NutonicPrimaryButton(
                text = "Continue",
                onClick = {
                    statusLine =
                        if (identity.isBlank()) {
                            "Continuing without account sign-in."
                        } else {
                            "Identity saved for this session."
                        }
                    onSkip()
                },
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(modifier = Modifier.height(8.dp))
            TextButton(
                onClick = onSkip,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Skip for now")
            }
        },
    )
}

@Composable
fun ShellDetailScreen(
    detail: ShellDetail,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    /** Final results → RANK with map context. */
    onNavigateToRankForMap: ((String) -> Unit)? = null,
    rankNavigationMapId: String = "demo",
    /** Last persisted non-ranked row for this map. */
    lastRoundSummary: String? = null,
) {
    val (title, ref) = detailMeta(detail)
    ChecklistScreenChrome(
        title = title,
        supportText = ref,
        modifier = modifier,
        onBack = onBack,
        extra = {
            if (detail == ShellDetail.FinalResults) {
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = "Round recap",
                    style = MaterialTheme.typography.subtitle1,
                    color = MaterialTheme.colors.primary,
                )
                Text(
                    text = "Distance, score, and AI vs truth for your last run on this map.",
                    style = MaterialTheme.typography.body2,
                    color = MaterialTheme.colors.onBackground,
                    modifier = Modifier.padding(top = 6.dp),
                )
                if (lastRoundSummary != null) {
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = lastRoundSummary,
                        style = MaterialTheme.typography.body2,
                        color = MaterialTheme.colors.onBackground,
                    )
                }
            }
            if (detail == ShellDetail.FinalResults && onNavigateToRankForMap != null) {
                Spacer(modifier = Modifier.height(24.dp))
                NutonicPrimaryButton(
                    text = "Open rankings for this map",
                    onClick = { onNavigateToRankForMap(rankNavigationMapId) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
    )
}

private fun detailMeta(detail: ShellDetail): Pair<String, String> =
    when (detail) {
        ShellDetail.WorldMapGameplay -> "World map gameplay" to "Map, still clue, assists, and one primary submit."
        ShellDetail.FinalResults -> "Final results" to "Mission summary, progression, and rank handoff."
        ShellDetail.IntelDashboard -> "INTEL dashboard" to "Session progress, XP lane, and daily protocol status."
        ShellDetail.RankGlobal -> "RANK · global + map pick" to "Browse map-scoped and global rank slices."
        ShellDetail.SetupProtocol -> "SETUP · protocol" to "Profile, accessibility, and audio protocol controls."
        ShellDetail.ProCoordinateDashboard -> "PRO · coordinate dashboard" to "Advanced coordinate tooling and VLM surfaces."
        ShellDetail.ProFireWatch -> "PRO · FireWatch" to "Wildfire risk, burn/change overlays, hotspots, and brief handoff."
        ShellDetail.ProOceanScout -> "PRO · OceanScout" to "Coastal activity, vessel candidates, heatmaps, and evidence labels."
        ShellDetail.ProLandShift -> "PRO · LandShift" to "Land-cover transitions, top changes, overlays, and transition matrix."
        ShellDetail.ProFloodPulse -> "PRO · FloodPulse" to "Flood extent, affected-area metrics, and before/after review."
        ShellDetail.ProBriefComposer -> "PRO · brief composer" to "Structured multi-source brief composition and export handoff."
    }
