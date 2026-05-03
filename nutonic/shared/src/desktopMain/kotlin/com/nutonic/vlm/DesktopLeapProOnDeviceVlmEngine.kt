package com.nutonic.vlm

import ai.liquid.leap.ModelRunner
import ai.liquid.leap.manifest.LeapDownloader
import ai.liquid.leap.manifest.LeapDownloaderConfig
import ai.liquid.leap.message.ChatMessage
import ai.liquid.leap.message.ChatMessageContent
import ai.liquid.leap.message.MessageResponse
import com.nutonic.pro.ProModelPromptContract
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.io.path.Path
import kotlin.io.path.createDirectories

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
                downloader.loadModel(
                    modelName = modelName,
                    quantizationSlug = quant,
                    progress = {},
                )
            }
        runner = loaded
        preparedKey = key
    }

    override suspend fun run(input: ProVlmPreparedInput): ProOnDeviceVlmRunResult =
        withContext(Dispatchers.IO) {
            val r = runner ?: return@withContext ProOnDeviceVlmRunResult.Failed("PRO VLM is not prepared")
            try {
                val systemPreamble = ProModelPromptContract.LEAP_CHAT_SYSTEM_PREAMBLE
                val conversation = r.createConversation(systemPreamble)
                val contents =
                    buildList {
                        add(ChatMessageContent.Text(input.prompt))
                        for (img in input.images) {
                            add(ChatMessageContent.Image(img.bytes))
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
                ProOnDeviceVlmRunResult.Failed(e.message ?: "Liquid Leap inference failed")
            }
        }
}
