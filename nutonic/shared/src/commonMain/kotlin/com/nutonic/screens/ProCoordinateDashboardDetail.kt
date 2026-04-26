package com.nutonic.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.LinearProgressIndicator
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
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
import com.nutonic.screens.pro.ProAnalysisLocationPicker
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard
import com.nutonic.style.NutonicPrimaryButton
import com.nutonic.vlm.ProOnDeviceVlmCoordinator
import com.nutonic.vlm.ProVlmResult
import com.nutonic.vlm.ProVlmStatus
import kotlinx.coroutines.launch

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
    var profile by rememberSaveable { mutableStateOf(ProJobProfile.BRIEF_ONLY) }
    var statusText by remember { mutableStateOf<String?>(null) }
    var currentJob by remember { mutableStateOf<ProJobStatusOut?>(null) }
    var recentJobs by remember { mutableStateOf<List<ProJobStatusOut>>(emptyList()) }
    var lastOverlayCandidate by remember { mutableStateOf<ProGameplayOverlayCandidate?>(null) }
    var proAccessToken by remember { mutableStateOf<String?>(null) }
    var vlmStatus by remember { mutableStateOf<ProVlmStatus>(ProVlmStatus.Idle) }

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
            "Pick an AOI on the map, choose a mini-app profile, then enqueue a server-side PRO analysis job.",
            style = MaterialTheme.typography.body2,
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
        ProfileSelector(profile = profile, onProfileChange = { profile = it })
        NutonicPrimaryButton(
            text = "Run PRO analysis",
            enabled = proEnabled && nutonicApiClient != null,
            onClick = {
                val client = nutonicApiClient ?: return@NutonicPrimaryButton
                scope.launch {
                    statusText = "Requesting session token..."
                    when (val token = client.postAuthToken()) {
                        is ApiResult.Ok -> {
                            proAccessToken = token.value.accessToken
                            val body =
                                ProJobCreateIn(
                                    centerLat = centerLat,
                                    centerLon = centerLon,
                                    bboxHalfKm = bboxHalfKm,
                                    mapboxZoom = mapboxZoom,
                                    analysisProfile = profile,
                                    enableTim = profile != ProJobProfile.BRIEF_ONLY,
                                    sentinelFetchMode = if (profile == ProJobProfile.BRIEF_ONLY) "MINIMAL_RGB" else "TERRAMIND_SPECTRAL",
                                    timBranch = if (profile == ProJobProfile.BRIEF_ONLY) "RGB_mapbox" else "S2L2A_full",
                                )
                            statusText = "Enqueueing PRO job..."
                            when (val created = client.postProJob(body, token.value.accessToken)) {
                                is ApiResult.Ok -> {
                                    statusText = "Job ${created.value.jobId} queued"
                                    when (
                                        val polled =
                                            client.pollProJob(
                                                created.value.jobId,
                                                token.value.accessToken,
                                                onProgress = {
                                                    currentJob = it
                                                    statusText = "Job ${it.status} · ${it.progressPct ?: 0}%"
                                                },
                                            )
                                    ) {
                                        is ApiResult.Ok -> {
                                            currentJob = polled.value
                                            recentJobs = listOf(polled.value) + recentJobs.take(4)
                                            statusText = "Job ${polled.value.status}"
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
                                                        artifactId = preferredOverlayArtifact(mergedArtifacts(polled.value)),
                                                    )
                                            }
                                        }

                                        is ApiResult.HttpFailure -> statusText = polled.userMessage
                                        is ApiResult.NetworkFailure -> statusText = "Network: ${polled.debugMessage}"
                                    }
                                }

                                is ApiResult.HttpFailure -> statusText = created.userMessage
                                is ApiResult.NetworkFailure -> statusText = "Network: ${created.debugMessage}"
                            }
                        }

                        is ApiResult.HttpFailure -> statusText = token.userMessage
                        is ApiResult.NetworkFailure -> statusText = "Network: ${token.debugMessage}"
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
        ArtifactGallery(mergedArtifacts(currentJob))
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
        MiniAppHandoff(currentJob = currentJob, onOpenMiniApp = onOpenMiniApp)
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
        Text(vlmStatus.copy(), style = MaterialTheme.typography.body2)
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
            "Model binaries are downloaded from the game server/CDN, verified by sha256, and cached outside the repository.",
            style = MaterialTheme.typography.caption,
        )
    }
}

@Composable
private fun VlmResultSummary(result: ProVlmResult) {
    Text("Caption: ${result.caption}", style = MaterialTheme.typography.body2)
    Text("Boxes: ${result.boxes.size} · model ${result.modelBundleId.orEmpty()} ${result.revision.orEmpty()}", style = MaterialTheme.typography.caption)
    result.boxes.take(4).forEach { box ->
        Text("${box.label} · ${box.bbox.joinToString(prefix = "[", postfix = "]")}", style = MaterialTheme.typography.caption)
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
private fun ProfileSelector(
    profile: ProJobProfile,
    onProfileChange: (ProJobProfile) -> Unit,
) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Mini-app profile", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        listOf(
            ProJobProfile.WILDFIRE to "FireWatch",
            ProJobProfile.OCEANSCOUT_SHIP_DETECTION to "OceanScout",
            ProJobProfile.LAND_USE_CHANGE to "LandShift",
            ProJobProfile.FLOOD_PULSE to "FloodPulse",
            ProJobProfile.BRIEF_ONLY to "Brief Composer",
        ).forEach { (candidate, label) ->
            NutonicGhostButton(
                text = if (candidate == profile) "$label selected" else label,
                onClick = { onProfileChange(candidate) },
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
        Text(statusText ?: "No job submitted yet.", style = MaterialTheme.typography.body2)
        val progress = ((currentJob?.progressPct ?: 0).coerceIn(0, 100)) / 100f
        LinearProgressIndicator(progress = progress, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        currentJob?.errorClass?.let {
            Text(proErrorCopy(it, currentJob.errorDetail), color = MaterialTheme.colors.error)
        }
    }
}

@Composable
private fun ArtifactGallery(artifacts: List<ProArtifactRef>) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Artifacts", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        if (artifacts.isEmpty()) {
            Text("Completed jobs will list map-ready frames and JSON artifacts here.", style = MaterialTheme.typography.caption)
        }
        artifacts.forEach { artifact ->
            val contract = artifact.contractId ?: "uncontracted"
            val required = if (artifact.requiredForProfile) " · required" else ""
            Text("${artifact.category ?: artifact.kind} · $contract · ${artifact.artifactId}$required")
        }
    }
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
            )
            return@NutonicGlassCard
        }
        Text(
            "Ready for map $currentMapId · ${candidate.profile} · job ${candidate.jobId.take(8)}",
            style = MaterialTheme.typography.body2,
        )
        Text(
            "Overlay coordinate ${candidate.center.latitude.format()} / ${candidate.center.longitude.format()} is kept separate from manifest data.",
            style = MaterialTheme.typography.caption,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
            NutonicGhostButton("Publish overlay", { onPublish(candidate) }, Modifier.weight(1f))
            NutonicGhostButton("Open gameplay", onOpenGameplay, Modifier.weight(1f))
        }
    }
}

@Composable
private fun MiniAppHandoff(
    currentJob: ProJobStatusOut?,
    onOpenMiniApp: (ShellDetail, ProJobStatusOut?) -> Unit,
) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Open mini-app", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            NutonicGhostButton("Fire", { onOpenMiniApp(ShellDetail.ProFireWatch, currentJob) }, Modifier.weight(1f))
            NutonicGhostButton("Ocean", { onOpenMiniApp(ShellDetail.ProOceanScout, currentJob) }, Modifier.weight(1f))
            NutonicGhostButton("Land", { onOpenMiniApp(ShellDetail.ProLandShift, currentJob) }, Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
            NutonicGhostButton("Flood", { onOpenMiniApp(ShellDetail.ProFloodPulse, currentJob) }, Modifier.weight(1f))
            NutonicGhostButton("Brief Composer", { onOpenMiniApp(ShellDetail.ProBriefComposer, currentJob) }, Modifier.weight(1f))
        }
    }
}

@Composable
private fun RecentJobs(recentJobs: List<ProJobStatusOut>) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Recent jobs", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        if (recentJobs.isEmpty()) {
            Text("No recent jobs in this session.", style = MaterialTheme.typography.caption)
        }
        recentJobs.forEach { job ->
            Text("${job.jobId.take(8)} · ${job.analysisProfile ?: job.profile.orEmpty()} · ${job.status}")
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
                is ApiResult.NetworkFailure -> onStatus("Network: ${jobs.debugMessage}")
            }
        }

        is ApiResult.HttpFailure -> onStatus(token.userMessage)
        is ApiResult.NetworkFailure -> onStatus("Network: ${token.debugMessage}")
    }
}
