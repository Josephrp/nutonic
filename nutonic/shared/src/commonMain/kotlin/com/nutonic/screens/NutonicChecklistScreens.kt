package com.nutonic.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.nutonic.navigation.ShellDetail
import com.nutonic.style.NutonicGhostButton
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
fun SplashScreenPlaceholder(
    onInitialize: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ChecklistScreenChrome(
        title = "NU:TONIC",
        supportText = "Initialize uplink and enter the SCAN shell.",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(24.dp))
            NutonicPrimaryButton(text = "Initialize", onClick = onInitialize, modifier = Modifier.fillMaxWidth())
        },
    )
}

@Composable
fun RoleSelectionScreenPlaceholder(
    selectedRole: String?,
    onSelectRole: (String) -> Unit,
    onContinue: () -> Unit,
    onOpenOptionalAuth: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ChecklistScreenChrome(
        title = "Choose your role",
        supportText = "Pick the protocol identity for this session.",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(16.dp))
            GameRolePicker(selectedRole = selectedRole, onSelectRole = onSelectRole)
            Spacer(modifier = Modifier.height(16.dp))
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
        },
    )
}

/** Human / Astronaut / Alien picker (`rules/01`, CLIENT-SETTINGS-SPEC §6.1). */
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
                    text = "★ $label",
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
fun AuthenticationScreenPlaceholder(
    onSkip: () -> Unit,
    modifier: Modifier = Modifier,
) {
    ChecklistScreenChrome(
        title = "Authentication",
        supportText = "Sign in is optional for casual SCAN play.",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(24.dp))
            NutonicPrimaryButton(text = "Skip for now", onClick = onSkip, modifier = Modifier.fillMaxWidth())
        },
    )
}

@Composable
fun ShellDetailPlaceholder(
    detail: ShellDetail,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    /** Final results → RANK + `map_id` (`IMP-071`, `rules/07` #7). */
    onNavigateToRankForMap: ((String) -> Unit)? = null,
    rankNavigationMapId: String = "demo",
    /** Last persisted non-ranked row for this map (`IMP-083` / `IMP-084`). */
    lastRoundSummary: String? = null,
) {
    val (title, ref) = detailMeta(detail)
    ChecklistScreenChrome(
        title = title,
        supportText = ref,
        modifier = modifier,
        onBack = onBack,
        extra = {
            if (detail == ShellDetail.FinalResults && lastRoundSummary != null) {
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = lastRoundSummary,
                    style = MaterialTheme.typography.body2,
                    color = MaterialTheme.colors.onBackground,
                )
            }
            if (detail == ShellDetail.FinalResults && onNavigateToRankForMap != null) {
                Spacer(modifier = Modifier.height(24.dp))
                NutonicPrimaryButton(
                    text = "Open RANK for map: $rankNavigationMapId",
                    onClick = { onNavigateToRankForMap(rankNavigationMapId) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
    )
}

private fun detailMeta(detail: ShellDetail): Pair<String, String> =
    when (detail) {
        ShellDetail.MissionSelection -> "Mission selection" to "Select a mission profile and launch from SCAN."
        ShellDetail.MapLevelSelection -> "Map / level selection" to "Select map context used by gameplay and ranks."
        ShellDetail.WorldMapGameplay -> "World map gameplay" to "Map, still clue, assists, and one primary submit."
        ShellDetail.SuccessOverlay -> "Success overlay" to "Round-complete summary before full results."
        ShellDetail.FinalResults -> "Final results" to "Mission summary, progression, and rank handoff."
        ShellDetail.IntelDashboard -> "INTEL dashboard" to "Session progress, XP lane, and daily protocol status."
        ShellDetail.RankGlobal -> "RANK · global + map pick" to "Browse map-scoped and global rank slices."
        ShellDetail.SetupProtocol -> "SETUP · protocol" to "Profile, accessibility, and audio protocol controls."
        ShellDetail.ProCoordinateDashboard -> "PRO · coordinate dashboard" to "Advanced coordinate tooling and VLM surfaces."
    }
