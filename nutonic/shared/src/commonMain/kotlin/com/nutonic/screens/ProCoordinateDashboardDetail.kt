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
import com.nutonic.navigation.ShellDetail
import com.nutonic.screens.pro.ProAnalysisLocationPicker
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicGlassCard
import com.nutonic.style.NutonicPrimaryButton
import kotlinx.coroutines.launch

@Composable
fun ProCoordinateDashboardDetail(
    nutonicApiClient: NutonicApiClient?,
    serverFeatureFlags: FeatureFlags?,
    onBack: () -> Unit,
    onOpenMiniApp: (ShellDetail) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val proEnabled = serverFeatureFlags?.proJobs == true
    var centerLat by rememberSaveable { mutableStateOf(34.05) }
    var centerLon by rememberSaveable { mutableStateOf(-118.24) }
    var bboxHalfKm by rememberSaveable { mutableStateOf(5.0) }
    var profile by rememberSaveable { mutableStateOf(ProJobProfile.BRIEF_ONLY) }
    var statusText by remember { mutableStateOf<String?>(null) }
    var currentJob by remember { mutableStateOf<ProJobStatusOut?>(null) }
    var recentJobs by remember { mutableStateOf<List<ProJobStatusOut>>(emptyList()) }

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
            onCenterChange = { lat, lon ->
                centerLat = lat
                centerLon = lon
            },
            onBboxHalfKmChange = { bboxHalfKm = it },
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
                            val body =
                                ProJobCreateIn(
                                    centerLat = centerLat,
                                    centerLon = centerLon,
                                    bboxHalfKm = bboxHalfKm,
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
        if (!proEnabled) {
            Text(
                "PRO jobs are not available on this server.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.error,
            )
        }
        JobStatusCard(currentJob = currentJob, statusText = statusText)
        ArtifactGallery(currentJob?.artifacts.orEmpty())
        MiniAppHandoff(onOpenMiniApp)
        RecentJobs(recentJobs)
    }
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
            Text("Error: $it ${currentJob.errorDetail.orEmpty()}", color = MaterialTheme.colors.error)
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
            Text("${artifact.kind} · ${artifact.artifactId} · ${artifact.downloadUrl.orEmpty()}")
        }
    }
}

@Composable
private fun MiniAppHandoff(onOpenMiniApp: (ShellDetail) -> Unit) {
    NutonicGlassCard(modifier = Modifier.fillMaxWidth()) {
        Text("Open mini-app", style = MaterialTheme.typography.subtitle1, color = MaterialTheme.colors.primary)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            NutonicGhostButton("Fire", { onOpenMiniApp(ShellDetail.ProFireWatch) }, Modifier.weight(1f))
            NutonicGhostButton("Ocean", { onOpenMiniApp(ShellDetail.ProOceanScout) }, Modifier.weight(1f))
            NutonicGhostButton("Land", { onOpenMiniApp(ShellDetail.ProLandShift) }, Modifier.weight(1f))
        }
        NutonicGhostButton("Brief Composer", { onOpenMiniApp(ShellDetail.ProBriefComposer) }, Modifier.fillMaxWidth().padding(top = 8.dp))
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
