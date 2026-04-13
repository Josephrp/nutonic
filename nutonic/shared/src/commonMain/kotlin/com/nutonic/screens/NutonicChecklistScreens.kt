package com.nutonic.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.Button
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.nutonic.navigation.ShellDetail

@Composable
fun ChecklistScreenChrome(
    title: String,
    checklistRef: String,
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
            text = checklistRef,
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
            textAlign = TextAlign.Center,
        )
        extra()
        if (onBack != null) {
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onBack) { Text("Back") }
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
        checklistRef = "Splash — rules/07 #1 · `music_splash`",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onInitialize) { Text("Initialize") }
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
        checklistRef = "Role selection — rules/07 #3 · Human / Astronaut / Alien",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(16.dp))
            GameRolePicker(selectedRole = selectedRole, onSelectRole = onSelectRole)
            Spacer(modifier = Modifier.height(16.dp))
            Button(
                onClick = onContinue,
                enabled = selectedRole != null,
            ) {
                Text("Continue")
            }
            Spacer(modifier = Modifier.height(8.dp))
            Button(onClick = onOpenOptionalAuth) {
                Text("Sign in (optional)")
            }
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
            Button(onClick = { onSelectRole(id) }) {
                Text(if (sel) "★ $label" else label)
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
        checklistRef = "rules/07 #2 · skippable optional path",
        modifier = modifier,
        onBack = null,
        extra = {
            Spacer(modifier = Modifier.height(24.dp))
            Button(onClick = onSkip) { Text("Skip for now") }
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
        checklistRef = ref,
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
                Button(onClick = { onNavigateToRankForMap(rankNavigationMapId) }) {
                    Text("Open RANK for map: $rankNavigationMapId")
                }
            }
        },
    )
}

private fun detailMeta(detail: ShellDetail): Pair<String, String> =
    when (detail) {
        ShellDetail.MissionSelection -> "Mission selection" to "rules/07 #4c · SCAN hub"
        ShellDetail.MapLevelSelection -> "Map / level selection" to "rules/07 #4b · `map_id`"
        ShellDetail.WorldMapGameplay -> "World map gameplay" to "rules/07 #5"
        ShellDetail.SuccessOverlay -> "Success overlay" to "rules/07 #6"
        ShellDetail.FinalResults -> "Final results" to "rules/07 #7 · deep-link to RANK"
        ShellDetail.IntelDashboard -> "INTEL dashboard" to "rules/07 #4"
        ShellDetail.RankGlobal -> "RANK · global + map pick" to "rules/07 · RANK tab"
        ShellDetail.SetupProtocol -> "SETUP · protocol" to "rules/07 #8"
        ShellDetail.ProCoordinateDashboard -> "PRO · coordinate dashboard" to "rules/07 #9 · VLM tools"
    }
