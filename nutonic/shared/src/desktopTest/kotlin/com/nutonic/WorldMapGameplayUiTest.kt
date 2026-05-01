package com.nutonic

import androidx.compose.material.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import com.nutonic.screens.WorldMapGameplayDetail
import org.junit.Rule
import org.junit.Test

class WorldMapGameplayUiTest {
    @get:Rule
    val rule = createComposeRule()

    @Test
    fun gameplayDetail_rendersControlsAndCoreScanSurfaces() {
        rule.setContent {
            MaterialTheme {
                WorldMapGameplayDetail(mapId = "demo", mapTitle = "Demo mission", onBack = {})
            }
        }

        rule.onNodeWithTag("worldMapGameplayRoot").assertIsDisplayed()
        rule.onNodeWithTag("worldMapViewport").assertIsDisplayed()
        rule.onNodeWithTag("worldMapHudExpandButton").performClick()
        rule.onNodeWithTag("worldMapHudCard").assertIsDisplayed()
        rule.onNodeWithTag("worldMapReferenceStillCard").assertIsDisplayed()
        rule.onNodeWithTag("worldMapAssistExpandButton").assertIsDisplayed().performClick()
        rule.onNodeWithTag("worldMapAssistDock").assertIsDisplayed()
        rule.onNodeWithTag("worldMapGuessHandleButton").assertIsDisplayed().performClick()
        rule.onNodeWithTag("worldMapGuessModal").assertIsDisplayed()

        rule.onNodeWithTag("worldMapGuessCollapseButton").performClick()
        rule.onNodeWithTag("worldMapGuessHandleButton").assertIsDisplayed().performClick()
        rule.onNodeWithTag("worldMapGuessModal").assertIsDisplayed()

        rule.onNodeWithTag("worldMapSearchField").performTextClearance()
        rule.onNodeWithTag("worldMapSearchField").performTextInput("Paris")
        rule.onNodeWithTag("worldMapSearchButton").performClick()
        rule.onNodeWithTag("worldMapSubmitGuessButton").performClick()

        rule.onNodeWithTag("worldMapBasemapButton").performClick()
        rule.onNodeWithTag("worldMapBoundsButton").performClick()
        rule.onNodeWithTag("worldMapPeerButton").performClick()
        rule.onNodeWithTag("worldMapNarrativeButton").performClick()
        rule.onNodeWithTag("worldMapNarrativeOverlay").assertIsDisplayed()
        rule.onNodeWithTag("worldMapNarrativeCloseButton").performClick()
        rule.onNodeWithTag("worldMapClearButton").performClick()
    }
}
