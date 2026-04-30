package com.nutonic.vlm

import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertIs
import kotlin.test.assertTrue

class ProOnDeviceVlmEngineTest {
    @Test
    fun deterministicEngineReturnsVerifiedBundleResult() =
        runTest {
            val engine = DeterministicProOnDeviceVlmEngine("test runtime")
            val model =
                ProVlmCacheRecord(
                    modelBundleId = "nutonic.pro.vlm.test",
                    revision = "rev",
                    sha256 = "sha",
                    sizeBytes = 4,
                    runtime = "test",
                )
            engine.prepareModel(byteArrayOf(1, 2, 3, 4), model)

            val result =
                engine.run(
                    ProVlmPreparedInput(
                        prompt = "Assess wildfire risk.",
                        images =
                            listOf(
                                ProVlmPreparedImage(
                                    role = "mapbox_rgb",
                                    bytes = byteArrayOf(1),
                                    mimeType = "image/png",
                                    width = 1,
                                    height = 1,
                                ),
                            ),
                        model = model,
                    ),
                )

            val ok = assertIs<ProOnDeviceVlmRunResult.Ok>(result)
            assertTrue(ok.text.contains("nutonic.pro.vlm.test"))
            assertTrue(ok.text.contains("mapbox_rgb"))
        }
}
