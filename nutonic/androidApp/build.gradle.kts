plugins {
    kotlin("multiplatform")
    kotlin("plugin.compose")
    id("com.android.application")
    id("org.jetbrains.compose")
    id("com.google.android.libraries.mapsplatform.secrets-gradle-plugin") version "2.0.1"
}

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
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        // Game server origin only (no `/api/v1`); override per build type or `buildTypes { debug { ... } }` as needed.
        buildConfigField("String", "NUTONIC_SERVER_ORIGIN", "\"http://10.0.2.2:7860\"")
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
