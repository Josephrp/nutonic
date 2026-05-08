plugins {
    kotlin("multiplatform")
    kotlin("plugin.compose")
    id("com.android.application")
    id("org.jetbrains.compose")
    id("com.google.android.libraries.mapsplatform.secrets-gradle-plugin") version "2.0.1"
}

val nutonicVersionCode = (project.findProperty("nutonicVersionCode") as String?)?.toIntOrNull()
val nutonicVersionName = (project.findProperty("nutonicVersionName") as String?)?.trim()?.takeIf { it.isNotEmpty() }
val nutonicServerOrigin = (project.findProperty("nutonicServerOrigin") as String?)?.trim()?.takeIf { it.isNotEmpty() } ?: "http://10.0.2.2:7860"

kotlin {
    androidTarget()
    sourceSets {
        val androidMain by getting {
            dependencies {
                implementation(project(":shared"))
            }
        }
    }
}

android {
    compileSdk = 36
    namespace = "com.nutonic"
    buildFeatures {
        buildConfig = true
    }
    defaultConfig {
        applicationId = "com.nutonic.android"
        minSdk = 31
        targetSdk = 35
        versionCode = nutonicVersionCode ?: 1
        versionName = nutonicVersionName ?: "1.0"
        // Game server origin only (no `/api/v1`); CI/release: `-PnutonicServerOrigin=https://your-host`.
        buildConfigField("String", "NUTONIC_SERVER_ORIGIN", "\"${nutonicServerOrigin.replace("\\", "\\\\").replace("\"", "\\\"")}\"")
    }
    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin {
        jvmToolchain(17)
    }
    lint {
        // Machine-specific `local.properties` (gitignored) triggers false positives on Windows paths.
        disable += "PropertyEscape"
    }
}

secrets {
    defaultPropertiesFileName = "default.local.properties"
    propertiesFileName = "local.properties"
}
