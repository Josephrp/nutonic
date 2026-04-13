package com.nutonic

/**
 * Canonical shell tabs (`rules/01-navigation-architecture.md`).
 * IDs are stable in code; labels match tactical copy.
 */
enum class MainTab(
    val id: String,
    val label: String,
) {
    ScanHub("ScanHub", "SCAN"),
    Intel("Intel", "INTEL"),
    Rank("Rank", "RANK"),
    Setup("Setup", "SETUP"),
    Pro("Pro", "PRO"),
    ;

    companion object {
        val ordered: Array<MainTab> = entries.toTypedArray()

        fun fromId(id: String): MainTab? = entries.find { it.id == id }
    }
}
