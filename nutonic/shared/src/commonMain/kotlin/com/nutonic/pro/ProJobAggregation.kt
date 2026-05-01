package com.nutonic.pro

import com.nutonic.api.ProArtifactRef
import com.nutonic.api.ProBriefSection
import com.nutonic.api.ProJobStatusOut
import com.nutonic.api.ProOnDevicePayload
import com.nutonic.api.ProVlmImageRef

/**
 * Combines multiple completed PRO jobs from the same AOI queue run into one view model so mini-apps
 * see the union of artifacts (unique by id + download URL so shared ids across profiles are kept).
 */
fun mergeCompletedProJobs(jobs: List<ProJobStatusOut>): ProJobStatusOut {
    require(jobs.isNotEmpty())
    require(jobs.all { it.status == "completed" })
    if (jobs.size == 1) return jobs.single()

    val mergedArtifacts =
        dedupeProArtifactRefs(jobs.flatMap { it.artifacts.orEmpty() })
    val mergedAnalysis =
        dedupeProArtifactRefs(jobs.flatMap { it.analysisArtifacts.orEmpty() })
    val mergedBrief =
        dedupeProArtifactRefs(jobs.flatMap { it.briefArtifacts.orEmpty() })

    val profiles =
        jobs.mapNotNull { j -> j.analysisProfile?.takeIf { it.isNotBlank() } ?: j.profile?.takeIf { it.isNotBlank() } }
            .distinct()

    val mergedJobId =
        jobs.joinToString("+") { it.jobId }.take(240)

    val bundleUrl =
        jobs.firstOrNull { !it.bundleDownloadUrl.isNullOrBlank() }?.bundleDownloadUrl

    return ProJobStatusOut(
        jobId = mergedJobId,
        status = "completed",
        statusReason = null,
        errorClass = null,
        errorDetail = null,
        progressPct = 100,
        profile = profiles.joinToString(",").takeIf { it.isNotEmpty() },
        analysisProfile = profiles.joinToString(",").takeIf { it.isNotEmpty() },
        startedAt = jobs.mapNotNull { it.startedAt }.minOrNull(),
        finishedAt = jobs.mapNotNull { it.finishedAt }.maxOrNull(),
        artifacts = mergedArtifacts.takeIf { it.isNotEmpty() },
        analysisArtifacts = mergedAnalysis.takeIf { it.isNotEmpty() },
        briefArtifacts = mergedBrief.takeIf { it.isNotEmpty() },
        sceneProvenance = jobs.firstOrNull { it.sceneProvenance != null }?.sceneProvenance,
        onDevicePayload = mergeOnDevicePayloads(jobs.mapNotNull { it.onDevicePayload }),
        bundleDownloadUrl = bundleUrl,
        materializationId =
            jobs.mapNotNull { it.materializationId?.takeIf { id -> id.isNotBlank() } }
                .distinct()
                .joinToString(",")
                .takeIf { it.isNotEmpty() },
        cacheKey =
            jobs.mapNotNull { it.cacheKey?.takeIf { k -> k.isNotBlank() } }
                .distinct()
                .joinToString(",")
                .takeIf { it.isNotEmpty() },
        materializationSummary =
            jobs.firstOrNull { it.materializationSummary != null }?.materializationSummary,
    )
}

private fun mergeOnDevicePayloads(payloads: List<ProOnDevicePayload>): ProOnDevicePayload? {
    if (payloads.isEmpty()) return null
    if (payloads.size == 1) return payloads.single()
    val sections =
        payloads.flatMap { it.briefSections }.distinctBy { sectionKey(it) }
    val overlays =
        payloads.flatMap { it.overlayRefs }.distinctBy { it.artifactId }
    val confidence =
        payloads.mapNotNull { it.confidenceSummary?.takeIf { s -> s.isNotBlank() } }
            .distinct()
            .joinToString("\n")
            .takeIf { it.isNotEmpty() }
    val images =
        payloads.flatMap { it.vlmImageSet }.distinctBy { imageKey(it) }
    val injection =
        payloads.firstOrNull { it.vlmPromptInjection != null }?.vlmPromptInjection
    return ProOnDevicePayload(
        briefSections = sections,
        overlayRefs = overlays,
        confidenceSummary = confidence,
        vlmImageSet = images,
        vlmPromptInjection = injection,
        onDeviceModelHint =
            payloads.firstOrNull { !it.onDeviceModelHint.isNullOrBlank() }?.onDeviceModelHint,
        modelBundleId =
            payloads.firstOrNull { !it.modelBundleId.isNullOrBlank() }?.modelBundleId,
    )
}

private fun sectionKey(s: ProBriefSection): String = "${s.title}\u0000${s.body}"

private fun imageKey(i: ProVlmImageRef): String =
    "${i.role}\u0000${i.url ?: i.inlineRef ?: i.artifactId.orEmpty()}"
