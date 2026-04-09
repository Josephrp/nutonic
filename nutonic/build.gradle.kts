import io.gitlab.arturbosch.detekt.Detekt
import io.gitlab.arturbosch.detekt.extensions.DetektExtension
import org.jlleitschuh.gradle.ktlint.KtlintExtension

plugins {
    // this is necessary to avoid the plugins to be loaded multiple times
    // in each subproject's classloader
    kotlin("jvm") apply false
    kotlin("multiplatform") apply false
    kotlin("android") apply false
    id("com.android.application") apply false
    id("com.android.library") apply false
    id("org.jetbrains.compose") apply false
    id("org.jlleitschuh.gradle.ktlint") apply false
    id("io.gitlab.arturbosch.detekt") apply false
}

allprojects {
    repositories {
        google()
        mavenCentral()
        maven("https://packages.jetbrains.team/maven/p/cmp/dev")
    }
}

subprojects {
    apply(plugin = "org.jlleitschuh.gradle.ktlint")
    apply(plugin = "io.gitlab.arturbosch.detekt")

    afterEvaluate {
        val isAndroid =
            pluginManager.hasPlugin("com.android.library") ||
                pluginManager.hasPlugin("com.android.application")

        extensions.configure<KtlintExtension> {
            version.set(libs.versions.ktlintCli.get())
            android.set(isAndroid)
            ignoreFailures.set(false)
            filter {
                exclude { entry ->
                    val p = entry.file.path.replace("\\", "/")
                    "/build/" in p || "/generated/" in p
                }
            }
        }

        extensions.configure<DetektExtension> {
            buildUponDefaultConfig = true
            parallel = true
            config.setFrom(rootProject.files("config/detekt/detekt.yml"))
            val baselineFile = rootProject.file("config/detekt/baseline.xml")
            if (baselineFile.exists()) {
                baseline = baselineFile
            }
            // KMP / Android / Compose do not use `src/main/kotlin` only; default detekt inputs stay empty → NO-SOURCE.
            val srcRoot = layout.projectDirectory.dir("src").asFile
            if (srcRoot.isDirectory) {
                source.setFrom(
                    fileTree(srcRoot) {
                        include("**/*.kt")
                        exclude("**/build/**")
                        exclude("**/generated/**")
                    },
                )
            }
        }

        tasks.withType<Detekt>().configureEach {
            reports {
                html.required.set(true)
                xml.required.set(true)
                txt.required.set(false)
                sarif.required.set(false)
                md.required.set(false)
            }
        }
    }
}

tasks.register("quality") {
    group = "verification"
    description = "Runs ktlintCheck and detekt on all subprojects."
    subprojects.forEach { sub ->
        dependsOn(sub.tasks.named("ktlintCheck"))
        dependsOn(sub.tasks.named("detekt"))
    }
}

tasks.register("formatKotlin") {
    group = "formatting"
    description = "Runs ktlintFormat on all subprojects."
    subprojects.forEach { sub ->
        dependsOn(sub.tasks.named("ktlintFormat"))
    }
}
