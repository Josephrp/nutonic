package com.nutonic.pro

import com.nutonic.api.ProArtifactRef
import com.nutonic.api.ProJobStatusOut
import kotlin.test.Test
import kotlin.test.assertEquals

class ProJobAggregationTest {
    @Test
    fun mergeCompletedProJobs_keeps_duplicate_artifact_ids_when_download_paths_differ() {
        val briefA =
            ProArtifactRef(
                artifactId = "brief_summary",
                kind = "brief",
                mimeType = "application/json",
                downloadUrl = "/api/v1/pro/jobs/job-a/artifacts/brief_summary",
                profile = "brief_only",
            )
        val briefB =
            briefA.copy(downloadUrl = "/api/v1/pro/jobs/job-b/artifacts/brief_summary")
        val jA =
            ProJobStatusOut(
                jobId = "job-a",
                status = "completed",
                briefArtifacts = listOf(briefA),
            )
        val jB =
            ProJobStatusOut(
                jobId = "job-b",
                status = "completed",
                briefArtifacts = listOf(briefB),
            )
        val merged = mergeCompletedProJobs(listOf(jA, jB))
        assertEquals(2, merged.briefArtifacts?.size)
    }
}
