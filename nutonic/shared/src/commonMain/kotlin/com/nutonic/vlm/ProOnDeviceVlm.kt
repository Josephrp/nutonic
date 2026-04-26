package com.nutonic.vlm

import com.nutonic.api.ApiResult
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.ProArtifactRef
import com.nutonic.api.ProJobStatusOut
import com.nutonic.api.ProVlmImageRef
import com.nutonic.api.ProVlmModelManifest
import com.nutonic.persistence.Utf8BlobStore
import com.nutonic.persistence.createProVlmModelBlobStore
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

private const val DEFAULT_MODEL_BUNDLE_ID = "nutonic.pro.vlm.remote.v1"
private const val DEFAULT_CONTRACT_ID = "nutonic.pro.vlm.v1_512"
private const val MAX_PROMPT_CHARS = 500

private val ProVlmJson =
    Json {
        ignoreUnknownKeys = true
        explicitNulls = false
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
    suspend fun run(
        job: ProJobStatusOut,
        userAsk: String = "",
        onStatus: (ProVlmStatus) -> Unit,
    ): ProVlmStatus {
        if (job.status != "completed") {
            return ProVlmStatus.Failed("PRO job must be completed before local VLM runs.").also(onStatus)
        }
        val payload = job.onDevicePayload
        val imageRefs = payload?.vlmImageSet.orEmpty().ifEmpty { fallbackImageRefs(job) }
        if (imageRefs.isEmpty()) {
            return ProVlmStatus.Failed("No VLM image set was attached to this PRO job.").also(onStatus)
        }

        val model =
            when (val prepared = prepareModel(payload?.modelBundleId, onStatus)) {
                is ApiResult.Ok -> prepared.value
                is ApiResult.HttpFailure -> return ProVlmStatus.Failed(prepared.userMessage).also(onStatus)
                is ApiResult.NetworkFailure -> return ProVlmStatus.Failed("Model download failed: ${prepared.debugMessage}").also(onStatus)
            }

        val images = mutableListOf<ProVlmPreparedImage>()
        for (ref in imageRefs) {
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
                is ApiResult.HttpFailure -> return ProVlmStatus.Failed(bytes.userMessage).also(onStatus)
                is ApiResult.NetworkFailure -> return ProVlmStatus.Failed("Image download failed: ${bytes.debugMessage}").also(onStatus)
            }
        }

        val input =
            ProVlmPreparedInput(
                prompt = buildPrompt(payload?.vlmPromptInjection, userAsk),
                images = images,
                model = model,
            )

        onStatus(ProVlmStatus.LoadingModel)
        onStatus(ProVlmStatus.Inferencing)
        val raw =
            when (val result = engine.run(input)) {
                is ProOnDeviceVlmRunResult.Ok -> result.text
                is ProOnDeviceVlmRunResult.Unsupported ->
                    return ProVlmStatus.Failed(result.reason).also(onStatus)
                is ProOnDeviceVlmRunResult.Failed ->
                    return ProVlmStatus.Failed(result.reason).also(onStatus)
            }
        return ProVlmStatus.Ready(parseVlmOutput(raw, model)).also(onStatus)
    }

    private suspend fun prepareModel(
        preferredModelBundleId: String?,
        onStatus: (ProVlmStatus) -> Unit,
    ): ApiResult<ProVlmCacheRecord> {
        val cached = modelCache.load()
        if (cached != null && (preferredModelBundleId == null || cached.modelBundleId == preferredModelBundleId)) {
            return ApiResult.Ok(cached)
        }
        val manifest =
            when (val result = apiClient.getProVlmModelManifest(bearerAccessToken)) {
                is ApiResult.Ok -> result.value
                is ApiResult.HttpFailure -> return result
                is ApiResult.NetworkFailure -> return result
            }
        if (preferredModelBundleId != null && manifest.modelBundleId != preferredModelBundleId) {
            return ApiResult.NetworkFailure(
                "Server advertised ${manifest.modelBundleId}, but job requested $preferredModelBundleId",
            )
        }
        val bytes =
            when (
                val result =
                    apiClient.getProVlmModelBytes(
                        manifest.downloadUrl,
                        bearerAccessToken,
                    ) { received, total -> onStatus(ProVlmStatus.DownloadingModel(received, total)) }
            ) {
                is ApiResult.Ok -> result.value
                is ApiResult.HttpFailure -> return result
                is ApiResult.NetworkFailure -> return result
            }
        val verification = verifyModelBytes(manifest, bytes)
        if (verification != null) {
            return ApiResult.NetworkFailure(verification)
        }
        val record =
            ProVlmCacheRecord(
                modelBundleId = manifest.modelBundleId,
                revision = manifest.revision,
                sha256 = manifest.sha256.lowercase(),
                sizeBytes = manifest.sizeBytes,
                runtime = manifest.runtime,
            )
        modelCache.save(record)
        engine.prepareModel(bytes, record)
        return ApiResult.Ok(record)
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
    suspend fun prepareModel(
        bytes: ByteArray,
        cacheRecord: ProVlmCacheRecord,
    )

    suspend fun run(input: ProVlmPreparedInput): ProOnDeviceVlmRunResult
}

expect fun createProOnDeviceVlmEngine(): ProOnDeviceVlmEngine

fun buildPrompt(
    promptInjection: JsonObject?,
    userAsk: String,
): String {
    val safeAsk =
        userAsk
            .filterNot { it.code < 32 && it != '\n' && it != '\t' }
            .take(MAX_PROMPT_CHARS)
    val injected =
        promptInjection
            ?.entries
            ?.sortedBy { it.key }
            ?.joinToString("\n") { (key, value) -> "$key: ${value.toString().take(600)}" }
            .orEmpty()
    return listOf(
        "You are NU:TONIC PRO local vision. Describe the provided EO image set.",
        "Return a concise caption followed by strict JSON with key `boxes`.",
        "Each box must be `{label,bbox,confidence}` with bbox normalized [x1,y1,x2,y2] in 0..1.",
        injected,
        safeAsk.takeIf { it.isNotBlank() }?.let { "User ask: $it" }.orEmpty(),
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

fun verifyModelBytes(
    manifest: ProVlmModelManifest,
    bytes: ByteArray,
): String? {
    if (manifest.sizeBytes >= 0 && bytes.size.toLong() != manifest.sizeBytes) {
        return "Downloaded model size mismatch for ${manifest.modelBundleId}"
    }
    val expected = manifest.sha256.trim().lowercase()
    if (expected.isBlank()) {
        return "Model manifest is missing sha256"
    }
    val actual = sha256Hex(bytes)
    if (actual != expected) {
        return "Downloaded model sha256 mismatch for ${manifest.modelBundleId}"
    }
    if (manifest.contractIds.isEmpty()) {
        return "Model manifest is missing supported contract ids"
    }
    if (DEFAULT_CONTRACT_ID !in manifest.contractIds) {
        return "Model manifest does not support $DEFAULT_CONTRACT_ID"
    }
    return null
}

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

