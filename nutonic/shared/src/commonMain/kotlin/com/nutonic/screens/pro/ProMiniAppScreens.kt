package com.nutonic.screens.pro

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard

@Composable
fun ProFireWatchScreen(onBack: () -> Unit) {
    ProMiniAppScreen(
        title = "FireWatch",
        summary = "Wildfire and burn-change review for temporal Sentinel/TiM outputs.",
        sections =
            listOf(
                "Burn/change overlay",
                "Hotspot ranking",
                "Send findings to Brief Composer",
            ),
        onBack = onBack,
    )
}

@Composable
fun ProOceanScoutScreen(onBack: () -> Unit) {
    ProMiniAppScreen(
        title = "OceanScout",
        summary = "Candidate vessel review with coverage-normalized maritime activity indicators.",
        sections =
            listOf(
                "Base optical detections in green",
                "TiM-enhanced candidates in blue",
                "Observation coverage and claim-safety notices",
            ),
        onBack = onBack,
    )
}

@Composable
fun ProLandShiftScreen(onBack: () -> Unit) {
    ProMiniAppScreen(
        title = "LandShift",
        summary = "Land use / land cover transition review across temporal windows.",
        sections = listOf("Transition matrix", "Top transitions", "Change hotspots"),
        onBack = onBack,
    )
}

@Composable
fun ProFloodPulseScreen(onBack: () -> Unit) {
    ProMiniAppScreen(
        title = "FloodPulse",
        summary = "Water expansion and affected-area review for flood-sensitive profiles.",
        sections = listOf("Before/after water extent", "Inundation polygons", "Affected area export"),
        onBack = onBack,
    )
}

@Composable
fun ProBriefComposerScreen(onBack: () -> Unit) {
    ProMiniAppScreen(
        title = "Brief Composer",
        summary = "Cross-mini-app synthesis with confidence-aware sections and source toggles.",
        sections = listOf("Executive summary", "Key findings", "Recommended actions"),
        onBack = onBack,
    )
}

@Composable
private fun ProMiniAppScreen(
    title: String,
    summary: String,
    sections: List<String>,
    onBack: () -> Unit,
) {
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        NutonicGhostButton(text = "Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
        Text(title, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(summary, style = MaterialTheme.typography.body2)
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Panels", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            sections.forEach { section ->
                Text("• $section", style = MaterialTheme.typography.body2)
            }
        }
        Text(
            "Artifact-backed rendering will populate this screen from the selected PRO job bundle.",
            style = MaterialTheme.typography.caption,
        )
    }
}
