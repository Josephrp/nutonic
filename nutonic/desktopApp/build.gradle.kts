import org.jetbrains.compose.desktop.application.dsl.TargetFormat

plugins {
    kotlin("multiplatform")
    kotlin("plugin.compose")
    id("org.jetbrains.compose")
}

kotlin {
    jvm()
    sourceSets {
        jvmMain.dependencies {
            implementation(compose.desktop.currentOs)
            implementation(project(":shared"))
        }
    }
}

compose.desktop {
    application {
        mainClass = "com.nutonic.MainKt"

        nativeDistributions {
            targetFormats(TargetFormat.Dmg, TargetFormat.Msi, TargetFormat.Deb)
            packageName = "nutonic"
            packageVersion = "1.0.0"
            // ASCII-only: em dashes / colons in MSI metadata break jpackage+WiX on some Windows runners.
            description = "NU TONIC - geo guessing game (official reference client)."
            vendor = "Nutonic"

            val iconsRoot = project.file("desktop-icons")
            macOS {
                iconFile.set(iconsRoot.resolve("icon-mac.icns"))
            }
            windows {
                iconFile.set(iconsRoot.resolve("icon-windows.ico"))
                // Colon is illegal in Start Menu folder names; jpackage passes this into WiX paths.
                menuGroup = "NU TONIC"
                // see https://wixtoolset.org/documentation/manual/v3/howtos/general/generate_guids.html
                upgradeUuid = "18159995-d967-4CD2-8885-77BFA97CFA9F"
            }
            linux {
                iconFile.set(iconsRoot.resolve("icon-linux.png"))
            }
        }

        buildTypes.release.proguard {
            configurationFiles.from(project.file("rules.pro"))
        }
    }
}
