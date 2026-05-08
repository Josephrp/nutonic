import Foundation
import UIKit
import LeapSDK
import shared

/// Swift implementation of `IosVlmBridge` (exported from Kotlin/Native).
///
/// Uses the Swift Leap SDK (leap-ios) to run multimodal generation on-device.
final class LeapVlmBridge: NSObject, IosVlmBridge {
    private var runner: ModelRunner?
    private var preparedKey: String?

    // These should eventually be driven by the server manifest (model_bundle_id + revision/runtime).
    private let modelName: String
    private let quantization: String

    init(modelName: String = "LFM2.5-350M-GGUF", quantization: String = "Q4_K_M") {
        self.modelName = modelName
        self.quantization = quantization
        super.init()
    }

    func run(
        prompt: String,
        images: [KotlinByteArray],
        roles: [String],
        completion: @escaping (String?, NSError?) -> Void
    ) {
        Task {
            do {
                let key = "\(modelName)|\(quantization)"
                if runner == nil || preparedKey != key {
                    runner = try await Leap.load(model: modelName, quantization: quantization) { _, _ in }
                    preparedKey = key
                }

                guard let runner else {
                    completion(nil, NSError(domain: "nutonic.vlm", code: 1, userInfo: [NSLocalizedDescriptionKey: "Leap model runner not initialized"]))
                    return
                }

                // Leap iOS multimodal expects JPEG bytes.
                var contents: [ChatMessageContent] = [.text(prompt)]
                for imgBytes in images {
                    let data = imgBytes.toData()
                    guard let uiImage = UIImage(data: data),
                          let jpeg = uiImage.jpegData(compressionQuality: 0.92) else {
                        completion(nil, NSError(domain: "nutonic.vlm", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to decode/encode image as JPEG"]))
                        return
                    }
                    contents.append(.image(jpeg))
                }

                let conversation = runner.createConversation(systemPrompt: nil)
                let msg = ChatMessage(role: .user, content: contents)

                var chunks = ""
                for try await resp in conversation.generateResponse(message: msg, generationOptions: nil) {
                    switch resp {
                    case .chunk(let text):
                        chunks += text
                    case .complete(let completionMsg):
                        if case .text(let final) = completionMsg.message.content.first {
                            completion(final as String, nil)
                        } else {
                            completion(chunks, nil)
                        }
                        return
                    default:
                        continue
                    }
                }
                completion(chunks, nil)
            } catch {
                completion(nil, error as NSError)
            }
        }
    }
}

private extension KotlinByteArray {
    func toData() -> Data {
        let size = Int(self.size)
        var bytes = [UInt8](repeating: 0, count: size)
        for i in 0..<size {
            bytes[i] = UInt8(truncating: self.get(index: Int32(i)) as NSNumber)
        }
        return Data(bytes)
    }
}

import Foundation
import LeapSDK
import shared

/// Swift-side implementation of the Kotlin `IosVlmBridge` protocol.
///
/// This owns the Leap `ModelRunner` lifecycle on iOS to avoid Kotlin/Native dependency skew.
final class LeapVlmBridge: NSObject, IosVlmBridge {
    private var runner: ModelRunner?
    private var preparedKey: String?

    /// NOTE: These map to Leap model-library names, not HF Hub ids.
    /// If you need iOS to run `NuTonic/lspace`, you must publish a Leap-packaged model entry or use a custom manifestURL.
    private let defaultModelName = "LFM2.5-VL-450M"
    private let defaultQuant = "Q8_0"

    private func ensureRunner(modelName: String, quant: String) async throws -> ModelRunner {
        let key = "\(modelName)|\(quant)"
        if let runner = runner, preparedKey == key {
            return runner
        }
        let loaded = try await Leap.load(model: modelName, quantization: quant)
        self.runner = loaded
        self.preparedKey = key
        return loaded
    }

    func run(
        prompt: String,
        images: [KotlinByteArray],
        roles: [String],
        completion: @escaping (String?, NSError?) -> Void
    ) {
        Task {
            do {
                let runner = try await ensureRunner(modelName: defaultModelName, quant: defaultQuant)

                // Leap conversation: one USER message with [text + images...], aligned with Kotlin engines.
                let conversation = runner.createConversation()
                var contents: [ChatMessageContent] = [.text(prompt)]
                for (idx, kbytes) in images.enumerated() {
                    let data = Data(kotlinByteArray: kbytes)
                    // Optionally, you can incorporate role hints into the prompt; Leap message content is image+text.
                    _ = roles[safe: idx]
                    contents.append(.image(data))
                }
                let msg = ChatMessage(role: .user, content: contents)

                var out = ""
                let stream = conversation.generateResponse(msg)
                for try await resp in stream {
                    switch resp {
                    case .chunk(let t):
                        out.append(t)
                    case .complete(let full):
                        if let first = full.content.first, case .text(let text) = first {
                            completion(text, nil)
                        } else {
                            completion(out, nil)
                        }
                        return
                    default:
                        break
                    }
                }
                completion(out, nil)
            } catch {
                completion(nil, error as NSError)
            }
        }
    }
}

private extension Data {
    init(kotlinByteArray: KotlinByteArray) {
        self = kotlinByteArray.withUnsafeBytes { rawBuf in
            Data(bytes: rawBuf.baseAddress!, count: rawBuf.count)
        }
    }
}

private extension KotlinByteArray {
    func withUnsafeBytes<R>(_ body: (UnsafeRawBufferPointer) throws -> R) rethrows -> R {
        try self.usePinned { pinned in
            let buffer = UnsafeRawBufferPointer(start: pinned.addressOf(0), count: Int(self.size))
            return try body(buffer)
        }
    }
}

private extension Array {
    subscript(safe idx: Int) -> Element? { (0..<count).contains(idx) ? self[idx] : nil }
}

