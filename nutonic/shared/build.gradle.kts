import java.io.File
plugins {
    kotlin("multiplatform")
    kotlin("plugin.compose")
    id("com.android.library")
    id("org.jetbrains.compose")
    kotlin("plugin.serialization")
    id("kotlin-parcelize")
}

version = "1.0-SNAPSHOT"

kotlin {
    androidTarget()
    jvm("desktop")
    js {
        browser()
        useEsModules()
    }

    // iosX64 omitted: Liquid Leap ships iosArm64 + iosSimulatorArm64 only (no legacy Intel simulator klib).
    listOf(
        iosArm64(),
        iosSimulatorArm64(),
    ).forEach { iosTarget ->
        iosTarget.binaries.framework {
            baseName = "shared"
            isStatic = true
        }
    }

    applyDefaultHierarchyTemplate()

    sourceSets {
        all {
            languageSettings {
                optIn("org.jetbrains.compose.resources.ExperimentalResourceApi")
            }
        }

        val ktorVersion = "3.0.3"

        commonMain.dependencies {
            implementation(compose.runtime)
            implementation(compose.foundation)
            implementation(compose.material)
            implementation(compose.components.resources)
            implementation("org.jetbrains.compose.material:material-icons-core:1.6.11")
            implementation("org.jetbrains.compose.material:material-icons-extended:1.6.11")
            implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
            implementation("org.jetbrains.kotlinx:kotlinx-datetime:0.5.0")
            implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2")
            implementation("io.ktor:ktor-client-core:$ktorVersion")
            implementation("io.ktor:ktor-client-content-negotiation:$ktorVersion")
            implementation("io.ktor:ktor-serialization-kotlinx-json:$ktorVersion")
            // Incremental SHA-256 for streaming PRO VLM bundle verification without heap-sized ByteArrays.
            // Align with Leap SDK / hash BOM (0.8.x): `core` replaced `common`; mixing 0.5 `common-jvm` + 0.8 `core-jvm` duplicates classes on Android.
            implementation("org.kotlincrypto.core:core:0.8.0")
            implementation("org.kotlincrypto.core:digest:0.8.0")
            implementation("org.kotlincrypto.hash:sha2:0.8.0")
        }

        commonTest.dependencies {
            implementation(kotlin("test"))
            implementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
            implementation("io.ktor:ktor-client-mock:$ktorVersion")
        }

        androidMain.dependencies {
            implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
            implementation("ai.liquid.leap:leap-sdk:0.10.2")
            implementation("ai.liquid.leap:leap-model-downloader:0.10.2")
            implementation("io.ktor:ktor-client-okhttp:$ktorVersion")
            api("androidx.activity:activity-compose:1.13.0")
            api("androidx.appcompat:appcompat:1.7.1")
            api("androidx.core:core-ktx:1.18.0")
            implementation("androidx.camera:camera-camera2:1.6.0")
            implementation("androidx.camera:camera-lifecycle:1.6.0")
            implementation("androidx.camera:camera-view:1.6.0")
            implementation("androidx.concurrent:concurrent-futures-ktx:1.2.0")
            implementation("com.google.guava:guava:33.3.1-android")
            implementation("com.google.accompanist:accompanist-permissions:0.29.2-rc")
            implementation("com.google.android.gms:play-services-maps:20.0.0")
            implementation("com.google.android.gms:play-services-location:21.3.0")
            implementation("com.google.maps.android:maps-compose:2.11.2")
        }

        val iosMain by getting {
            dependencies {
                implementation("io.ktor:ktor-client-darwin:$ktorVersion")
            }
        }

        val jsMain by getting {
            dependencies {
                implementation("io.ktor:ktor-client-js:$ktorVersion")
                implementation(npm("uuid", "^9.0.1"))
            }
        }

        val desktopMain by getting
        desktopMain.dependencies {
            implementation("ai.liquid.leap:leap-sdk-jvm:0.10.2")
            implementation("io.ktor:ktor-client-cio:$ktorVersion")
            runtimeOnly("org.slf4j:slf4j-simple:2.0.17")
            implementation(compose.desktop.common)
            implementation(project(":mapview-desktop"))
        }
        val desktopTest by getting
        desktopTest.dependencies {
            implementation(compose.desktop.currentOs)
            implementation(compose.desktop.uiTestJUnit4)
        }
    }
}

android {
    compileSdk = 36
    namespace = "com.nutonic.shared"
    sourceSets["main"].manifest.srcFile("src/androidMain/AndroidManifest.xml")
    sourceSets["main"].res.srcDirs("src/androidMain/res")
    sourceSets["main"].assets.srcDirs("src/androidMain/assets")

    defaultConfig {
        minSdk = 31
        buildConfigField("String", "NUTONIC_CLIENT_VERSION", "\"1.0-SNAPSHOT\"")
    }
    buildFeatures {
        buildConfig = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin {
        jvmToolchain(17)
    }
}

compose.resources {
    // Stable package: avoids parent-package import ambiguity with `package com.nutonic` sources.
    packageOfResClass = "com.nutonic.resources"
    publicResClass = true
}

tasks.register<Exec>("validateCatalog") {
    group = "verification"
    description =
        "Validates shipped manifest still_bundled_resource paths under composeResources (SPEC-catalog-lint)."
    val repoRoot = rootProject.projectDir.resolve("..").canonicalFile
    workingDir = repoRoot
    val manifestFile =
        File(repoRoot, "nutonic/shared/src/commonMain/composeResources/files/cache/manifest.full.json")
    val composeResourcesRoot = File(repoRoot, "nutonic/shared/src/commonMain/composeResources")
    commandLine(
        "python",
        "data/scripts/validate_shipped_compose_resources.py",
        "--manifest",
        manifestFile.absolutePath,
        "--compose-resources-root",
        composeResourcesRoot.absolutePath,
    )
}

// CI runs `./gradlew test`; for this KMP module AGP's `test` is Android unit tests only.
// Wire desktop Compose UI tests (e.g. IMP-083 local leaderboard persistence) into that graph.
afterEvaluate {
    tasks.named("test").configure {
        finalizedBy(tasks.named("desktopTest"))
    }
}
