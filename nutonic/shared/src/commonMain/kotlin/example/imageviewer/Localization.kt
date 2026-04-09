package example.imageviewer

enum class AvailableLanguages {
    DE,
    EN,
}

expect fun getCurrentLanguage(): AvailableLanguages

expect fun getCurrentPlatform(): String

private object EnglishLocalization : Localization {
    override val appName = "My Memories"
    override val picture = "Picture:"
    override val back = "Back"
    override val takePhoto = "Take a photo 📸"
    override val addPhoto = "Add a photo"
    override val kotlinConfName = "KotlinConf 2023 🎉"
    override val kotlinConfDescription =
        """
        This photo was taken during KotlinConf 2023 using #ComposeMultiplatform running on ${getCurrentPlatform()}! 🎊
        Let's build some stunning UIs! 🥳
        https://jb.gg/compose
        """.trimIndent()
    override val newPhotoName = "New Memory"
    override val newPhotoDescription = "May amazing things happen to you! 🙂"
}

private object DeutschLocalization : Localization {
    override val appName = "Meine Erinnerungen"
    override val picture = "Bild:"
    override val back = "Zurück"
    override val takePhoto = "Mach ein Foto 📸"
    override val addPhoto = "Füge ein Foto hinzu"
    override val kotlinConfName = "KotlinConf 2023 🎉"
    override val kotlinConfDescription =
        """
        This photo was taken during KotlinConf 2023! 🎊
        Have a fun with Kotlin and Compose Multiplatform 🥳
        """.trimIndent()
    override val newPhotoName = "New Memory"
    override val newPhotoDescription = "May amazing things happen to you! 🙂"
}

fun getCurrentLocalization() =
    when (getCurrentLanguage()) {
        AvailableLanguages.EN -> EnglishLocalization
        AvailableLanguages.DE -> DeutschLocalization
    }
