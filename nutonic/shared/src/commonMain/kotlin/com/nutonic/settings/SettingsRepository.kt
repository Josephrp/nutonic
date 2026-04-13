package com.nutonic.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Persistence sketch for SETUP (`rules/13`, IMP-051): common in-memory default;
 * replace with expect/actual DataStore / NSUserDefaults when wiring platforms.
 */
interface SettingsRepository {
    val settings: ClientSettings

    fun update(transform: (ClientSettings) -> ClientSettings)
}

class MemorySettingsRepository(
    initial: ClientSettings = ClientSettings(),
) : SettingsRepository {
    private var state by mutableStateOf(initial)

    override val settings: ClientSettings
        get() = state

    override fun update(transform: (ClientSettings) -> ClientSettings) {
        state = transform(state)
    }
}
