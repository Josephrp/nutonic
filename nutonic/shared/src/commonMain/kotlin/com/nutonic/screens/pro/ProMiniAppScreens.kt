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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.nutonic.api.ProArtifactRef
import com.nutonic.api.ProJobStatusOut
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard

@Composable
fun ProFireWatchScreen(
    job: ProJobStatusOut?,
    onBack: () -> Unit,
    onOpenBriefComposer: () -> Unit,
) {
    val artifacts = fireWatchArtifacts(job)
    val heatmap = artifacts.firstOrNull { it.artifactId == "firewatch_burn_change_heatmap" }
    val hotspots = artifacts.firstOrNull { it.artifactId == "firewatch_hotspots" }
    val hotspotsGeoJson = artifacts.firstOrNull { it.artifactId == "firewatch_hotspots_geojson" }
    val metrics = artifacts.firstOrNull { it.artifactId == "firewatch_metrics" }
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        NutonicGhostButton(text = "Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
        Text("FireWatch", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Wildfire and burn-change review for temporal Sentinel/TiM outputs.",
            style = MaterialTheme.typography.body2,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Selected PRO run", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            if (job == null) {
                Text(
                    "Open FireWatch from a completed wildfire PRO job to review burn/change artifacts.",
                    style = MaterialTheme.typography.body2,
                )
            } else {
                Text("${job.jobId.take(8)} · ${job.analysisProfile ?: job.profile.orEmpty()} · ${job.status}")
                job.sceneProvenance?.let {
                    Text("Scene provenance: ${it.toString().take(300)}", style = MaterialTheme.typography.caption)
                }
            }
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Burn/change overlay", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactLine("Heatmap PNG", heatmap)
            ArtifactLine("Hotspot GeoJSON", hotspotsGeoJson)
            Text(
                "The heatmap is derived from NBR(t0)-NBR(t1); high values indicate burn/change signals requiring source-scene review.",
                style = MaterialTheme.typography.caption,
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Hotspot ranking", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactLine("Hotspot list JSON", hotspots)
            ArtifactLine("Metrics JSON", metrics)
            if (hotspots == null) {
                Text("No hotspot artifact is attached to the selected job.", style = MaterialTheme.typography.caption)
            }
        MissingRequiredArtifacts(job)
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Brief handoff", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Send FireWatch artifacts and limitations into Brief Composer for confidence-aware synthesis.")
            NutonicGhostButton(
                text = "Open Brief Composer",
                onClick = onOpenBriefComposer,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }
    }
}

@Composable
fun ProOceanScoutScreen(
    job: ProJobStatusOut?,
    onBack: () -> Unit,
    onOpenBriefComposer: () -> Unit,
) {
    val artifacts = proArtifacts(job)
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        NutonicGhostButton(text = "Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
        Text("OceanScout", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Candidate vessel review with coverage-normalized maritime activity indicators.",
            style = MaterialTheme.typography.body2,
        )
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Selected PRO run", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            if (job == null) {
                Text("Open OceanScout from a completed maritime PRO job to review candidate artifacts.")
            } else {
                Text("${job.jobId.take(8)} · ${job.analysisProfile ?: job.profile.orEmpty()} · ${job.status}")
            }
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Compare overlays", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactLine("Vessel candidate GeoJSON", artifacts.firstOrNull { it.artifactId == "vessel_overlay" })
            ArtifactLine("Candidate list JSON", artifacts.firstOrNull { it.artifactId == "vessel_candidates" })
            Text(
                "Green/blue overlay semantics are encoded in the GeoJSON: base optical signals stay distinct from TiM-enhanced indicators.",
                style = MaterialTheme.typography.caption,
            )
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Coverage-normalized activity", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactLine("Lane heatmap PNG", artifacts.firstOrNull { it.artifactId == "lane_heatmap" })
            ArtifactLine("Observation coverage JSON", artifacts.firstOrNull { it.artifactId == "observation_coverage" })
            ArtifactLine("Incursion summary JSON", artifacts.firstOrNull { it.artifactId == "incursion_events" })
            Text(
                "OceanScout outputs are presence indicators only; coverage and cloud limits must be reviewed before claims.",
                style = MaterialTheme.typography.caption,
            )
            MissingRequiredArtifacts(job)
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Brief handoff", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            NutonicGhostButton(
                text = "Open Brief Composer",
                onClick = onOpenBriefComposer,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
fun ProLandShiftScreen(
    job: ProJobStatusOut?,
    onBack: () -> Unit,
    onOpenBriefComposer: () -> Unit,
) {
    val artifacts = proArtifacts(job)
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        NutonicGhostButton(text = "Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
        Text("LandShift", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text("Land use / land cover transition review across temporal windows.", style = MaterialTheme.typography.body2)
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Selected PRO run", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(job?.let { "${it.jobId.take(8)} · ${it.analysisProfile ?: it.profile.orEmpty()} · ${it.status}" } ?: "Open LandShift from a completed land-use PRO job.")
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Transitions", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactLine("Transition matrix JSON", artifacts.firstOrNull { it.artifactId == "land_transition_matrix" })
            ArtifactLine("Top transitions JSON", artifacts.firstOrNull { it.artifactId == "land_top_transitions" })
            ArtifactLine("Change heatmap PNG", artifacts.firstOrNull { it.artifactId == "land_change_heatmap" })
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Change hotspots", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactLine("Hotspot GeoJSON", artifacts.firstOrNull { it.artifactId == "land_change_hotspots" })
            Text("Transitions are proxy classes derived from temporal spectral changes and require source-scene review.", style = MaterialTheme.typography.caption)
            MissingRequiredArtifacts(job)
        }
        NutonicGhostButton("Open Brief Composer", onOpenBriefComposer, Modifier.fillMaxWidth())
    }
}

@Composable
fun ProFloodPulseScreen(
    job: ProJobStatusOut?,
    onBack: () -> Unit,
    onOpenBriefComposer: () -> Unit,
) {
    val artifacts = proArtifacts(job)
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        NutonicGhostButton(text = "Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
        Text("FloodPulse", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text("Water expansion and affected-area review for flood-sensitive profiles.", style = MaterialTheme.typography.body2)
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Selected PRO run", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(job?.let { "${it.jobId.take(8)} · ${it.analysisProfile ?: it.profile.orEmpty()} · ${it.status}" } ?: "Open FloodPulse from a completed flood PRO job.")
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Before / after water extent", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactLine("Before extent PNG", artifacts.firstOrNull { it.artifactId == "flood_before_water_extent" })
            ArtifactLine("After extent PNG", artifacts.firstOrNull { it.artifactId == "flood_after_water_extent" })
            ArtifactLine("Expansion heatmap PNG", artifacts.firstOrNull { it.artifactId == "flood_expansion_heatmap" })
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Affected area", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactLine("Water change metrics JSON", artifacts.firstOrNull { it.artifactId == "flood_water_change_metrics" })
            ArtifactLine("Inundation polygons GeoJSON", artifacts.firstOrNull { it.artifactId == "flood_inundation_polygons" })
            Text("FloodPulse polygons are decision-support geometry and should be reviewed against source scenes.", style = MaterialTheme.typography.caption)
            MissingRequiredArtifacts(job)
        }
        NutonicGhostButton("Open Brief Composer", onOpenBriefComposer, Modifier.fillMaxWidth())
    }
}

@Composable
fun ProBriefComposerScreen(
    job: ProJobStatusOut?,
    onBack: () -> Unit,
) {
    val artifacts = proArtifacts(job)
    var includeOverlays by remember { mutableStateOf(true) }
    var includeMetrics by remember { mutableStateOf(true) }
    var includeBrief by remember { mutableStateOf(true) }
    val selectedArtifacts =
        artifacts.filter { artifact ->
            (includeOverlays && (artifact.kind == "geojson" || artifact.kind == "image")) ||
                (includeMetrics && artifact.kind == "json") ||
                (includeBrief && artifact.kind == "brief")
        }
    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        NutonicGhostButton(text = "Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
        Text("Brief Composer", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text("Cross-mini-app synthesis with confidence-aware sections and source toggles.", style = MaterialTheme.typography.body2)
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Selected PRO run", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text(job?.let { "${it.jobId.take(8)} · ${it.analysisProfile ?: it.profile.orEmpty()} · ${it.status}" } ?: "Open Brief Composer from a completed PRO job.")
            Text("Confidence: ${job?.onDevicePayload?.confidenceSummary ?: "not available"}", style = MaterialTheme.typography.caption)
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Source toggles", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            SourceToggle("Overlays and map images", includeOverlays) { includeOverlays = !includeOverlays }
            SourceToggle("Metrics and artifact indexes", includeMetrics) { includeMetrics = !includeMetrics }
            SourceToggle("Generated brief summary", includeBrief) { includeBrief = !includeBrief }
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Brief sections", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            val sections = job?.onDevicePayload?.briefSections.orEmpty()
            if (sections.isEmpty()) {
                Text("No on-device brief sections are attached yet.", style = MaterialTheme.typography.caption)
            } else {
                sections.forEach { section ->
                    Text("${section.title}: ${section.body}", style = MaterialTheme.typography.body2)
                    section.confidence?.let { Text("Confidence: $it", style = MaterialTheme.typography.caption) }
                }
            }
        }
        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Export / share draft", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Selected sources: ${selectedArtifacts.size}", style = MaterialTheme.typography.body2)
            selectedArtifacts.take(10).forEach { artifact ->
                Text("${artifact.artifactId} · ${artifact.kind} · ${artifact.downloadUrl.orEmpty()}", style = MaterialTheme.typography.caption)
            }
            if (selectedArtifacts.size > 10) {
                Text("+${selectedArtifacts.size - 10} more sources", style = MaterialTheme.typography.caption)
            }
        }
    }
}

@Composable
private fun ArtifactLine(
    label: String,
    artifact: ProArtifactRef?,
) {
    if (artifact == null) {
        Text("$label: not attached", style = MaterialTheme.typography.caption)
    } else {
        Text(
            "$label: ${artifact.artifactId} · ${artifact.kind} · ${artifact.downloadUrl.orEmpty()}",
            style = MaterialTheme.typography.body2,
        )
    }
}

@Composable
private fun SourceToggle(
    label: String,
    enabled: Boolean,
    onToggle: () -> Unit,
) {
    NutonicGhostButton(
        text = "${if (enabled) "Included" else "Excluded"} · $label",
        onClick = onToggle,
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
    )
}

private fun fireWatchArtifacts(job: ProJobStatusOut?): List<ProArtifactRef> = proArtifacts(job)

@Composable
private fun MissingRequiredArtifacts(job: ProJobStatusOut?) {
    val expected = expectedRequiredArtifactIds(job?.analysisProfile ?: job?.profile)
    if (expected.isEmpty() || job?.status != "completed") {
        return
    }
    val present =
        proArtifacts(job)
            .filter { it.requiredForProfile }
            .map { it.artifactId }
            .toSet()
    val missing = expected.filterNot { it in present }
    if (missing.isNotEmpty()) {
        Text(
            "Missing required profile artifacts: ${missing.joinToString()}",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.error,
        )
    }
}

private fun expectedRequiredArtifactIds(profile: String?): List<String> =
    when (profile) {
        "wildfire" ->
            listOf("firewatch_burn_change_heatmap", "firewatch_hotspots", "firewatch_hotspots_geojson", "firewatch_metrics")
        "oceanscout_ship_detection" ->
            listOf("vessel_overlay", "vessel_candidates", "lane_heatmap", "observation_coverage")
        "land_use_change" ->
            listOf("land_transition_matrix", "land_top_transitions", "land_change_heatmap", "land_change_hotspots")
        "flood_pulse" ->
            listOf(
                "flood_before_water_extent",
                "flood_after_water_extent",
                "flood_expansion_heatmap",
                "flood_water_change_metrics",
                "flood_inundation_polygons",
            )
        else -> emptyList()
    }

private fun proArtifacts(job: ProJobStatusOut?): List<ProArtifactRef> =
    if (job == null) {
        emptyList()
    } else {
        (
            job.artifacts.orEmpty() +
                job.analysisArtifacts.orEmpty() +
                job.onDevicePayload?.overlayRefs.orEmpty()
        ).distinctBy { it.artifactId }
    }
