plugins {
    kotlin("multiplatform")
    kotlin("plugin.compose")
    id("org.jetbrains.compose")
}

val rootDirPath = project.rootDir.path

kotlin {
    js {
        outputModuleName = "nutonic"
        browser {
            commonWebpackConfig {
                outputFileName = "nutonic.js"
            }
        }
        binaries.executable()
        useEsModules()
    }

    sourceSets {
        val webMain by creating {
            dependsOn(commonMain.get())
            dependencies {
                implementation(project(":shared"))
                implementation(compose.runtime)
                implementation(compose.ui)
                implementation(compose.foundation)
                implementation(compose.material)
                @OptIn(org.jetbrains.compose.ExperimentalComposeLibrary::class)
                implementation(compose.components.resources)
            }
        }
        val jsMain by getting {
            dependsOn(webMain)
        }
    }
}
