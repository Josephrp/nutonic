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
    Rank("Rank", "RANK"),
    Setup("Setup", "SETUP"),
    Pro("Pro", "PRO"),
    ;

    companion object {
        val ordered: Array<MainTab> = entries.toTypedArray()

        /** Legacy bookmark `shell.Intel` resolves to fused progress + leaderboard tab. */
        fun fromId(id: String): MainTab? =
            when (id) {
                "Intel" -> Rank
                else -> entries.find { it.id == id }
            }
    }
}
