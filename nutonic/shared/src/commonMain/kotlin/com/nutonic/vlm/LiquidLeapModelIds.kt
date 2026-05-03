package com.nutonic.vlm

/** Maps server [ProVlmCacheRecord] / bundle id strings to Liquid Leap catalog names (all native targets). */
internal object LiquidLeapModelIds {
    fun modelName(record: ProVlmCacheRecord): String {
        val id = record.modelBundleId.lowercase()
        return when {
            id.contains("1.6b") -> "LFM2.5-VL-1.6B"
            id.contains("450m") -> "LFM2.5-VL-450M"
            id.contains("lfm2.5") && id.contains("vl") -> "LFM2.5-VL-450M"
            id.contains("lspace") -> "LFM2.5-VL-450M"
            else -> "LFM2.5-VL-450M"
        }
    }

    fun quantization(record: ProVlmCacheRecord): String =
        when {
            record.revision.uppercase().contains("Q4") -> "Q4_0"
            record.revision.uppercase().contains("FP16") -> "F16"
            else -> "Q8_0"
        }
}
