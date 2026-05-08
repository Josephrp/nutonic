package com.nutonic

import androidx.compose.material.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRepository
import com.nutonic.persistence.MemoryUtf8BlobStore
import com.nutonic.screens.WorldMapGameplayDetail
import kotlinx.coroutines.runBlocking
import org.junit.Rule
import org.junit.Test
import kotlin.test.assertTrue

/** IMP-083: non-ranked submit persists a device-local leaderboard row. */
class WorldMapGameplayPersistenceTest {
    @get:Rule
    val rule = createComposeRule()

    @Test
    fun submitGuess_appendsLocalLeaderboardRow() {
        val repo = LocalNonRankedLeaderboardRepository(MemoryUtf8BlobStore())
        rule.setContent {
            MaterialTheme {
                WorldMapGameplayDetail(
                    mapId = "poi_0000",
                    mapTitle = "Shipped manifest row",
                    localLeaderboardRepository = repo,
                    onBack = {},
                )
            }
        }
        rule.onNodeWithTag("worldMapGuessHandleButton").performClick()
        // poi_0000 truth is South Australia; "Paris" resolves ~16 Mm away → score clamps to 0.
        rule.onNodeWithTag("worldMapSearchField").performTextInput("-34.24,138.914")
        rule.onNodeWithTag("worldMapSearchButton").performClick()
        rule.onNodeWithTag("worldMapSubmitGuessButton").performClick()
        rule.waitForIdle()
        rule.onNodeWithTag("worldMapSuccessOverlay").assertIsDisplayed()
        rule.onNodeWithTag("worldMapShareScoreStub").assertIsDisplayed()
        rule.onNodeWithTag("worldMapSuccessDismissButton").performClick()
        rule.waitUntil(timeoutMillis = 10_000) {
            runBlocking { repo.rowsForMap("poi_0000").isNotEmpty() }
        }
        val rows = runBlocking { repo.rowsForMap("poi_0000") }
        assertTrue(rows.isNotEmpty())
        assertTrue(rows.first().humanScorePoints > 0)
    }
}
