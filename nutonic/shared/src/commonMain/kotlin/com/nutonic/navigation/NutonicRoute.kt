package com.nutonic.navigation

import com.nutonic.MainTab

/**
 * Single typed graph for product flows (`rules/01-navigation-architecture.md`,
 * checklist `rules/07-screens-checklist.md`). Pre-shell routes are global;
 * [Shell] owns bottom tabs plus at most one in-tab [ShellDetail] (depth rule).
 */
sealed class NutonicRoute {
    data object Splash : NutonicRoute()

    data object RoleSelection : NutonicRoute()

    data object Authentication : NutonicRoute()

    data class Shell(
        val tab: MainTab,
        val detail: ShellDetail? = null,
        /** When opening **RANK** from results / notifications (`IMP-071`, complete plan §3.1). */
        val rankFocusMapId: String? = null,
    ) : NutonicRoute()
}

/**
 * Checklist-aligned detail surfaces reached from shell tabs.
 */
sealed class ShellDetail {
    data object WorldMapGameplay : ShellDetail()

    data object FinalResults : ShellDetail()

    data object IntelDashboard : ShellDetail()

    data object RankGlobal : ShellDetail()

    data object SetupProtocol : ShellDetail()

    data object ProCoordinateDashboard : ShellDetail()

    data object ProFireWatch : ShellDetail()

    data object ProOceanScout : ShellDetail()

    data object ProLandShift : ShellDetail()

    data object ProFloodPulse : ShellDetail()

    data object ProBriefComposer : ShellDetail()
}

private const val PREFIX_SHELL = "shell."

fun NutonicRoute.encode(): String =
    when (this) {
        NutonicRoute.Splash -> "splash"
        NutonicRoute.RoleSelection -> "role"
        NutonicRoute.Authentication -> "auth"
        is NutonicRoute.Shell -> {
            val base = PREFIX_SHELL + tab.id
            val withDetail =
                if (detail == null) {
                    base
                } else {
                    "$base.${detail.token()}"
                }
            val focus = rankFocusMapId?.takeIf { it.isNotBlank() && tab == MainTab.Rank }
            if (focus == null) {
                withDetail
            } else {
                "$withDetail#${encodeRankFocusFragment(focus)}"
            }
        }
    }

fun decodeNutonicRoute(token: String): NutonicRoute {
    val t = token.trim()
    return when {
        t == "splash" -> NutonicRoute.Splash
        t == "role" -> NutonicRoute.RoleSelection
        t == "auth" -> NutonicRoute.Authentication
        t.startsWith(PREFIX_SHELL) -> {
            val withoutPrefix = t.removePrefix(PREFIX_SHELL)
            val hash = withoutPrefix.indexOf('#')
            val shellPart = if (hash >= 0) withoutPrefix.substring(0, hash) else withoutPrefix
            val fragment = if (hash >= 0) withoutPrefix.substring(hash + 1) else null
            decodeShell(shellPart, decodeRankFocusFragment(fragment))
        }
        else -> NutonicRoute.Splash
    }
}

private fun decodeShell(
    rest: String,
    rankFocusMapId: String?,
): NutonicRoute.Shell {
    val parts = rest.split('.')
    val tabId = parts.firstOrNull().orEmpty()
    val tab = MainTab.fromId(tabId) ?: MainTab.ScanHub
    val detailToken = parts.getOrNull(1)
    val detail = detailToken?.let { decodeDetail(it) }
    val focus =
        rankFocusMapId?.takeIf { tab == MainTab.Rank }
    return NutonicRoute.Shell(tab = tab, detail = detail, rankFocusMapId = focus)
}

/** Percent-encodes `#` / `%` so `map_id` stays a single route token segment. */
private fun encodeRankFocusFragment(mapId: String): String =
    buildString(mapId.length * 3) {
        for (ch in mapId) {
            when (ch) {
                '%' -> append("%25")
                '#' -> append("%23")
                else -> append(ch)
            }
        }
    }

private fun decodeRankFocusFragment(raw: String?): String? {
    if (raw.isNullOrBlank()) return null
    val sb = StringBuilder(raw.length)
    var i = 0
    while (i < raw.length) {
        if (raw[i] == '%' && i + 2 < raw.length) {
            val hex = raw.substring(i + 1, i + 3)
            val code = hex.toIntOrNull(16) ?: return null
            sb.append(code.toChar())
            i += 3
        } else {
            sb.append(raw[i])
            i++
        }
    }
    return sb.toString()
}

private fun ShellDetail.token(): String =
    when (this) {
        ShellDetail.WorldMapGameplay -> "gameplay"
        ShellDetail.FinalResults -> "results"
        ShellDetail.IntelDashboard -> "intel"
        ShellDetail.RankGlobal -> "rank"
        ShellDetail.SetupProtocol -> "setup"
        ShellDetail.ProCoordinateDashboard -> "pro"
        ShellDetail.ProFireWatch -> "pro-firewatch"
        ShellDetail.ProOceanScout -> "pro-oceanscout"
        ShellDetail.ProLandShift -> "pro-landshift"
        ShellDetail.ProFloodPulse -> "pro-floodpulse"
        ShellDetail.ProBriefComposer -> "pro-brief"
    }

private fun decodeDetail(token: String): ShellDetail? =
    when (token) {
        // Legacy aliases: route back to active SCAN gameplay/detail surfaces.
        "mission" -> ShellDetail.WorldMapGameplay
        "map" -> ShellDetail.WorldMapGameplay
        "gameplay" -> ShellDetail.WorldMapGameplay
        "success" -> ShellDetail.FinalResults
        "results" -> ShellDetail.FinalResults
        "intel" -> ShellDetail.IntelDashboard
        "rank" -> ShellDetail.RankGlobal
        "setup" -> ShellDetail.SetupProtocol
        "pro" -> ShellDetail.ProCoordinateDashboard
        "pro-firewatch" -> ShellDetail.ProFireWatch
        "pro-oceanscout" -> ShellDetail.ProOceanScout
        "pro-landshift" -> ShellDetail.ProLandShift
        "pro-floodpulse" -> ShellDetail.ProFloodPulse
        "pro-brief" -> ShellDetail.ProBriefComposer
        else -> null
    }
