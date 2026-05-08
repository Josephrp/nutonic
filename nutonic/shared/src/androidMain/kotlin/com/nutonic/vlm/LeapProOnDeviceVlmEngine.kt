package com.nutonic.vlm

import ai.liquid.leap.ModelRunner
import ai.liquid.leap.downloader.LeapModelDownloader
import ai.liquid.leap.downloader.LeapModelDownloaderNotificationConfig
import ai.liquid.leap.message.ChatMessage
import ai.liquid.leap.message.ChatMessageContent
import ai.liquid.leap.message.MessageResponse
import com.nutonic.AndroidNutonicAppContext
import com.nutonic.pro.ProModelPromptContract
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * On-device VLM using Liquid Leap ([ModelRunner]) — same stack as [refs/VLMExample].
 * One user message contains the full text prompt plus every EO image as [ChatMessageContent.Image] bytes.
 */
internal class LeapProOnDeviceVlmEngine : ProOnDeviceVlmEngine {
    private var runner: ModelRunner? = null
    private var preparedKey: String? = null

    override suspend fun prepareModel(
        cacheRecord: ProVlmCacheRecord,
        bundleBytes: ByteArray?,
    ) {
        if (bundleBytes != null) {
            require(bundleBytes.isNotEmpty()) { "Model bundle is empty" }
        }
        val ctx =
            checkNotNull(AndroidNutonicAppContext.application) {
                "Application context is not set; cannot load Liquid Leap VLM"
            }
        val modelName = LiquidLeapModelIds.modelName(cacheRecord)
        val quant = LiquidLeapModelIds.quantization(cacheRecord)
        val key = "$modelName|$quant"
        if (runner != null && preparedKey == key) {
            return
        }
        withContext(Dispatchers.Main) {
            val downloader =
                LeapModelDownloader(
                    ctx,
                    notificationConfig =
                        LeapModelDownloaderNotificationConfig.build {
                            notificationTitleDownloading = "Downloading PRO on-device VLM"
                            notificationTitleDownloaded = "PRO VLM ready"
                        },
                )
            when (downloader.queryStatus(modelName, quant)) {
                is LeapModelDownloader.ModelDownloadStatus.NotOnLocal -> {
                    downloader.requestDownloadModel(modelName, quant)
                    waitForLeapModelReady(downloader, modelName, quant)
                }
                is LeapModelDownloader.ModelDownloadStatus.DownloadInProgress -> {
                    waitForLeapModelReady(downloader, modelName, quant)
                }
                is LeapModelDownloader.ModelDownloadStatus.Downloaded -> Unit
            }
            val loaded = downloader.loadModel(modelName, quant)
            runner = loaded
            preparedKey = key
        }
    }

    override suspend fun run(input: ProVlmPreparedInput): ProOnDeviceVlmRunResult =
        withContext(Dispatchers.Main) {
            val r = runner ?: return@withContext ProOnDeviceVlmRunResult.Failed("PRO VLM is not prepared")
            try {
                val systemPreamble =
                    input.leapSystemPreamble ?: ProModelPromptContract.LEAP_CHAT_SYSTEM_PREAMBLE
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

    private suspend fun waitForLeapModelReady(
        downloader: LeapModelDownloader,
        modelName: String,
        quant: String,
    ) {
        repeat(24_000) {
            when (downloader.queryStatus(modelName, quant)) {
                is LeapModelDownloader.ModelDownloadStatus.Downloaded -> return
                else -> delay(250)
            }
        }
        error("Timed out waiting for Liquid Leap model download")
    }
}
