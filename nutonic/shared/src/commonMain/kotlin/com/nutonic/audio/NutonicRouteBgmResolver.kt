package com.nutonic.audio

import com.nutonic.MainTab
import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.ShellDetail

/**
 * Maps navigation to the active BGM loop (`docs/SCREEN-MUSIC-SPEC.md` §3, `rules/01`).
 * In-tab overlays that are not separate routes (e.g. round success) use
 * [LocalNutonicBgmOverlay] instead.
 */
fun resolveNutonicBgmTrack(route: NutonicRoute): NutonicBgmTrack =
    when (route) {
        NutonicRoute.Splash -> NutonicBgmTrack.MusicSplash
        NutonicRoute.RoleSelection -> NutonicBgmTrack.MusicRole
        NutonicRoute.Authentication -> NutonicBgmTrack.MusicAuth
        is NutonicRoute.Shell -> resolveShellBgm(route)
    }

private fun resolveShellBgm(shell: NutonicRoute.Shell): NutonicBgmTrack =
    when (val d = shell.detail) {
        ShellDetail.WorldMapGameplay -> NutonicBgmTrack.MusicGameplay
        ShellDetail.SuccessOverlay -> NutonicBgmTrack.MusicSuccess
        ShellDetail.FinalResults -> NutonicBgmTrack.MusicResults
        null -> tabDefault(shell.tab)
        ShellDetail.MissionSelection,
        ShellDetail.MapLevelSelection,
        -> NutonicBgmTrack.MusicScanHub
        ShellDetail.IntelDashboard -> NutonicBgmTrack.MusicIntel
        ShellDetail.RankGlobal -> NutonicBgmTrack.MusicRank
        ShellDetail.SetupProtocol -> NutonicBgmTrack.MusicSetup
        ShellDetail.ProCoordinateDashboard -> NutonicBgmTrack.MusicPro
    }

private fun tabDefault(tab: MainTab): NutonicBgmTrack =
    when (tab) {
        MainTab.ScanHub -> NutonicBgmTrack.MusicScanHub
        MainTab.Intel -> NutonicBgmTrack.MusicIntel
        MainTab.Rank -> NutonicBgmTrack.MusicRank
        MainTab.Setup -> NutonicBgmTrack.MusicSetup
        MainTab.Pro -> NutonicBgmTrack.MusicPro
    }
