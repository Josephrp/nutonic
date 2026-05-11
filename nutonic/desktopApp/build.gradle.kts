import java.io.File
import java.nio.charset.StandardCharsets
import java.util.Properties
import org.jetbrains.compose.desktop.application.dsl.TargetFormat

plugins {
    kotlin("multiplatform")
    kotlin("plugin.compose")
    id("org.jetbrains.compose")
}

val nutonicServerOrigin = (project.findProperty("nutonicServerOrigin") as String?)?.trim()?.takeIf { it.isNotEmpty() }

/** Strip quotes and whitespace from a JDK path from gradle.properties / env. */
fun normalizeJavaHomePath(raw: String): String =
    raw.trim().removeSurrounding("\"").trim()

fun readOrgGradleJavaHomeFromRootGradleProperties(rootDir: File): String? {
    val f = File(rootDir, "gradle.properties")
    if (!f.isFile) return null
    val p = Properties()
    f.reader(StandardCharsets.UTF_8).use { reader -> p.load(reader) }
    val raw = p.getProperty("org.gradle.java.home") ?: return null
    return normalizeJavaHomePath(raw).takeIf { it.isNotEmpty() }
}

fun jdkHomeLooksUsable(home: String): Boolean {
    if (home.isBlank()) return false
    val dir = File(home)
    if (!dir.isDirectory) return false
    val winJava = File(dir, "bin/java.exe")
    val nixJava = File(dir, "bin/java")
    return winJava.isFile || nixJava.isFile
}

/**
 * JVM used for `:desktopApp:run` and packaging. Prefer a full JDK (Temurin), not Android Studio JBR,
 * for Liquid Leap / JNI stability on Windows.
 */
fun resolveDesktopJavaHome(project: Project): String {
    val candidates =
        sequence {
            (project.findProperty("nutonicDesktopJavaHome") as String?)
                ?.let { yield("nutonicDesktopJavaHome" to normalizeJavaHomePath(it)) }
            readOrgGradleJavaHomeFromRootGradleProperties(project.rootDir)
                ?.let { yield("org.gradle.java.home (gradle.properties)" to it) }
            (project.findProperty("org.gradle.java.home") as String?)
                ?.let { yield("org.gradle.java.home (project property)" to normalizeJavaHomePath(it)) }
            System.getenv("JAVA_HOME")?.let { yield("JAVA_HOME" to normalizeJavaHomePath(it)) }
            yield("java.home (current Gradle JVM)" to System.getProperty("java.home")!!)
        }
    for ((label, home) in candidates) {
        if (jdkHomeLooksUsable(home)) {
            return home
        }
        if (home.isNotBlank()) {
            logger.warn("[nutonic] Skipping invalid desktop JVM candidate ($label): $home")
        }
    }
    return System.getProperty("java.home")!!
}

val resolvedDesktopJavaHome = resolveDesktopJavaHome(project)
logger.lifecycle(
    "[nutonic] desktopApp JVM (compose.javaHome): $resolvedDesktopJavaHome " +
        "(override with -PnutonicDesktopJavaHome=... or JAVA_HOME; avoid Android Studio JBR for Leap/VLM on Windows)",
)

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
        javaHome = resolvedDesktopJavaHome
        // Large PRO VLM bundles + Compose Multiplatform need headroom beyond the default JVM heap.
        jvmArgs("-Xmx4g")
        jvmArgs("--enable-native-access=ALL-UNNAMED")
        if (nutonicServerOrigin != null) {
            // Forward Gradle property into the JVM so `defaultNutonicServerOrigin()` can pick it up.
            jvmArgs("-Dnutonic.serverOrigin=$nutonicServerOrigin")
        }

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
