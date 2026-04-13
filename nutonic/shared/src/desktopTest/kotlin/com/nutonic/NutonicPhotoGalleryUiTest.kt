package com.nutonic

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import com.nutonic.filter.PlatformContext
import com.nutonic.model.PictureData
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import org.junit.Rule
import org.junit.Test

class NutonicPhotoGalleryUiTest {
    @get:Rule
    val rule = createComposeRule()

    private val dependencies =
        object : Dependencies() {
            override val notification: Notification =
                object : PopupNotification(localization) {
                    override fun showPopUpMessage(text: String) {
                    }
                }
            override val imageStorage: DesktopImageStorage =
                DesktopImageStorage(CoroutineScope(Dispatchers.Main))
            override val sharePicture: SharePicture =
                object : SharePicture {
                    override fun share(
                        context: PlatformContext,
                        picture: PictureData,
                    ) {}
                }
        }

    @Test
    fun galleryToggleChangesLayoutStyle() {
        rule.setContent {
            CompositionLocalProvider(
                LocalLocalization provides dependencies.localization,
                LocalNotification provides dependencies.notification,
                LocalImageProvider provides dependencies.imageProvider,
                LocalInternalEvents provides dependencies.externalEvents,
                LocalSharePicture provides dependencies.sharePicture,
            ) {
                NutonicPhotoGalleryFlow(dependencies.pictures)
            }
        }

        rule.onNodeWithTag("squaresGalleryView").assertExists()
        rule.onNodeWithTag("listGalleryView").assertDoesNotExist()
        rule.onNodeWithTag("toggleGalleryStyleButton").performClick()
        rule.onNodeWithTag("squaresGalleryView").assertDoesNotExist()
        rule.onNodeWithTag("listGalleryView").assertExists()
    }
}
