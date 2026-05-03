package com.nutonic.vlm

import com.nutonic.api.ApiResult
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.ProArtifactRef
import com.nutonic.api.ProJobStatusOut
import com.nutonic.api.ProVlmImageRef
import com.nutonic.api.ProVlmModelManifest
import com.nutonic.persistence.Utf8BlobStore
import com.nutonic.pro.ProModelPromptContract
import com.nutonic.pro.allProArtifactRefsForJob
import com.nutonic.persistence.createProVlmModelBlobStore
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.kotlincrypto.hash.sha2.SHA256

private const val DEFAULT_MODEL_BUNDLE_ID = "NuTonic/lspace"
private const val DEFAULT_CONTRACT_ID = "nutonic.pro.vlm.v1_512_s2_only"
private const val MAX_PROMPT_CHARS = 500

private val ProVlmJson =
    Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

/** Pretty JSON for server ``vlm_prompt_injection`` (run_manifest / tim_summary can be large). */
private val VlmPromptInjectJson =
    Json {
        prettyPrint = true
        ignoreUnknownKeys = true
    }

sealed class ProVlmStatus {
    data object Idle : ProVlmStatus()

    data class DownloadingModel(
        val receivedBytes: Long,
        val totalBytes: Long?,
    ) : ProVlmStatus()

    data object LoadingModel : ProVlmStatus()

    data object Inferencing : ProVlmStatus()

    data class Ready(
        val result: ProVlmResult,
    ) : ProVlmStatus()

    data class Failed(
        val reason: String,
    ) : ProVlmStatus()
}

@Serializable
data class ProVlmCacheRecord(
    @SerialName("model_bundle_id") val modelBundleId: String,
    val revision: String,
    val sha256: String,
    @SerialName("size_bytes") val sizeBytes: Long,
    val runtime: String,
)

@Serializable
data class ProVlmResult(
    val caption: String,
    val boxes: List<ProVlmBoundingBox> = emptyList(),
    @SerialName("model_bundle_id") val modelBundleId: String? = null,
    val revision: String? = null,
    val source: String,
)

@Serializable
data class ProVlmBoundingBox(
    val label: String,
    val bbox: List<Double>,
    val confidence: Double? = null,
)

data class ProVlmPreparedInput(
    val prompt: String,
    val images: List<ProVlmPreparedImage>,
    val model: ProVlmCacheRecord,
)

data class ProVlmPreparedImage(
    val role: String,
    val bytes: ByteArray,
    val mimeType: String,
    val width: Int?,
    val height: Int?,
)

class ProOnDeviceVlmCoordinator(
    private val apiClient: NutonicApiClient,
    private val bearerAccessToken: String,
    private val modelCache: ProVlmModelCache = ProVlmModelCache(),
    private val engine: ProOnDeviceVlmEngine = createProOnDeviceVlmEngine(),
) {
    @Suppress("NestedBlockDepth")
    suspend fun run(
        job: ProJobStatusOut,
        userAsk: String = "",
        onStatus: (ProVlmStatus) -> Unit,
        /** Invoked with decoded model output and the same image bytes fed to the engine (for UI overlays). */
        onInferenceComplete: ((ProVlmResult, List<ProVlmPreparedImage>) -> Unit)? = null,
    ): ProVlmStatus {
        var failure: String? = null
        var ready: ProVlmStatus.Ready? = null
        if (job.status != "completed") {
            failure = "PRO job must be completed before local VLM runs."
        }
        val payload = job.onDevicePayload
        val imageRefs = payload?.vlmImageSet.orEmpty().ifEmpty { fallbackImageRefs(job) }
        if (failure == null && imageRefs.isEmpty()) {
            failure = "No VLM image set was attached to this PRO job."
        }

        var model: ProVlmCacheRecord? = null
        if (failure == null) {
            when (val prepared = prepareModel(payload?.modelBundleId, onStatus)) {
                is ApiResult.Ok -> model = prepared.value
                is ApiResult.HttpFailure -> failure = prepared.userMessage
                is ApiResult.NetworkFailure -> failure = "Model download failed: ${prepared.debugMessage}"
            }
        }

        val images = mutableListOf<ProVlmPreparedImage>()
        if (failure == null) {
            for (ref in imageRefs) {
                if (failure == null) {
                    when (val bytes = fetchImageBytes(job, ref)) {
                        is ApiResult.Ok ->
                            images +=
                                ProVlmPreparedImage(
                                    role = ref.role.ifBlank { "image" },
                                    bytes = bytes.value,
                                    mimeType = ref.mime ?: "application/octet-stream",
                                    width = ref.width,
                                    height = ref.height,
                                )
                        is ApiResult.HttpFailure -> {
                            failure = bytes.userMessage
                        }
                        is ApiResult.NetworkFailure -> {
                            failure = "Image download failed: ${bytes.debugMessage}"
                        }
                    }
                }
            }
        }

        if (failure == null) {
            val input =
                ProVlmPreparedInput(
                    prompt = buildPrompt(payload?.vlmPromptInjection, userAsk),
                    images = images,
                    model = checkNotNull(model),
                )
            onStatus(ProVlmStatus.LoadingModel)
            onStatus(ProVlmStatus.Inferencing)
            when (val result = engine.run(input)) {
                is ProOnDeviceVlmRunResult.Ok -> {
                    val parsed = parseVlmOutput(result.text, checkNotNull(model))
                    onInferenceComplete?.invoke(parsed, images.toList())
                    ready = ProVlmStatus.Ready(parsed)
                }
                is ProOnDeviceVlmRunResult.Unsupported -> failure = result.reason
                is ProOnDeviceVlmRunResult.Failed -> failure = result.reason
            }
        }

        val out = ready ?: ProVlmStatus.Failed(failure ?: "Unexpected VLM failure")
        return out.also(onStatus)
    }

    @Suppress("NestedBlockDepth")
    private suspend fun prepareModel(
        preferredModelBundleId: String?,
        onStatus: (ProVlmStatus) -> Unit,
    ): ApiResult<ProVlmCacheRecord> {
        val cached = modelCache.load()?.takeIf { preferredModelBundleId == null || it.modelBundleId == preferredModelBundleId }
        val stubEngine = engine as? DeterministicProOnDeviceVlmEngine
        if (cached != null &&
            cached.runtime.equals("leap", ignoreCase = true) &&
            stubEngine != null &&
            stubEngine.stubPrepareAllowed
        ) {
            return try {
                stubEngine.prepareModel(cached, null)
                ApiResult.Ok(cached)
            } catch (e: Exception) {
                ApiResult.NetworkFailure(e.message ?: "Web VLM stub prepare failed")
            }
        }
        if (cached != null && cached.runtime.equals("leap", ignoreCase = true) && supportsLiquidLeapOnDeviceVlm()) {
            return try {
                engine.prepareModel(cached, null)
                ApiResult.Ok(cached)
            } catch (e: Exception) {
                ApiResult.NetworkFailure(e.message ?: "Liquid Leap VLM prepare failed")
            }
        }
        if (cached != null) {
            val bundledBytes = loadBundledProVlmModelBytes(cached)
            if (bundledBytes != null) {
                engine.prepareModel(cached, bundledBytes)
                return ApiResult.Ok(cached)
            }
            if (proVlmVerifiedBundleExists(cached)) {
                engine.prepareModel(cached, null)
                return ApiResult.Ok(cached)
            }
        }
        val result: ApiResult<ProVlmCacheRecord> =
            run {
                val manifestResult = apiClient.getProVlmModelManifest(bearerAccessToken)
                val manifest = (manifestResult as? ApiResult.Ok)?.value
                if (manifest == null) {
                    when (manifestResult) {
                        is ApiResult.HttpFailure -> manifestResult
                        is ApiResult.NetworkFailure -> manifestResult
                        is ApiResult.Ok -> ApiResult.NetworkFailure("Unable to parse model manifest")
                    }
                } else if (preferredModelBundleId != null && manifest.modelBundleId != preferredModelBundleId) {
                    ApiResult.NetworkFailure(
                        "Server advertised ${manifest.modelBundleId}, but job requested $preferredModelBundleId",
                    )
                } else if (manifest.runtime.equals("leap", ignoreCase = true)) {
                    if (supportsLiquidLeapOnDeviceVlm()) {
                        val record =
                            ProVlmCacheRecord(
                                modelBundleId = manifest.modelBundleId,
                                revision = manifest.revision,
                                sha256 = manifest.sha256.lowercase(),
                                sizeBytes = manifest.sizeBytes,
                                runtime = manifest.runtime,
                            )
                        modelCache.save(record)
                        try {
                            engine.prepareModel(record, null)
                            ApiResult.Ok(record)
                        } catch (e: Exception) {
                            ApiResult.NetworkFailure(e.message ?: "Liquid Leap VLM initialization failed")
                        }
                    } else {
                        val leapStub = engine as? DeterministicProOnDeviceVlmEngine
                        if (leapStub != null && leapStub.stubPrepareAllowed) {
                            val record =
                                ProVlmCacheRecord(
                                    modelBundleId = manifest.modelBundleId,
                                    revision = manifest.revision,
                                    sha256 = manifest.sha256.lowercase(),
                                    sizeBytes = manifest.sizeBytes,
                                    runtime = manifest.runtime,
                                )
                            modelCache.save(record)
                            try {
                                leapStub.prepareModel(record, null)
                                ApiResult.Ok(record)
                            } catch (e: Exception) {
                                ApiResult.NetworkFailure(e.message ?: "Web VLM stub prepare failed")
                            }
                        } else {
                            ApiResult.NetworkFailure(
                                "Liquid Leap on-device VLM is not available on this target (use Android, iOS, or desktop).",
                            )
                        }
                    }
                } else {
                    withContext(Dispatchers.Default) {
                        val digest = SHA256()
                        val writer =
                            ProVlmModelCacheWriter(
                                manifest.modelBundleId,
                                manifest.revision,
                            )
                        if (!writer.open()) {
                            return@withContext ApiResult.NetworkFailure(
                                "Cannot prepare on-device model cache on this platform.",
                            )
                        }
                        try {
                            val dl =
                                apiClient.downloadAuthenticatedStreaming(
                                    manifest.downloadUrl,
                                    bearerAccessToken,
                                    onProgress = { received, total ->
                                        onStatus(ProVlmStatus.DownloadingModel(received, total))
                                    },
                                    onChunk = { buf, off, len ->
                                        digest.update(buf, off, len)
                                        writer.write(buf, off, len)
                                    },
                                )
                            when (dl) {
                                is ApiResult.Ok -> {
                                    val shaHex = digestToHexLowercase(digest.digest())
                                    val verification =
                                        verifyDownloadedModel(manifest, dl.value, shaHex)
                                    if (verification != null) {
                                        writer.abort()
                                        ApiResult.NetworkFailure(verification)
                                    } else {
                                        writer.commit()
                                        val record =
                                            ProVlmCacheRecord(
                                                modelBundleId = manifest.modelBundleId,
                                                revision = manifest.revision,
                                                sha256 = manifest.sha256.lowercase(),
                                                sizeBytes = manifest.sizeBytes,
                                                runtime = manifest.runtime,
                                            )
                                        modelCache.save(record)
                                        engine.prepareModel(record, null)
                                        ApiResult.Ok(record)
                                    }
                                }

                                is ApiResult.HttpFailure -> {
                                    writer.abort()
                                    dl
                                }

                                is ApiResult.NetworkFailure -> {
                                    writer.abort()
                                    dl
                                }
                            }
                        } catch (e: CancellationException) {
                            writer.abort()
                            throw e
                        } catch (e: Exception) {
                            writer.abort()
                            ApiResult.NetworkFailure(e.message ?: "model download failed")
                        }
                    }
                }
            }
        return result
    }

    private suspend fun fetchImageBytes(
        job: ProJobStatusOut,
        ref: ProVlmImageRef,
    ): ApiResult<ByteArray> {
        val url = ref.url ?: ref.inlineRef
        if (!url.isNullOrBlank()) {
            return apiClient.getProArtifactByUrl(url, bearerAccessToken)
        }
        val artifactId = ref.artifactId
        if (!artifactId.isNullOrBlank()) {
            return apiClient.getProArtifact(job.jobId, artifactId, bearerAccessToken)
        }
        return ApiResult.NetworkFailure("VLM image ${ref.role} has no URL or artifact_id")
    }
}

class ProVlmModelCache(
    private val store: Utf8BlobStore = createProVlmModelBlobStore(),
) {
    suspend fun load(): ProVlmCacheRecord? =
        store.load()?.let {
            runCatching { ProVlmJson.decodeFromString(ProVlmCacheRecord.serializer(), it) }.getOrNull()
        }

    suspend fun save(record: ProVlmCacheRecord) {
        store.save(ProVlmJson.encodeToString(ProVlmCacheRecord.serializer(), record))
    }
}

sealed class ProOnDeviceVlmRunResult {
    data class Ok(
        val text: String,
    ) : ProOnDeviceVlmRunResult()

    data class Unsupported(
        val reason: String,
    ) : ProOnDeviceVlmRunResult()

    data class Failed(
        val reason: String,
    ) : ProOnDeviceVlmRunResult()
}

interface ProOnDeviceVlmEngine {
    /**
     * @param bundleBytes when non-null, bundle payload held in memory (bundled assets only).
     * When null, [proVlmVerifiedBundleExists] must be true (disk cache after streaming download).
     */
    suspend fun prepareModel(
        cacheRecord: ProVlmCacheRecord,
        bundleBytes: ByteArray? = null,
    )

    suspend fun run(input: ProVlmPreparedInput): ProOnDeviceVlmRunResult
}

class DeterministicProOnDeviceVlmEngine(
    private val runtimeName: String,
    /** Kotlin/JS: allow manifest-only prepare and demo overlay boxes (no Liquid Leap artifact). */
    private val allowPrepareWithoutVerifiedBundle: Boolean = false,
) : ProOnDeviceVlmEngine {
    /** True when [allowPrepareWithoutVerifiedBundle] is enabled (web preview path). */
    val stubPrepareAllowed: Boolean get() = allowPrepareWithoutVerifiedBundle

    private var prepared: ProVlmCacheRecord? = null

    override suspend fun prepareModel(
        cacheRecord: ProVlmCacheRecord,
        bundleBytes: ByteArray?,
    ) {
        prepared = cacheRecord
        when {
            bundleBytes != null -> require(bundleBytes.isNotEmpty()) { "Model bundle is empty" }
            allowPrepareWithoutVerifiedBundle -> Unit
            else ->
                require(proVlmVerifiedBundleExists(cacheRecord)) {
                    "Model bundle is missing or empty"
                }
        }
    }

    override suspend fun run(input: ProVlmPreparedInput): ProOnDeviceVlmRunResult {
        val model = prepared ?: input.model
        val stubBoxes =
            if (allowPrepareWithoutVerifiedBundle) {
                listOf(
                    ProVlmBoundingBox(
                        label = "preview",
                        bbox = listOf(0.08, 0.08, 0.42, 0.38),
                        confidence = 0.75,
                    ),
                    ProVlmBoundingBox(
                        label = "preview",
                        bbox = listOf(0.52, 0.42, 0.92, 0.88),
                        confidence = 0.65,
                    ),
                )
            } else {
                emptyList()
            }
        val caption =
            if (allowPrepareWithoutVerifiedBundle) {
                buildString {
                    append(
                        "Preview — full Liquid Leap inference runs on Android, iOS, or desktop. ",
                    )
                    append(input.images.size)
                    append(if (input.images.size == 1) " image (demo overlays)." else " images (demo overlays).")
                }
            } else {
                buildString {
                    val roles = input.images.map { it.role.ifBlank { "image" } }.distinct().take(4)
                    append(input.prompt.take(1500))
                    if (roles.isNotEmpty()) {
                        append(" | image_roles=")
                        append(roles.joinToString(","))
                    }
                    append(" | ")
                    append(input.images.size)
                    append(if (input.images.size == 1) " image" else " images")
                    append(" · ")
                    append(runtimeName)
                    append(" (non-neural stub — Android uses Liquid Leap).")
                }
            }
        return ProOnDeviceVlmRunResult.Ok(
            ProVlmJson.encodeToString(
                ProVlmResult.serializer(),
                ProVlmResult(
                    caption = caption,
                    boxes = stubBoxes,
                    modelBundleId = model.modelBundleId,
                    revision = model.revision,
                    source =
                        if (allowPrepareWithoutVerifiedBundle) {
                            "on_device_vlm_web_preview"
                        } else {
                            "on_device_vlm_verified_bundle"
                        },
                ),
            ),
        )
    }
}

expect fun createProOnDeviceVlmEngine(): ProOnDeviceVlmEngine

expect suspend fun loadBundledProVlmModelBytes(record: ProVlmCacheRecord): ByteArray?

expect suspend fun loadCachedProVlmModelBytes(record: ProVlmCacheRecord): ByteArray?

expect suspend fun saveCachedProVlmModelBytes(
    record: ProVlmCacheRecord,
    bytes: ByteArray,
)

private fun promptInjectionValueText(
    key: String,
    element: JsonElement,
): String {
    val maxChars =
        when (key) {
            "run_manifest", "tim_summary" -> 12_000
            "tim_context_block" -> 14_000
            "product" -> 2_000
            else -> 1_200
        }
    val encoded =
        when {
            element is JsonPrimitive && element.isString -> element.content
            else -> VlmPromptInjectJson.encodeToString(JsonElement.serializer(), element)
        }
    return encoded.take(maxChars)
}

private val vlmPromptInjectionKeyOrder =
    listOf(
        "product",
        "tim_context_block",
        "run_manifest",
        "tim_summary",
    )

fun buildPrompt(
    promptInjection: JsonObject?,
    userAsk: String,
): String {
    val safeAsk =
        userAsk
            .filterNot { it.code < 32 && it != '\n' && it != '\t' }
            .take(MAX_PROMPT_CHARS)
    val injected =
        promptInjection?.let { obj ->
            val seen = mutableSetOf<String>()
            val ordered =
                buildList {
                    for (k in vlmPromptInjectionKeyOrder) {
                        if (k in obj && seen.add(k)) add(k)
                    }
                    for (k in obj.keys.sorted()) {
                        if (seen.add(k)) add(k)
                    }
                }
            ordered.joinToString("\n\n") { key ->
                val value = obj[key] ?: return@joinToString ""
                "$key:\n${promptInjectionValueText(key, value)}"
            }
        }.orEmpty()
    return listOf(
        ProModelPromptContract.ON_DEVICE_VLM_USER_INSTRUCTION_LINES,
        injected,
        safeAsk.takeIf { it.isNotBlank() }?.let { "User ask: $it" }.orEmpty(),
        ProModelPromptContract.ASSESSMENT_TASK_FOOTER,
    ).filter { it.isNotBlank() }.joinToString("\n")
}

fun parseVlmOutput(
    raw: String,
    model: ProVlmCacheRecord = ProVlmCacheRecord(DEFAULT_MODEL_BUNDLE_ID, "unknown", "", 0, "unknown"),
): ProVlmResult {
    val parsed = parseJsonCandidate(raw)
    val caption =
        parsed
            ?.let { obj ->
                obj["caption"]?.jsonPrimitive?.contentOrNull
                    ?: obj["summary"]?.jsonPrimitive?.contentOrNull
            }
            ?: raw.substringBefore("{").trim().ifBlank { raw.take(500) }
    val boxes = parsed?.let(::boxesFromJson).orEmpty()
    return ProVlmResult(
        caption = caption.take(2000),
        boxes = boxes,
        modelBundleId = model.modelBundleId,
        revision = model.revision,
        source = "on_device_vlm",
    )
}

private fun digestToHexLowercase(digestBytes: ByteArray): String =
    digestBytes.joinToString("") { b -> (b.toInt() and 0xff).toString(16).padStart(2, '0') }

fun verifyDownloadedModel(
    manifest: ProVlmModelManifest,
    downloadedByteCount: Long,
    sha256HexLowercase: String,
): String? {
    val expected = manifest.sha256.trim().lowercase()
    return when {
        manifest.sizeBytes >= 0 && downloadedByteCount != manifest.sizeBytes ->
            "Downloaded model size mismatch for ${manifest.modelBundleId}"
        expected.isBlank() -> "Model manifest is missing sha256"
        sha256HexLowercase != expected ->
            "Downloaded model sha256 mismatch for ${manifest.modelBundleId}"
        manifest.contractIds.isEmpty() -> "Model manifest is missing supported contract ids"
        DEFAULT_CONTRACT_ID !in manifest.contractIds ->
            "Model manifest does not support $DEFAULT_CONTRACT_ID"
        else -> null
    }
}

fun verifyModelBytes(
    manifest: ProVlmModelManifest,
    bytes: ByteArray,
): String? = verifyDownloadedModel(manifest, bytes.size.toLong(), sha256Hex(bytes))

expect fun sha256Hex(bytes: ByteArray): String

private fun fallbackImageRefs(job: ProJobStatusOut): List<ProVlmImageRef> =
    mergedArtifacts(job)
        .filter { it.kind == "image" || it.mimeType.startsWith("image/") }
        .take(4)
        .map {
            ProVlmImageRef(
                role = it.artifactId,
                artifactId = it.artifactId,
                url = it.downloadUrl,
                mime = it.mimeType,
            )
        }

private fun mergedArtifacts(job: ProJobStatusOut): List<ProArtifactRef> =
    buildList {
        addAll(job.artifacts.orEmpty())
        addAll(job.analysisArtifacts.orEmpty())
        addAll(job.briefArtifacts.orEmpty())
    }.distinctBy { it.artifactId }

private fun parseJsonCandidate(raw: String): JsonObject? {
    val trimmed = raw.trim()
    val direct = runCatching { ProVlmJson.parseToJsonElement(trimmed).jsonObject }.getOrNull()
    if (direct != null) {
        return direct
    }
    val start = trimmed.indexOf('{')
    val end = trimmed.lastIndexOf('}')
    if (start < 0 || end <= start) {
        return null
    }
    return runCatching { ProVlmJson.parseToJsonElement(trimmed.substring(start, end + 1)).jsonObject }.getOrNull()
}

private fun boxesFromJson(obj: JsonObject): List<ProVlmBoundingBox> {
    val rawBoxes =
        when (val value = obj["boxes"] ?: obj["bboxes"] ?: obj["detections"]) {
            is JsonArray -> value
            else -> return emptyList()
        }
    return rawBoxes.mapNotNull { element ->
        val boxObj = element as? JsonObject ?: return@mapNotNull null
        val label =
            boxObj["label"]?.jsonPrimitive?.contentOrNull
                ?: boxObj["class"]?.jsonPrimitive?.contentOrNull
                ?: return@mapNotNull null
        val bbox =
            (boxObj["bbox"] ?: boxObj["box"])
                ?.jsonArray
                ?.mapNotNull { it.jsonPrimitive.doubleOrNull }
                ?.takeIf { it.size == 4 }
                ?.map { it.coerceIn(0.0, 1.0) }
                ?: return@mapNotNull null
        val confidence = boxObj["confidence"]?.jsonPrimitive?.doubleOrNull ?: boxObj["score"]?.jsonPrimitive?.doubleOrNull
        val visible = boxObj["visible"]?.jsonPrimitive?.booleanOrNull ?: true
        if (!visible) {
            null
        } else {
            ProVlmBoundingBox(label = label.take(80), bbox = bbox, confidence = confidence?.coerceIn(0.0, 1.0))
        }
    }
}
