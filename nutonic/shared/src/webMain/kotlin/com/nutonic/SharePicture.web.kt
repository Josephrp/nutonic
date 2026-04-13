package com.nutonic

import com.nutonic.filter.PlatformContext
import com.nutonic.model.PictureData

class WebSharePicture : SharePicture {
    override fun share(
        context: PlatformContext,
        picture: PictureData,
    ) {
        error("Should not be called")
    }
}
