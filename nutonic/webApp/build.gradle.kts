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
        val jsMain by getting {
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
    }
}
