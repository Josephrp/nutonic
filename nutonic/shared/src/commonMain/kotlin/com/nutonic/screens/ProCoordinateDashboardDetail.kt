package com.nutonic.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.LinearProgressIndicator
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.nutonic.api.ApiResult
import com.nutonic.api.FeatureFlags
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.ProArtifactRef
import com.nutonic.api.ProJobCreateIn
import com.nutonic.api.ProJobProfile
import com.nutonic.api.ProJobStatusOut
import com.nutonic.cache.ProOverlayGuess
import com.nutonic.map.LatLon
import com.nutonic.navigation.ShellDetail
import com.nutonic.pro.ProEvidenceBundleItem
import com.nutonic.pro.ProEvidenceBundleManifest
import com.nutonic.pro.parseProEvidenceBundle
import com.nutonic.screens.pro.ProAnalysisLocationPicker
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard
import com.nutonic.style.NutonicPrimaryButton
import com.nutonic.toImageBitmap
import com.nutonic.vlm.ProOnDeviceVlmCoordinator
import com.nutonic.vlm.ProVlmResult
import com.nutonic.vlm.ProVlmStatus
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

@Composable
fun ProCoordinateDashboardDetail(
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
    currentMapId: String,
    onBack: () -> Unit,
    onOpenMiniApp: (ShellDetail, ProJobStatusOut?) -> Unit,
    onOpenGameplay: () -> Unit,
    onPublishGameplayOverlay: (ProOverlayGuess) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val proEnabled = serverFeatureFlags?.proJobs == true
    var centerLat by rememberSaveable { mutableStateOf(34.05) }
    var centerLon by rememberSaveable { mutableStateOf(-118.24) }
    var bboxHalfKm by rememberSaveable { mutableStateOf(5.0) }
    var mapboxZoom by rememberSaveable { mutableStateOf(12) }
    var selectedProfiles by remember { mutableStateOf(setOf(ProJobProfile.BRIEF_ONLY)) }
    var statusText by remember { mutableStateOf<String?>(null) }
    var currentJob by remember { mutableStateOf<ProJobStatusOut?>(null) }
    var recentJobs by remember { mutableStateOf<List<ProJobStatusOut>>(emptyList()) }
    var lastOverlayCandidate by remember { mutableStateOf<ProGameplayOverlayCandidate?>(null) }
    var proAccessToken by remember { mutableStateOf<String?>(null) }
    var vlmStatus by remember { mutableStateOf<ProVlmStatus>(ProVlmStatus.Idle) }
    var bundleState by remember { mutableStateOf<ProBundleUiState>(ProBundleUiState.Idle) }
    var lastAutoBundledJobId by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(
        currentJob?.jobId,
        currentJob?.status,
        currentJob?.bundleDownloadUrl,
        proAccessToken,
        nutonicApiClient,
    ) {
        val job = currentJob
        val url = job?.bundleDownloadUrl?.takeIf { it.isNotBlank() }
        val client = nutonicApiClient
        val token = proAccessToken
        if (job == null || job.status != "completed" || url == null || client == null || token == null) {
            return@LaunchedEffect
        }
        if (lastAutoBundledJobId == job.jobId) {
            return@LaunchedEffect
        }
        bundleState = ProBundleUiState.Loading
        when (val bytes = client.getProBundleByUrl(url, token)) {
            is ApiResult.Ok -> {
                val preview = parseProEvidenceBundle(bytes.value)
                bundleState =
                    ProBundleUiState.Ready(
                        sizeBytes = preview.sizeBytes,
                        manifest = preview.manifest,
                        items = renderBundleItems(preview.items),
                        warning = preview.error,
                    )
                lastAutoBundledJobId = job.jobId
            }
            is ApiResult.HttpFailure -> bundleState = ProBundleUiState.Failed(bytes.userMessage)
            is ApiResult.NetworkFailure ->
                bundleState = ProBundleUiState.Failed("Bundle fetch failed: ${bytes.debugMessage}")
        }
    }

    fun toggleProfile(p: ProJobProfile) {
        selectedProfiles =
            buildSet {
                addAll(selectedProfiles)
                if (p in this) {
                    remove(p)
                    if (isEmpty()) add(ProJobProfile.BRIEF_ONLY)
                } else {
                    add(p)
                }
            }
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
        Text("PRO coordinate dashboard", style = MaterialTheme.typography.h5, color = MaterialTheme.colors.primary)
        Text(
            "Pick an AOI on the map, select one or more mini-app profiles, then run a queued PRO analysis (one server job per profile).",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        ProAnalysisLocationPicker(
            centerLat = centerLat,
            centerLon = centerLon,
            bboxHalfKm = bboxHalfKm,
            mapboxZoom = mapboxZoom,
            onCenterChange = { lat, lon ->
                centerLat = lat
                centerLon = lon
            },
            onBboxHalfKmChange = { bboxHalfKm = it },
            onMapboxZoomChange = { mapboxZoom = it },
        )
        BundleImageCarouselRow(bundleState = bundleState)
        MultiProfileSelector(selected = selectedProfiles, onToggle = { toggleProfile(it) })
        NutonicPrimaryButton(
            text = "Run PRO analysis queue",
            enabled = proEnabled && nutonicApiClient != null && selectedProfiles.isNotEmpty(),
            onClick = {
                val client = nutonicApiClient ?: return@NutonicPrimaryButton
                scope.launch {
                    statusText = "Requesting session token..."
                    when (val token = client.postAuthToken()) {
                        is ApiResult.Ok -> {
                            proAccessToken = token.value.accessToken
                            bundleState = ProBundleUiState.Idle
                            lastAutoBundledJobId = null
                            val profilesOrdered =
                                selectedProfiles.toList().sortedBy { it.ordinal }
                            val finishedStatuses = mutableListOf<ProJobStatusOut>()
                            var failed = false
                            for (profile in profilesOrdered) {
                                if (failed) break
                                val body =
                                    ProJobCreateIn(
                                        centerLat = centerLat,
                                        centerLon = centerLon,
                                        bboxHalfKm = bboxHalfKm,
                                        mapboxZoom = mapboxZoom,
                                        analysisProfile = profile,
                                        enableTim = profile != ProJobProfile.BRIEF_ONLY,
                                        sentinelFetchMode = "TERRAMIND_SPECTRAL",
                                        timBranch = "S2L2A_full",
                                        vlmContractId = "nutonic.pro.vlm.v1_512_s2_only",
                                    )
                                statusText = "Enqueueing ${profileLabel(profile)}…"
                                when (val created = client.postProJob(body, token.value.accessToken)) {
                                    is ApiResult.Ok -> {
                                        statusText = "Job ${created.value.jobId} queued (${profileLabel(profile)})"
                                        when (
                                            val polled =
                                                client.pollProJob(
                                                    created.value.jobId,
                                                    token.value.accessToken,
                                                    onProgress = {
                                                        currentJob = it
                                                        statusText =
                                                            "${profileLabel(profile)} · ${it.status} · ${it.progressPct ?: 0}%"
                                                    },
                                                )
                                        ) {
                                            is ApiResult.Ok -> {
                                                finishedStatuses.add(polled.value)
                                                currentJob = polled.value
                                                recentJobs =
                                                    listOf(polled.value) + recentJobs.filterNot {
                                                        it.jobId == polled.value.jobId
                                                    }.take(4)
                                                statusText = "${profileLabel(profile)} · ${polled.value.status}"
                                                val mergedRefs = mergeArtifactRefs(finishedStatuses)
                                                if (polled.value.status == "completed") {
                                                    lastOverlayCandidate =
                                                        ProGameplayOverlayCandidate(
                                                            mapId = currentMapId,
                                                            jobId = polled.value.jobId,
                                                            profile =
                                                                polled.value.analysisProfile
                                                                    ?: polled.value.profile
                                                                    ?: profile.wireToken(),
                                                            center = LatLon(centerLat, centerLon).normalized(),
                                                            artifactId = preferredOverlayArtifact(mergedRefs),
                                                        )
                                                }
                                            }

                                            is ApiResult.HttpFailure -> {
                                                statusText = polled.userMessage
                                                failed = true
                                            }
                                            is ApiResult.NetworkFailure -> {
                                                statusText = "Network unavailable while polling job status."
                                                failed = true
                                            }
                                        }
                                    }

                                    is ApiResult.HttpFailure -> {
                                        statusText = created.userMessage
                                        failed = true
                                    }
                                    is ApiResult.NetworkFailure -> {
                                        statusText = "Network unavailable while creating PRO job."
                                        failed = true
                                    }
                                }
                            }
                            if (!failed && finishedStatuses.isNotEmpty()) {
                                currentJob = finishedStatuses.last()
                            }
                        }

                        is ApiResult.HttpFailure -> statusText = token.userMessage
                        is ApiResult.NetworkFailure -> statusText = "Network unavailable while requesting session token."
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        NutonicGhostButton(
            text = "Refresh recent jobs",
            enabled = proEnabled && nutonicApiClient != null,
            onClick = {
                val client = nutonicApiClient ?: return@NutonicGhostButton
                scope.launch {
                    refreshRecentProJobs(
                        client = client,
                        onStatus = { statusText = it },
                        onJobs = { recentJobs = it },
                    )
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        if (!proEnabled) {
            Text(
                "PRO jobs are not available on this server.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.error,
            )
        }
        JobStatusCard(currentJob = currentJob, statusText = statusText)
        ProEvidenceBundleCard(
            currentJob = currentJob,
            nutonicApiClient = nutonicApiClient,
            accessToken = proAccessToken,
            state = bundleState,
            onState = { bundleState = it },
            showManualFetchButton = false,
        )
        OnDeviceVlmCard(
            currentJob = currentJob,
            nutonicApiClient = nutonicApiClient,
            accessToken = proAccessToken,
            vlmStatus = vlmStatus,
            onStatus = { vlmStatus = it },
        )
        GameplayOverlayHandoff(
            candidate = lastOverlayCandidate,
            currentMapId = currentMapId,
            onPublish = {
                onPublishGameplayOverlay(it.toOverlayGuess())
                statusText = "Published PRO overlay for gameplay map $currentMapId."
            },
            onOpenGameplay = onOpenGameplay,
        )
        MiniAppHandoff(
            selectedProfiles = selectedProfiles,
            currentJob = currentJob,
            onOpenMiniApp = onOpenMiniApp,
        )
        RecentJobs(recentJobs)
    }
}

@Composable
private fun OnDeviceVlmCard(
    currentJob: ProJobStatusOut?,
    nutonicApiClient: NutonicApiClient?,
    accessToken: String?,
    vlmStatus: ProVlmStatus,
    onStatus: (ProVlmStatus) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val completedJob = currentJob?.takeIf { it.status == "completed" }
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("On-device VLM", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Text(vlmStatus.copy(), style = MaterialTheme.typography.body2, color = MaterialTheme.colors.onBackground)
        if (vlmStatus is ProVlmStatus.DownloadingModel) {
            val total = vlmStatus.totalBytes
            val progress =
                if (total != null && total > 0) {
                    (vlmStatus.receivedBytes.toFloat() / total.toFloat()).coerceIn(0f, 1f)
                } else {
                    0f
                }
            LinearProgressIndicator(progress = progress, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        }
        if (vlmStatus is ProVlmStatus.Ready) {
            VlmResultSummary(vlmStatus.result)
        }
        NutonicGhostButton(
            text = "Run local VLM on completed job",
            enabled = completedJob != null && nutonicApiClient != null && accessToken != null,
            onClick = {
                val client = nutonicApiClient ?: return@NutonicGhostButton
                val token = accessToken ?: return@NutonicGhostButton
                val job = completedJob ?: return@NutonicGhostButton
                scope.launch {
                    ProOnDeviceVlmCoordinator(
                        apiClient = client,
                        bearerAccessToken = token,
                    ).run(job = job, onStatus = onStatus)
                }
            },
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
        Text(
            "Model weights download from the manifest URL (default: Hugging Face `LiquidAI/LFM2.5-VL-450M`), verified by sha256, and cached outside the repository.",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
    }
}

@Composable
private fun VlmResultSummary(result: ProVlmResult) {
    Text("Caption: ${result.caption}", style = MaterialTheme.typography.body2, color = MaterialTheme.colors.onBackground)
    Text(
        "Boxes: ${result.boxes.size} · model ${result.modelBundleId.orEmpty()} ${result.revision.orEmpty()}",
        style = MaterialTheme.typography.caption,
        color = MaterialTheme.colors.onBackground,
    )
    result.boxes.take(4).forEach { box ->
        Text(
            "${box.label} · ${box.bbox.joinToString(prefix = "[", postfix = "]")}",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
    }
}

private data class ProGameplayOverlayCandidate(
    val mapId: String,
    val jobId: String,
    val profile: String,
    val center: LatLon,
    val artifactId: String?,
) {
    fun toOverlayGuess(): ProOverlayGuess =
        ProOverlayGuess(
            mapId = mapId,
            coordinates = center,
            jobId = jobId,
            profile = profile,
            artifactId = artifactId,
        )
}

@Composable
private fun BundleImageCarouselRow(bundleState: ProBundleUiState) {
    when (bundleState) {
        ProBundleUiState.Loading -> {
            NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
                Text("Evidence imagery", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                Text(
                    "Loading bundle preview…",
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.onBackground,
                )
            }
        }
        is ProBundleUiState.Ready -> {
            val images = bundleState.items.filter { it.image != null }
            if (images.isEmpty()) return
            val pagerState =
                rememberPagerState(
                    pageCount = { images.size },
                )
            NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
                Text("Evidence imagery", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
                HorizontalPager(
                    state = pagerState,
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .padding(top = 8.dp),
                ) { page ->
                    val rendered = images[page]
                    Column {
                        Text(
                            rendered.item.artifact.artifactId,
                            style = MaterialTheme.typography.caption,
                            color = MaterialTheme.colors.onBackground,
                        )
                        rendered.image?.let { bitmap ->
                            Image(
                                bitmap = bitmap,
                                contentDescription = "PRO bundle image ${rendered.item.artifact.artifactId}",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxWidth().height(200.dp).padding(top = 4.dp),
                            )
                        }
                    }
                }
            }
        }
        else -> Unit
    }
}

@Composable
private fun MultiProfileSelector(
    selected: Set<ProJobProfile>,
    onToggle: (ProJobProfile) -> Unit,
) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Mini-app profiles", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Text(
            "Toggle profiles for the analysis queue and to enable matching mini-app shortcuts below.",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
        listOf(
            ProJobProfile.WILDFIRE to "FireWatch",
            ProJobProfile.OCEANSCOUT_SHIP_DETECTION to "OceanScout",
            ProJobProfile.LAND_USE_CHANGE to "LandShift",
            ProJobProfile.FLOOD_PULSE to "FloodPulse",
            ProJobProfile.BRIEF_ONLY to "Brief Composer",
        ).forEach { (candidate, label) ->
            val on = candidate in selected
            NutonicGhostButton(
                text = if (on) "$label ✓" else label,
                onClick = { onToggle(candidate) },
                modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
            )
        }
    }
}

@Composable
private fun JobStatusCard(
    currentJob: ProJobStatusOut?,
    statusText: String?,
) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Job status", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Text(
            statusText ?: "No job submitted yet.",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        val progress = ((currentJob?.progressPct ?: 0).coerceIn(0, 100)) / 100f
        LinearProgressIndicator(progress = progress, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        currentJob?.errorClass?.let {
            Text(proErrorCopy(it, currentJob.errorDetail), color = MaterialTheme.colors.error)
        }
    }
}

private sealed class ProBundleUiState {
    data object Idle : ProBundleUiState()

    data object Loading : ProBundleUiState()

    data class Ready(
        val sizeBytes: Int,
        val manifest: ProEvidenceBundleManifest?,
        val items: List<ProEvidenceBundleRenderedItem> = emptyList(),
        val warning: String? = null,
    ) : ProBundleUiState()

    data class Failed(
        val message: String,
    ) : ProBundleUiState()
}

@Composable
private fun ProEvidenceBundleCard(
    currentJob: ProJobStatusOut?,
    nutonicApiClient: NutonicApiClient?,
    accessToken: String?,
    state: ProBundleUiState,
    onState: (ProBundleUiState) -> Unit,
    showManualFetchButton: Boolean = true,
) {
    val scope = rememberCoroutineScope()
    val bundleUrl = currentJob?.bundleDownloadUrl?.takeIf { it.isNotBlank() }
    val canFetch = bundleUrl != null && nutonicApiClient != null && accessToken != null
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Evidence bundle", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Text(
            if (bundleUrl == null) {
                "Completed jobs expose a zip bundle once their manifest and artifact bytes are finalized."
            } else {
                "Bundle ready: $bundleUrl"
            },
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
        Text(
            "Mini-apps render the manifest/artifacts above; the zip is the atomic cache/export unit for the same evidence.",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
        when (state) {
            ProBundleUiState.Idle -> Unit
            ProBundleUiState.Loading -> {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                Text(
                    "Fetching bundle...",
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.onBackground,
                )
            }
            is ProBundleUiState.Ready -> ProEvidenceBundlePreview(state)
            is ProBundleUiState.Failed -> Text(state.message, color = MaterialTheme.colors.error)
        }
        if (showManualFetchButton) {
            NutonicGhostButton(
                text = "Fetch evidence bundle",
                enabled = canFetch && state !is ProBundleUiState.Loading,
                onClick = {
                    val client = nutonicApiClient ?: return@NutonicGhostButton
                    val token = accessToken ?: return@NutonicGhostButton
                    val url = bundleUrl ?: return@NutonicGhostButton
                    scope.launch {
                        onState(ProBundleUiState.Loading)
                        when (val bytes = client.getProBundleByUrl(url, token)) {
                            is ApiResult.Ok -> {
                                val preview = parseProEvidenceBundle(bytes.value)
                                onState(
                                    ProBundleUiState.Ready(
                                        sizeBytes = preview.sizeBytes,
                                        manifest = preview.manifest,
                                        items = renderBundleItems(preview.items),
                                        warning = preview.error,
                                    ),
                                )
                            }
                            is ApiResult.HttpFailure -> onState(ProBundleUiState.Failed(bytes.userMessage))
                            is ApiResult.NetworkFailure ->
                                onState(ProBundleUiState.Failed("Bundle fetch failed: ${bytes.debugMessage}"))
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }
    }
}

private data class ProEvidenceBundleRenderedItem(
    val item: ProEvidenceBundleItem,
    val image: ImageBitmap? = null,
    val summaryRows: List<String> = emptyList(),
)

@Composable
private fun ProEvidenceBundlePreview(state: ProBundleUiState.Ready) {
    val manifest = state.manifest
    Text(
        if (manifest == null) {
            "Fetched ${state.sizeBytes} bytes."
        } else {
            "Fetched ${state.sizeBytes} bytes · ${manifest.artifacts.size} artifact(s) · ${manifest.onDevicePayload?.vlmImageSet.orEmpty().size} VLM image(s)"
        },
        style = MaterialTheme.typography.body2,
        color = MaterialTheme.colors.onBackground,
    )
    state.warning?.let { Text(it, color = MaterialTheme.colors.error, style = MaterialTheme.typography.caption) }
    manifest?.let {
        val missing = it.artifacts.count { artifact -> artifact.missing }
        Text(
            "Bundle ${it.schema} · profile ${it.analysisProfile} · missing $missing",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
    }
    val summaries = state.items.filter { it.summaryRows.isNotEmpty() }.take(6)
    if (summaries.isNotEmpty()) {
        Text("Structured evidence", style = MaterialTheme.typography.subtitle2, color = MaterialTheme.colors.primary)
        summaries.forEach { rendered ->
            Text(rendered.item.artifact.artifactId, style = MaterialTheme.typography.caption, color = MaterialTheme.colors.primary)
            rendered.summaryRows.take(6).forEach { row ->
                Text(row, style = MaterialTheme.typography.caption, color = MaterialTheme.colors.onBackground)
            }
        }
    }
}

private fun renderBundleItems(items: List<ProEvidenceBundleItem>): List<ProEvidenceBundleRenderedItem> =
    items.map { item ->
        val mime = item.artifact.mimeType.lowercase()
        val image =
            if (mime.startsWith("image/")) {
                runCatching { item.bytes.toImageBitmap() }.getOrNull()
            } else {
                null
            }
        val summaryRows =
            if (mime.contains("json") || item.artifact.kind == "json" || item.artifact.kind == "geojson" || item.artifact.kind == "brief") {
                summarizeJsonBytes(item.bytes)
            } else {
                emptyList()
            }
        ProEvidenceBundleRenderedItem(item = item, image = image, summaryRows = summaryRows)
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
                ?: value.jsonPrimitive.content.take(120)
        is JsonObject -> "{${value.keys.take(4).joinToString()}${if (value.keys.size > 4) ", ..." else ""}}"
        is JsonArray -> "[size=${value.size}]"
        else -> value.toString().take(120)
    }

@Composable
private fun GameplayOverlayHandoff(
    candidate: ProGameplayOverlayCandidate?,
    currentMapId: String,
    onPublish: (ProGameplayOverlayCandidate) -> Unit,
    onOpenGameplay: () -> Unit,
) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Gameplay overlay handoff", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        if (candidate == null) {
            Text(
                "Run a PRO job to publish its center as an explicit gameplay AI overlay. This never changes manifest truth or shipped AI guesses.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
            return@NutonicGlassCard
        }
        Text(
            "Ready for map $currentMapId · ${candidate.profile} · job ${candidate.jobId.take(8)}",
            style = MaterialTheme.typography.body2,
            color = MaterialTheme.colors.onBackground,
        )
        Text(
            "Overlay coordinate ${candidate.center.latitude.format()} / ${candidate.center.longitude.format()} is kept separate from manifest data.",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
            NutonicGhostButton("Publish overlay", { onPublish(candidate) }, Modifier.weight(1f))
            NutonicGhostButton("Open gameplay", onOpenGameplay, Modifier.weight(1f))
        }
    }
}

@Composable
private fun MiniAppHandoff(
    selectedProfiles: Set<ProJobProfile>,
    currentJob: ProJobStatusOut?,
    onOpenMiniApp: (ShellDetail, ProJobStatusOut?) -> Unit,
) {
    val completed = currentJob?.status == "completed"
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Mini-apps", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Text(
            "Shortcuts respect profiles toggled above. Requires a completed PRO job.",
            style = MaterialTheme.typography.caption,
            color = MaterialTheme.colors.onBackground,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            NutonicGhostButton(
                text = "Fire",
                enabled = completed && ProJobProfile.WILDFIRE in selectedProfiles,
                onClick = { onOpenMiniApp(ShellDetail.ProFireWatch, currentJob) },
                modifier = Modifier.weight(1f),
            )
            NutonicGhostButton(
                text = "Ocean",
                enabled = completed && ProJobProfile.OCEANSCOUT_SHIP_DETECTION in selectedProfiles,
                onClick = { onOpenMiniApp(ShellDetail.ProOceanScout, currentJob) },
                modifier = Modifier.weight(1f),
            )
            NutonicGhostButton(
                text = "Land",
                enabled = completed && ProJobProfile.LAND_USE_CHANGE in selectedProfiles,
                onClick = { onOpenMiniApp(ShellDetail.ProLandShift, currentJob) },
                modifier = Modifier.weight(1f),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
            NutonicGhostButton(
                text = "Flood",
                enabled = completed && ProJobProfile.FLOOD_PULSE in selectedProfiles,
                onClick = { onOpenMiniApp(ShellDetail.ProFloodPulse, currentJob) },
                modifier = Modifier.weight(1f),
            )
            NutonicPrimaryButton(
                text = "Brief Composer",
                enabled = completed && ProJobProfile.BRIEF_ONLY in selectedProfiles,
                onClick = { onOpenMiniApp(ShellDetail.ProBriefComposer, currentJob) },
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun RecentJobs(recentJobs: List<ProJobStatusOut>) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Recent jobs", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        if (recentJobs.isEmpty()) {
            Text(
                "No recent jobs in this session.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        }
        recentJobs.forEach { job ->
            Text(
                "${job.jobId.take(8)} · ${job.analysisProfile ?: job.profile.orEmpty()} · ${job.status}",
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
        }
    }
}

private fun mergedArtifacts(job: ProJobStatusOut?): List<ProArtifactRef> {
    if (job == null) return emptyList()
    return (
        job.artifacts.orEmpty() +
            job.analysisArtifacts.orEmpty() +
            job.briefArtifacts.orEmpty() +
            job.onDevicePayload?.overlayRefs.orEmpty()
    ).distinctBy { artifact -> artifact.artifactId }
}

private fun mergeArtifactRefs(jobs: List<ProJobStatusOut>): List<ProArtifactRef> =
    jobs.flatMap { mergedArtifacts(it) }.distinctBy { artifact -> artifact.artifactId }

private fun profileLabel(profile: ProJobProfile): String =
    when (profile) {
        ProJobProfile.WILDFIRE -> "FireWatch"
        ProJobProfile.OCEANSCOUT_SHIP_DETECTION -> "OceanScout"
        ProJobProfile.LAND_USE_CHANGE -> "LandShift"
        ProJobProfile.FLOOD_PULSE -> "FloodPulse"
        ProJobProfile.BRIEF_ONLY -> "Brief Composer"
    }

private fun preferredOverlayArtifact(artifacts: List<ProArtifactRef>): String? =
    artifacts
        .firstOrNull { artifact ->
            artifact.kind == "geojson" ||
                artifact.mimeType == "application/geo+json" ||
                artifact.artifactId.contains("overlay", ignoreCase = true)
        }?.artifactId

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

private fun ProVlmStatus.copy(): String =
    when (this) {
        ProVlmStatus.Idle -> "Idle. Run a completed PRO job before local inference."
        is ProVlmStatus.DownloadingModel ->
            "Downloading model ${receivedBytes.bytesLabel()}${totalBytes?.let { " / ${it.bytesLabel()}" }.orEmpty()}"
        ProVlmStatus.LoadingModel -> "Loading local VLM runtime..."
        ProVlmStatus.Inferencing -> "Analyzing VLM image set on device..."
        is ProVlmStatus.Ready -> "Done · ${result.boxes.size} detected box(es)"
        is ProVlmStatus.Failed -> "Local VLM unavailable: $reason"
    }

private fun Long.bytesLabel(): String =
    when {
        this >= 1024L * 1024L -> "${this / (1024L * 1024L)} MiB"
        this >= 1024L -> "${this / 1024L} KiB"
        else -> "$this B"
    }

private suspend fun refreshRecentProJobs(
    client: NutonicApiClient,
    onStatus: (String) -> Unit,
    onJobs: (List<ProJobStatusOut>) -> Unit,
) {
    onStatus("Requesting session token...")
    when (val token = client.postAuthToken()) {
        is ApiResult.Ok -> {
            onStatus("Loading recent PRO jobs...")
            when (val jobs = client.listProJobs(token.value.accessToken, limit = 5)) {
                is ApiResult.Ok -> {
                    onJobs(jobs.value)
                    onStatus("Loaded ${jobs.value.size} recent PRO jobs")
                }

                is ApiResult.HttpFailure -> onStatus(jobs.userMessage)
                is ApiResult.NetworkFailure -> onStatus("Network unavailable while loading recent jobs.")
            }
        }

        is ApiResult.HttpFailure -> onStatus(token.userMessage)
        is ApiResult.NetworkFailure -> onStatus("Network unavailable while requesting session token.")
    }
}
