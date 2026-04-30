package com.nutonic.pro

import com.nutonic.api.NutonicJson
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ProEvidenceBundleManifest(
    val schema: String,
    @SerialName("job_id") val jobId: String,
    val status: String,
    @SerialName("analysis_profile") val analysisProfile: String,
    @SerialName("on_device_payload") val onDevicePayload: ProBundleOnDevicePayload? = null,
    val artifacts: List<ProEvidenceBundleArtifact> = emptyList(),
)

@Serializable
data class ProBundleOnDevicePayload(
    @SerialName("vlm_image_set") val vlmImageSet: List<ProBundleVlmImageRef> = emptyList(),
)

@Serializable
data class ProBundleVlmImageRef(
    val role: String? = null,
    @SerialName("artifact_id") val artifactId: String? = null,
)

@Serializable
data class ProEvidenceBundleArtifact(
    @SerialName("artifact_id") val artifactId: String,
    val kind: String,
    @SerialName("mime_type") val mimeType: String,
    val category: String? = null,
    val path: String? = null,
    val sha256: String? = null,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    val missing: Boolean = false,
)

data class ProEvidenceBundlePreview(
    val sizeBytes: Int,
    val manifest: ProEvidenceBundleManifest?,
    val items: List<ProEvidenceBundleItem> = emptyList(),
    val error: String? = null,
)

data class ProEvidenceBundleItem(
    val artifact: ProEvidenceBundleArtifact,
    val bytes: ByteArray,
)

fun parseStoredProEvidenceBundle(bytes: ByteArray): ProEvidenceBundlePreview {
    val entries = readStoredZipEntries(bytes)
        ?: return ProEvidenceBundlePreview(sizeBytes = bytes.size, manifest = null, error = "Bundle zip parse failed")
    val manifestBytes = entries["pro_bundle_manifest.json"]
        ?: return ProEvidenceBundlePreview(sizeBytes = bytes.size, manifest = null, error = "Bundle manifest missing")
    val manifest = runCatching {
        NutonicJson.decodeFromString(ProEvidenceBundleManifest.serializer(), manifestBytes.decodeToString())
    }.getOrElse {
        return ProEvidenceBundlePreview(sizeBytes = bytes.size, manifest = null, error = "Bundle manifest parse failed: ${it.message}")
    }
    val items =
        manifest.artifacts.mapNotNull { artifact ->
            val path = artifact.path ?: return@mapNotNull null
            val artifactBytes = entries[path] ?: return@mapNotNull null
            ProEvidenceBundleItem(artifact = artifact, bytes = artifactBytes)
        }
    return ProEvidenceBundlePreview(sizeBytes = bytes.size, manifest = manifest, items = items)
}

private fun readStoredZipEntries(bytes: ByteArray): Map<String, ByteArray>? {
    val entries = mutableMapOf<String, ByteArray>()
    var offset = 0
    while (offset + 4 <= bytes.size) {
        val signature = bytes.u32(offset)
        if (signature == ZIP_CENTRAL_DIRECTORY_SIGNATURE || signature == ZIP_END_SIGNATURE) {
            break
        }
        if (signature != ZIP_LOCAL_FILE_SIGNATURE || offset + 30 > bytes.size) {
            return null
        }
        val flags = bytes.u16(offset + 6)
        val method = bytes.u16(offset + 8)
        if (flags and ZIP_DATA_DESCRIPTOR_FLAG != 0 || method != ZIP_STORED_METHOD) {
            return null
        }
        val compressedSize = bytes.u32(offset + 18)
        val nameLen = bytes.u16(offset + 26)
        val extraLen = bytes.u16(offset + 28)
        val nameStart = offset + 30
        val dataStart = nameStart + nameLen + extraLen
        val dataEndLong = dataStart.toLong() + compressedSize.toLong()
        if (nameStart > bytes.size || dataStart > bytes.size || dataEndLong > bytes.size) {
            return null
        }
        val name = bytes.copyOfRange(nameStart, nameStart + nameLen).decodeToString()
        if (!name.endsWith("/")) {
            entries[name] = bytes.copyOfRange(dataStart, dataEndLong.toInt())
        }
        offset = dataEndLong.toInt()
    }
    return entries
}

private const val ZIP_LOCAL_FILE_SIGNATURE = 0x04034b50u
private const val ZIP_CENTRAL_DIRECTORY_SIGNATURE = 0x02014b50u
private const val ZIP_END_SIGNATURE = 0x06054b50u
private const val ZIP_STORED_METHOD = 0
private const val ZIP_DATA_DESCRIPTOR_FLAG = 0x0008

private fun ByteArray.u16(offset: Int): Int =
    (this[offset].toInt() and 0xff) or
        ((this[offset + 1].toInt() and 0xff) shl 8)

private fun ByteArray.u32(offset: Int): UInt =
    ((this[offset].toInt() and 0xff).toUInt()) or
        ((this[offset + 1].toInt() and 0xff).toUInt() shl 8) or
        ((this[offset + 2].toInt() and 0xff).toUInt() shl 16) or
        ((this[offset + 3].toInt() and 0xff).toUInt() shl 24)

expect fun parseProEvidenceBundle(bytes: ByteArray): ProEvidenceBundlePreview
