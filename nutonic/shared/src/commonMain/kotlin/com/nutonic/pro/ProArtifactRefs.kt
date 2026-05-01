package com.nutonic.pro

import com.nutonic.api.ProArtifactRef
import com.nutonic.api.ProJobStatusOut

/**
 * Dedupe refs that share an [ProArtifactRef.artifactId] but differ by download path (e.g. merged multi-profile runs).
 */
fun dedupeProArtifactRefs(refs: Iterable<ProArtifactRef>): List<ProArtifactRef> =
    refs.distinctBy { ref ->
        "${ref.artifactId}\u0000${ref.downloadUrl ?: ""}"
    }

/**
 * All artifact refs for one PRO job (deduped by id + download URL within that job).
 */
fun allProArtifactRefsForJob(job: ProJobStatusOut?): List<ProArtifactRef> {
    if (job == null) return emptyList()
    return dedupeProArtifactRefs(
        job.artifacts.orEmpty() +
            job.analysisArtifacts.orEmpty() +
            job.briefArtifacts.orEmpty() +
            job.onDevicePayload?.overlayRefs.orEmpty(),
    )
}

/**
 * Merge artifacts from several PRO jobs. The same [ProArtifactRef.artifactId] may appear in multiple jobs;
 * each copy is kept because [ProArtifactRef.downloadUrl] is scoped to its job.
 */
fun mergeProArtifactRefsAcrossJobs(jobs: List<ProJobStatusOut>): List<ProArtifactRef> =
    jobs
        .flatMap { job ->
            allProArtifactRefsForJob(job).map { ref -> job.jobId to ref }
        }
        .distinctBy { (jobId, ref) -> "$jobId:${ref.artifactId}" }
        .map { it.second }
