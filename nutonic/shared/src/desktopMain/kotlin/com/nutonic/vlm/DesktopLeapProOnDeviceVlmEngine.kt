package com.nutonic.vlm

import ai.liquid.leap.ModelRunner
import ai.liquid.leap.ModelLoadingOptions
import ai.liquid.leap.manifest.GenerationTimeParameters
import ai.liquid.leap.manifest.LeapDownloader
import ai.liquid.leap.manifest.LeapDownloaderConfig
import ai.liquid.leap.manifest.ModelSource
import ai.liquid.leap.manifest.SamplingParameters
import ai.liquid.leap.message.ChatMessage
import ai.liquid.leap.message.ChatMessageContent
import ai.liquid.leap.message.MessageResponse
import com.nutonic.pro.ProModelPromptContract
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.jetbrains.skia.EncodedImageFormat
import org.jetbrains.skia.Image
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.Path
import kotlin.io.path.createDirectories
import kotlin.io.path.exists
import kotlin.io.path.isRegularFile
import kotlin.io.path.readText

/**
 * JVM / Compose Desktop on-device VLM via Liquid Leap ([LeapDownloader] + [ModelRunner]).
 * Uses the same prompt + multi-image message layout as Android.
 */
internal class DesktopLeapProOnDeviceVlmEngine : ProOnDeviceVlmEngine {
    private var runner: ModelRunner? = null
    private var preparedKey: String? = null

    override suspend fun prepareModel(
        cacheRecord: ProVlmCacheRecord,
        bundleBytes: ByteArray?,
    ) {
        if (bundleBytes != null) {
            require(bundleBytes.isNotEmpty()) { "Model bundle is empty" }
        }
        val modelName = LiquidLeapModelIds.modelName(cacheRecord)
        val quant = LiquidLeapModelIds.quantization(cacheRecord)
        val manifestUrl = LiquidLeapModelIds.manifestUrl(cacheRecord)
        val key = "$modelName|$quant"
        if (runner != null && preparedKey == key) {
            return
        }
        val saveDir =
            Path(System.getProperty("user.home"), ".nutonic", "leap_models").also {
                it.createDirectories()
            }
        val downloader =
            LeapDownloader(
                LeapDownloaderConfig(saveDir = saveDir.toString()),
            )
        val loaded =
            withContext(Dispatchers.IO) {
                try {
                    downloader.downloadModelFromManifestUrl(
                        manifestUrl = manifestUrl,
                        progress = {},
                    )
                    val cacheFolder = findManifestCacheFolder(saveDir, manifestUrl)
                    val modelPath = cacheFolder.resolve("$modelName-$quant.gguf")
                    val mmprojPath = cacheFolder.resolve("mmproj-${modelName.replace("450M", "450m")}-$quant.gguf")
                    require(modelPath.isRegularFile()) {
                        "Liquid Leap model file is missing: $modelPath"
                    }
                    require(mmprojPath.isRegularFile()) {
                        "Liquid Leap multimodal projector is missing: $mmprojPath"
                    }
                    downloader.loadSimpleModel(
                        model =
                            ModelSource(
                                modelPath.toString(),
                                mmprojPath.toString(),
                                null,
                                null,
                                modelName,
                                quant,
                            ),
                        modelLoadingOptions = ModelLoadingOptions(),
                        generationTimeParameters =
                            GenerationTimeParameters(
                                SamplingParameters(
                                    temperature = 0.1,
                                    topP = null,
                                    minP = 0.15,
                                    repetitionPenalty = 1.05,
                                    topK = null,
                                ),
                            ),
                        false,
                        progress = {},
                    )
                } catch (e: Exception) {
                    e.printStackTrace()
                    throw IllegalStateException(
                        "Liquid Leap could not open model bundle from $manifestUrl: ${e.message ?: e::class.simpleName}",
                        e,
                    )
                }
            }
        runner = loaded
        preparedKey = key
    }

    override suspend fun run(input: ProVlmPreparedInput): ProOnDeviceVlmRunResult =
        withContext(Dispatchers.IO) {
            val r = runner ?: return@withContext ProOnDeviceVlmRunResult.Failed("PRO VLM is not prepared")
            try {
                val systemPreamble =
                    input.leapSystemPreamble ?: ProModelPromptContract.LEAP_CHAT_SYSTEM_PREAMBLE
                val conversation = r.createConversation(systemPreamble)
                val contents =
                    buildList {
                        add(ChatMessageContent.Text(input.prompt))
                        for (img in input.images) {
                            add(ChatMessageContent.Image(img.bytes.toLeapJpegBytes()))
                        }
                    }
                val userMessage =
                    ChatMessage(
                        role = ChatMessage.Role.USER,
                        content = contents,
                    )
                val chunks = StringBuilder()
                var completedText: String? = null
                conversation.generateResponse(userMessage).collect { resp ->
                    when (resp) {
                        is MessageResponse.Chunk -> chunks.append(resp.text)
                        is MessageResponse.Complete -> {
                            val first = resp.fullMessage.content.firstOrNull()
                            if (first is ChatMessageContent.Text) {
                                completedText = first.text
                            }
                        }
                        else -> {}
                    }
                }
                val raw =
                    completedText?.takeIf { it.isNotBlank() } ?: chunks.toString()
                if (raw.isBlank()) {
                    ProOnDeviceVlmRunResult.Failed("Liquid Leap returned an empty response")
                } else {
                    ProOnDeviceVlmRunResult.Ok(raw)
                }
            } catch (e: Exception) {
                e.printStackTrace()
                ProOnDeviceVlmRunResult.Failed(
                    e.message ?: "${e::class.simpleName ?: "Exception"} during Liquid Leap inference",
                )
            }
        }

    private fun ByteArray.toLeapJpegBytes(): ByteArray {
        if (isJpeg()) return this
        val image = Image.makeFromEncoded(this)
        return try {
            val data =
                image.encodeToData(EncodedImageFormat.JPEG, 92)
                    ?: error("Could not encode image as JPEG for Liquid Leap")
            try {
                data.bytes
            } finally {
                data.close()
            }
        } finally {
            image.close()
        }
    }

    private fun ByteArray.isJpeg(): Boolean =
        size >= 3 &&
            this[0] == 0xFF.toByte() &&
            this[1] == 0xD8.toByte() &&
            this[2] == 0xFF.toByte()

    private fun findManifestCacheFolder(
        saveDir: Path,
        manifestUrl: String,
    ): Path {
        Files.newDirectoryStream(saveDir, "manifest-*").use { stream ->
            for (candidate in stream) {
                if (!Files.isDirectory(candidate)) continue
                Files.newDirectoryStream(candidate, "*.json").use { jsonFiles ->
                    for (json in jsonFiles) {
                        if (json.exists() && json.readText().contains(manifestUrl)) {
                            return candidate
                        }
                    }
                }
            }
        }
        error("Could not find cached Liquid Leap manifest folder for $manifestUrl in $saveDir")
    }
}
