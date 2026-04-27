package com.nutonic.screens.pro

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.CircularProgressIndicator
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.nutonic.api.ApiResult
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.ProArtifactRef
import com.nutonic.api.ProJobStatusOut
import com.nutonic.filter.getPlatformContext
import com.nutonic.share.shareNutonicScorecard
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard
import com.nutonic.toImageBitmap
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

@Composable
fun ProFireWatchScreen(
    job: ProJobStatusOut?,
    nutonicApiClient: NutonicApiClient?,
    onBack: () -> Unit,
    onOpenBriefComposer: () -> Unit,
) {
    val artifacts = fireWatchArtifacts(job)
    val ui = rememberArtifactInspectorState(job, artifacts, nutonicApiClient)
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
        MiniAppHeader(
            title = "FireWatch",
            subtitle = "Wildfire and burn-change review for temporal Sentinel/TiM outputs.",
            onBack = onBack,
        )
        SelectedRunCard(job)
        ArtifactSyncCard(state = ui, onRefresh = ui.refresh)

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Burn and change overlays", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactInsightLine("Heatmap", heatmap, ui.state)
            ArtifactInsightLine("Hotspot GeoJSON", hotspotsGeoJson, ui.state)
            Text(
                "Heatmap values are change indicators from temporal scene deltas. Validate against source imagery before action.",
                style = MaterialTheme.typography.caption,
            )
        }

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Hotspot ranking", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactInsightLine("Hotspot list", hotspots, ui.state)
            ArtifactInsightLine("Metrics", metrics, ui.state)
            FieldSummary(
                title = "Operational summary",
                rows =
                    summaryRows(
                        ui.state,
                        "firewatch_hotspots",
                        listOf("hotspot_count", "top_hotspot_score", "confidence", "warnings"),
                    ),
            )
            MissingRequiredArtifacts(job)
        }

        BriefHandoffCard(onOpenBriefComposer)
    }
}

@Composable
fun ProOceanScoutScreen(
    job: ProJobStatusOut?,
    nutonicApiClient: NutonicApiClient?,
    onBack: () -> Unit,
    onOpenBriefComposer: () -> Unit,
) {
    val artifacts = proArtifacts(job)
    val ui = rememberArtifactInspectorState(job, artifacts, nutonicApiClient)

    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        MiniAppHeader(
            title = "OceanScout",
            subtitle = "Candidate vessel review with coverage-normalized maritime activity indicators.",
            onBack = onBack,
        )
        SelectedRunCard(job)
        ArtifactSyncCard(state = ui, onRefresh = ui.refresh)

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Candidate overlays", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactInsightLine("Vessel overlay", artifacts.firstOrNull { it.artifactId == "vessel_overlay" }, ui.state)
            ArtifactInsightLine("Candidate list", artifacts.firstOrNull { it.artifactId == "vessel_candidates" }, ui.state)
            FieldSummary(
                title = "Evidence classes",
                rows =
                    summaryRows(
                        ui.state,
                        "vessel_candidates",
                        listOf("evidence_level", "confidence", "candidate_count", "limitations"),
                    ),
            )
        }

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Coverage-normalized activity", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactInsightLine("Lane heatmap", artifacts.firstOrNull { it.artifactId == "lane_heatmap" }, ui.state)
            ArtifactInsightLine("Observation coverage", artifacts.firstOrNull { it.artifactId == "observation_coverage" }, ui.state)
            ArtifactInsightLine("Incursion events", artifacts.firstOrNull { it.artifactId == "incursion_events" }, ui.state)
            FieldSummary(
                title = "Coverage and confidence",
                rows =
                    summaryRows(
                        ui.state,
                        "observation_coverage",
                        listOf("valid_observation_count", "coverage_ratio", "cloud_ratio", "insufficient_observation"),
                    ) +
                        summaryRows(
                            ui.state,
                            "incursion_events",
                            listOf("event_count", "confidence", "warnings"),
                        ),
            )
            Text(
                "Outputs are presence indicators. Review observation coverage and blind spots before reporting claims.",
                style = MaterialTheme.typography.caption,
            )
            MissingRequiredArtifacts(job)
        }

        BriefHandoffCard(onOpenBriefComposer)
    }
}

@Composable
fun ProLandShiftScreen(
    job: ProJobStatusOut?,
    nutonicApiClient: NutonicApiClient?,
    onBack: () -> Unit,
    onOpenBriefComposer: () -> Unit,
) {
    val artifacts = proArtifacts(job)
    val ui = rememberArtifactInspectorState(job, artifacts, nutonicApiClient)

    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        MiniAppHeader(
            title = "LandShift",
            subtitle = "Land use and land cover transition review across temporal windows.",
            onBack = onBack,
        )
        SelectedRunCard(job)
        ArtifactSyncCard(state = ui, onRefresh = ui.refresh)

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Transitions", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactInsightLine("Transition matrix", artifacts.firstOrNull { it.artifactId == "land_transition_matrix" }, ui.state)
            ArtifactInsightLine("Top transitions", artifacts.firstOrNull { it.artifactId == "land_top_transitions" }, ui.state)
            ArtifactInsightLine("Change heatmap", artifacts.firstOrNull { it.artifactId == "land_change_heatmap" }, ui.state)
            FieldSummary(
                title = "Topline transition stats",
                rows =
                    summaryRows(
                        ui.state,
                        "land_transition_matrix",
                        listOf("total_pixels", "dominant_transition", "confidence", "warnings"),
                    ) +
                        summaryRows(
                            ui.state,
                            "land_top_transitions",
                            listOf("top_transitions", "coverage_ratio"),
                        ),
            )
        }

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Change hotspots", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactInsightLine("Hotspot GeoJSON", artifacts.firstOrNull { it.artifactId == "land_change_hotspots" }, ui.state)
            Text(
                "Transition classes are proxy analytics derived from temporal spectral differences. Validate with scene provenance.",
                style = MaterialTheme.typography.caption,
            )
            MissingRequiredArtifacts(job)
        }

        BriefHandoffCard(onOpenBriefComposer)
    }
}

@Composable
fun ProFloodPulseScreen(
    job: ProJobStatusOut?,
    nutonicApiClient: NutonicApiClient?,
    onBack: () -> Unit,
    onOpenBriefComposer: () -> Unit,
) {
    val artifacts = proArtifacts(job)
    val ui = rememberArtifactInspectorState(job, artifacts, nutonicApiClient)

    Column(
        modifier =
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        MiniAppHeader(
            title = "FloodPulse",
            subtitle = "Water expansion and affected-area review for flood-sensitive profiles.",
            onBack = onBack,
        )
        SelectedRunCard(job)
        ArtifactSyncCard(state = ui, onRefresh = ui.refresh)

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Before and after extent", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactInsightLine("Before extent", artifacts.firstOrNull { it.artifactId == "flood_before_water_extent" }, ui.state)
            ArtifactInsightLine("After extent", artifacts.firstOrNull { it.artifactId == "flood_after_water_extent" }, ui.state)
            ArtifactInsightLine("Expansion heatmap", artifacts.firstOrNull { it.artifactId == "flood_expansion_heatmap" }, ui.state)
        }

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Affected area", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            ArtifactInsightLine("Water change metrics", artifacts.firstOrNull { it.artifactId == "flood_water_change_metrics" }, ui.state)
            ArtifactInsightLine("Inundation polygons", artifacts.firstOrNull { it.artifactId == "flood_inundation_polygons" }, ui.state)
            FieldSummary(
                title = "Flood metrics",
                rows =
                    summaryRows(
                        ui.state,
                        "flood_water_change_metrics",
                        listOf("affected_area_km2", "change_ratio", "confidence", "warnings"),
                    ),
            )
            Text(
                "Flood polygons are decision-support geometry and should be reviewed against source scenes.",
                style = MaterialTheme.typography.caption,
            )
            MissingRequiredArtifacts(job)
        }

        BriefHandoffCard(onOpenBriefComposer)
    }
}

@Composable
fun ProBriefComposerScreen(
    job: ProJobStatusOut?,
    nutonicApiClient: NutonicApiClient?,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val platformContext = getPlatformContext()
    val artifacts = proArtifacts(job)
    val ui = rememberArtifactInspectorState(job, artifacts, nutonicApiClient)
    var includeOverlays by remember { mutableStateOf(true) }
    var includeMetrics by remember { mutableStateOf(true) }
    var includeBrief by remember { mutableStateOf(true) }
    var shareState by remember { mutableStateOf<BriefShareState>(BriefShareState.Idle) }

    val selectedArtifacts =
        artifacts.filter { artifact ->
            (includeOverlays && (artifact.kind == "geojson" || artifact.mimeType.startsWith("image/"))) ||
                (includeMetrics && (artifact.kind == "json" || artifact.mimeType.contains("json"))) ||
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
        MiniAppHeader(
            title = "Brief Composer",
            subtitle = "Cross-mini-app synthesis with confidence-aware sections and source toggles.",
            onBack = onBack,
        )
        SelectedRunCard(job)
        ArtifactSyncCard(state = ui, onRefresh = ui.refresh)

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
                Text("No brief sections are attached yet.", style = MaterialTheme.typography.caption)
            } else {
                sections.forEach { section ->
                    Text(section.title, style = MaterialTheme.typography.body1, color = MaterialTheme.colors.primary)
                    Text(section.body, style = MaterialTheme.typography.body2)
                    section.confidence?.let {
                        Text("Confidence: $it", style = MaterialTheme.typography.caption)
                    }
                }
            }
        }

        NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
            Text("Export/share draft", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
            Text("Selected sources: ${selectedArtifacts.size}", style = MaterialTheme.typography.body2)
            val shareBody =
                buildBriefShareBody(
                    job = job,
                    state = ui.state,
                    selectedArtifacts = selectedArtifacts,
                    includeOverlays = includeOverlays,
                    includeMetrics = includeMetrics,
                    includeBrief = includeBrief,
                )
            when (val current = shareState) {
                BriefShareState.Idle -> Unit
                BriefShareState.Loading ->
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(modifier = Modifier.height(14.dp).fillMaxWidth(0.08f), strokeWidth = 2.dp)
                        Text("Preparing brief share payload...", style = MaterialTheme.typography.caption)
                    }
                is BriefShareState.Completed ->
                    Text(
                        current.message,
                        style = MaterialTheme.typography.caption,
                        color = if (current.success) MaterialTheme.colors.secondary else MaterialTheme.colors.error,
                    )
            }
            OutlinedButton(
                enabled = shareState !is BriefShareState.Loading && shareBody.isNotBlank(),
                onClick = {
                    shareState = BriefShareState.Loading
                    scope.launch {
                        val ok = shareNutonicScorecard(platformContext, shareBody)
                        shareState =
                            if (ok) {
                                BriefShareState.Completed("Brief export/share opened (or copied where supported).", success = true)
                            } else {
                                BriefShareState.Completed("Sharing unavailable on this device right now.", success = false)
                            }
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            ) {
                Text("Export / Share brief draft")
            }
            selectedArtifacts.take(12).forEach { artifact ->
                ArtifactInsightLine("Source", artifact, ui.state)
            }
            if (selectedArtifacts.size > 12) {
                Text("+${selectedArtifacts.size - 12} more selected sources", style = MaterialTheme.typography.caption)
            }
        }
    }
}

@Composable
private fun MiniAppHeader(
    title: String,
    subtitle: String,
    onBack: () -> Unit,
) {
    NutonicGhostButton(text = "Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
    Text(title, style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
    Text(subtitle, style = MaterialTheme.typography.body2)
}

@Composable
private fun SelectedRunCard(job: ProJobStatusOut?) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Selected PRO run", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        if (job == null) {
            Text("Open this route from a completed PRO run.", style = MaterialTheme.typography.body2)
            return@NutonicGlassCard
        }
        Text("${job.jobId.take(8)} | ${job.analysisProfile ?: job.profile.orEmpty()} | ${job.status}")
        val reason = job.statusReason ?: job.errorClass
        if (!reason.isNullOrBlank()) {
            Text("Status reason: $reason", style = MaterialTheme.typography.caption)
        }
        job.errorClass?.let { errorClass ->
            Text(proErrorCopy(errorClass, job.errorDetail), style = MaterialTheme.typography.caption, color = MaterialTheme.colors.error)
        }
        job.sceneProvenance?.let {
            Text("Scene provenance: ${it.toString().take(400)}", style = MaterialTheme.typography.caption)
        }
    }
}

@Composable
private fun BriefHandoffCard(onOpenBriefComposer: () -> Unit) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Brief handoff", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Text("Send reviewed overlays, metrics, and caveats into Brief Composer for confidence-aware synthesis.")
        NutonicGhostButton(
            text = "Open Brief Composer",
            onClick = onOpenBriefComposer,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
    }
}

private data class ArtifactInspectorUi(
    val state: ArtifactInspectorState,
    val refresh: () -> Unit,
)

private data class ArtifactInspectorState(
    val loading: Boolean = false,
    val statusLine: String = "Not loaded",
    val insights: Map<String, ArtifactInsight> = emptyMap(),
)

private data class ArtifactInsight(
    val artifact: ProArtifactRef,
    val bytesSize: Int? = null,
    val image: ImageBitmap? = null,
    val summaryRows: List<String> = emptyList(),
    val warning: String? = null,
)

@Composable
private fun rememberArtifactInspectorState(
    job: ProJobStatusOut?,
    artifacts: List<ProArtifactRef>,
    nutonicApiClient: NutonicApiClient?,
): ArtifactInspectorUi {
    val scope = rememberCoroutineScope()
    var state by remember(job?.jobId, job?.status, nutonicApiClient) { mutableStateOf(ArtifactInspectorState()) }

    fun triggerRefresh() {
        scope.launch {
            state = state.copy(loading = true, statusLine = "Loading artifacts...")
            state = loadArtifactInsights(job, artifacts, nutonicApiClient)
        }
    }

    LaunchedEffect(job?.jobId, job?.status, nutonicApiClient) {
        if (job != null && job.status == "completed" && nutonicApiClient != null) {
            triggerRefresh()
        }
    }

    return ArtifactInspectorUi(state = state, refresh = ::triggerRefresh)
}

private suspend fun loadArtifactInsights(
    job: ProJobStatusOut?,
    artifacts: List<ProArtifactRef>,
    nutonicApiClient: NutonicApiClient?,
): ArtifactInspectorState {
    if (job == null) {
        return ArtifactInspectorState(loading = false, statusLine = "No selected PRO job.")
    }
    if (job.status != "completed") {
        return ArtifactInspectorState(loading = false, statusLine = "Job status is ${job.status}. Previews load after completion.")
    }
    val client = nutonicApiClient
        ?: return ArtifactInspectorState(loading = false, statusLine = "API client unavailable. Cannot load artifact previews.")
    if (artifacts.isEmpty()) {
        return ArtifactInspectorState(loading = false, statusLine = "No artifacts attached to this run.")
    }

    val token =
        when (val t = client.postAuthToken()) {
            is ApiResult.Ok -> t.value.accessToken
            is ApiResult.HttpFailure -> return ArtifactInspectorState(loading = false, statusLine = t.userMessage)
            is ApiResult.NetworkFailure -> return ArtifactInspectorState(loading = false, statusLine = "Network unavailable while requesting session token.")
        }

    val insights = mutableMapOf<String, ArtifactInsight>()
    var loadedCount = 0

    for (artifact in artifacts.take(24)) {
        val bytesResult = fetchArtifactBytes(client, job, artifact, token)
        val insight =
            when (bytesResult) {
                is ApiResult.Ok -> {
                    loadedCount += 1
                    buildArtifactInsight(artifact, bytesResult.value)
                }
                is ApiResult.HttpFailure -> ArtifactInsight(artifact = artifact, warning = bytesResult.userMessage)
                is ApiResult.NetworkFailure -> ArtifactInsight(artifact = artifact, warning = "Download failed: ${bytesResult.debugMessage}")
            }
        insights[artifact.artifactId] = insight
    }

    return ArtifactInspectorState(
        loading = false,
        statusLine = "Loaded $loadedCount / ${artifacts.size.coerceAtMost(24)} artifact preview(s)",
        insights = insights,
    )
}

private suspend fun fetchArtifactBytes(
    client: NutonicApiClient,
    job: ProJobStatusOut,
    artifact: ProArtifactRef,
    accessToken: String,
): ApiResult<ByteArray> {
    val url = artifact.downloadUrl
    return if (!url.isNullOrBlank()) {
        client.getProArtifactByUrl(url, accessToken)
    } else {
        client.getProArtifact(job.jobId, artifact.artifactId, accessToken)
    }
}

private fun buildArtifactInsight(
    artifact: ProArtifactRef,
    bytes: ByteArray,
): ArtifactInsight {
    val mime = artifact.mimeType.lowercase()
    val image =
        if (mime.startsWith("image/")) {
            runCatching { bytes.toImageBitmap() }.getOrNull()
        } else {
            null
        }

    val summaryRows =
        if (mime.contains("json") || artifact.kind == "json" || artifact.kind == "geojson" || artifact.kind == "brief") {
            summarizeJsonBytes(bytes)
        } else {
            emptyList()
        }

    return ArtifactInsight(
        artifact = artifact,
        bytesSize = bytes.size,
        image = image,
        summaryRows = summaryRows,
    )
}

private fun summarizeJsonBytes(bytes: ByteArray): List<String> {
    val text = runCatching { bytes.decodeToString() }.getOrNull()?.trim().orEmpty()
    if (text.isBlank()) {
        return listOf("Empty JSON payload")
    }
    val element = runCatching { com.nutonic.api.NutonicJson.parseToJsonElement(text) }.getOrNull()
    return if (element == null) {
        listOf("Non-parseable JSON payload", text.take(220))
    } else {
        summarizeJsonElement(element)
    }
}

private fun summarizeJsonElement(element: JsonElement): List<String> =
    when (element) {
        is JsonObject -> {
            val entries = element.entries.sortedBy { it.key }
            val rows = mutableListOf("Object keys: ${entries.size}")
            entries.take(8).forEach { (key, value) ->
                rows += "$key: ${summarizePrimitive(value)}"
            }
            if (entries.size > 8) {
                rows += "... ${entries.size - 8} additional keys"
            }
            rows
        }
        is JsonArray -> {
            val rows = mutableListOf("Array items: ${element.size}")
            element.take(5).forEachIndexed { index, item ->
                rows += "[$index] ${summarizePrimitive(item)}"
            }
            if (element.size > 5) {
                rows += "... ${element.size - 5} additional items"
            }
            rows
        }
        is JsonPrimitive -> listOf(summarizePrimitive(element))
        else -> listOf(element.toString().take(220))
    }

private fun summarizePrimitive(value: JsonElement): String =
    when (value) {
        is JsonPrimitive ->
            value.booleanOrNull?.toString()
                ?: value.intOrNull?.toString()
                ?: value.doubleOrNull?.let { "${(it * 1000.0).toInt() / 1000.0}" }
                ?: value.content.take(120)
        is JsonObject -> "{${value.keys.take(4).joinToString()}${if (value.keys.size > 4) ", ..." else ""}}"
        is JsonArray -> "[size=${value.size}]"
        else -> value.toString().take(120)
    }

@Composable
private fun ArtifactSyncCard(
    state: ArtifactInspectorUi,
    onRefresh: () -> Unit,
) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Artifact sync", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Text(state.state.statusLine, style = MaterialTheme.typography.body2)
        NutonicGhostButton(
            text = if (state.state.loading) "Loading previews..." else "Refresh artifact previews",
            onClick = onRefresh,
            enabled = !state.state.loading,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
    }
}

@Composable
private fun ArtifactInsightLine(
    label: String,
    artifact: ProArtifactRef?,
    state: ArtifactInspectorState,
) {
    if (artifact == null) {
        Text("$label: not attached", style = MaterialTheme.typography.caption)
        return
    }
    val insight = state.insights[artifact.artifactId]

    Column(modifier = Modifier.fillMaxWidth().padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            "$label: ${artifact.artifactId} (${artifact.kind})",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        Text(
            buildString {
                append("contract=")
                append(artifact.contractId ?: "n/a")
                artifact.category?.let {
                    append(" | category=")
                    append(it)
                }
                if (artifact.requiredForProfile) {
                    append(" | required")
                }
            },
            style = MaterialTheme.typography.caption,
        )
        insight?.bytesSize?.let { size ->
            Text("Preview bytes: $size", style = MaterialTheme.typography.caption)
        }
        insight?.image?.let { bitmap ->
            Image(
                bitmap = bitmap,
                contentDescription = "$label preview",
                modifier = Modifier.fillMaxWidth().height(120.dp),
                contentScale = ContentScale.Crop,
            )
        }
        insight?.summaryRows?.take(6)?.forEach { line ->
            Text(line, style = MaterialTheme.typography.caption)
        }
        if (insight == null && !state.loading) {
            Text("Preview not loaded yet.", style = MaterialTheme.typography.caption)
        }
        insight?.warning?.let {
            Text(it, style = MaterialTheme.typography.caption, color = MaterialTheme.colors.error)
        }
    }
}

private fun summaryRows(
    state: ArtifactInspectorState,
    artifactId: String,
    keys: List<String>,
): List<String> {
    val rows = state.insights[artifactId]?.summaryRows.orEmpty()
    if (rows.isEmpty()) {
        return emptyList()
    }
    return keys.mapNotNull { key ->
        rows.firstOrNull { it.startsWith("$key:") }
    }
}

@Composable
private fun FieldSummary(
    title: String,
    rows: List<String>,
) {
    if (rows.isEmpty()) {
        return
    }
    Column(modifier = Modifier.fillMaxWidth().padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(title, style = MaterialTheme.typography.caption, color = MaterialTheme.colors.primary)
        rows.forEach { row ->
            Text(row, style = MaterialTheme.typography.caption)
        }
    }
}

@Composable
private fun SourceToggle(
    label: String,
    enabled: Boolean,
    onToggle: () -> Unit,
) {
    NutonicGhostButton(
        text = "${if (enabled) "Included" else "Excluded"} | $label",
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

private sealed interface BriefShareState {
    data object Idle : BriefShareState

    data object Loading : BriefShareState

    data class Completed(
        val message: String,
        val success: Boolean,
    ) : BriefShareState
}

private fun buildBriefShareBody(
    job: ProJobStatusOut?,
    state: ArtifactInspectorState,
    selectedArtifacts: List<ProArtifactRef>,
    includeOverlays: Boolean,
    includeMetrics: Boolean,
    includeBrief: Boolean,
): String =
    buildString {
        appendLine("NU:TONIC PRO brief draft")
        if (job == null) {
            appendLine("No selected PRO run.")
            return@buildString
        }
        append("Job: ").appendLine(job.jobId)
        append("Profile: ").appendLine(job.analysisProfile ?: job.profile.orEmpty())
        append("Status: ").appendLine(job.status)
        append("Source toggles: overlays=").append(includeOverlays).append(", metrics=").append(includeMetrics).append(", brief=").appendLine(includeBrief)
        append("Selected sources: ").appendLine(selectedArtifacts.size.toString())
        if (selectedArtifacts.isEmpty()) {
            appendLine("No source artifacts selected.")
        } else {
            selectedArtifacts.take(20).forEach { artifact ->
                append("- ").append(artifact.artifactId)
                    .append(" | kind=").append(artifact.kind)
                    .append(" | contract=").append(artifact.contractId ?: "n/a")
                    .append(" | required=").appendLine(artifact.requiredForProfile.toString())
                state.insights[artifact.artifactId]?.summaryRows?.take(3)?.forEach { row ->
                    append("  • ").appendLine(row.take(200))
                }
            }
            if (selectedArtifacts.size > 20) {
                append("... ").append(selectedArtifacts.size - 20).appendLine(" more sources omitted")
            }
        }
        job.onDevicePayload?.briefSections?.take(6)?.forEach { section ->
            appendLine()
            append("[Section] ").appendLine(section.title)
            appendLine(section.body.take(500))
            section.confidence?.let { append("Confidence: ").appendLine(it) }
        }
    }.trim()

private fun proErrorCopy(
    errorClass: String,
    detail: String?,
): String =
    when (errorClass) {
        "stac_no_coverage" -> "No satellite imagery was found for this AOI. Try a nearby point or wider date range."
        "stac_cloud_ceiling" -> "Available scenes are too cloudy. Try a wider date range or a smaller AOI."
        "worker_timeout" -> "Processing took too long. Retry the job, or reduce the AOI radius."
        "worker_unreachable" -> "The required analysis service is temporarily unavailable. Try again shortly."
        "worker_error" -> "The analysis worker failed while processing this job. Retry or choose a different AOI."
        "input_validation" -> "The job input was rejected. Check coordinates, profile, and AOI radius."
        "cancelled" -> "The job was cancelled."
        else -> "Unexpected PRO job error: ${detail.orEmpty().ifBlank { errorClass }}"
    }
