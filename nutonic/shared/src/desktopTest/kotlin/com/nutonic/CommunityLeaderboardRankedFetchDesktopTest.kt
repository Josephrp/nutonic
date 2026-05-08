package com.nutonic

import androidx.compose.material.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import com.nutonic.api.FeatureFlags
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.NutonicJson
import com.nutonic.screens.CommunityLeaderboardPanel
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import org.junit.Rule
import org.junit.Test
import kotlin.test.assertTrue

class CommunityLeaderboardRankedFetchDesktopTest {
    @get:Rule
    val rule = createComposeRule()

    @Test
    fun rankedTierFetchButton_callsLeaderboardWithTierQuery() {
        var sawTierQuery = false
        val engine =
            MockEngine { request ->
                val url = request.url.toString()
                if (url.contains("leaderboard") && url.contains("tier=ranked")) {
                    sawTierQuery = true
                    respond(
                        """[{"display_handle":"RNK-ABCDEF01","player_role":"RANKED","score_points":100,"distance_km":2.0}]""",
                        HttpStatusCode.OK,
                        headersOf(HttpHeaders.ContentType to listOf("application/json")),
                    )
                } else {
                    respond("[]", HttpStatusCode.OK, headersOf(HttpHeaders.ContentType to listOf("application/json")))
                }
            }
        val http =
            HttpClient(engine) {
                install(ContentNegotiation) {
                    json(NutonicJson)
                }
            }
        val client = NutonicApiClient("https://api.test", http)
        val flags =
            FeatureFlags(
                ranked = true,
                communityLbGet = true,
                communityLbPost = false,
                proJobs = false,
            )
        rule.setContent {
            MaterialTheme {
                CommunityLeaderboardPanel(
                    nutonicApiClient = client,
                    mapId = "demo",
                    onMapIdChange = null,
                    featureFlags = flags,
                    sectionTitle = "Test panel",
                    showRankedVerifiedFetch = true,
                )
            }
        }
        rule.onNodeWithTag("rankedLeaderboardTierFetchButton").assertIsDisplayed().performClick()
        rule.waitForIdle()
        assertTrue(sawTierQuery, "expected GET with tier=ranked")
        rule.onNodeWithTag("rankedLeaderboardTierFetchButton").assertIsDisplayed()
        http.close()
    }
}
