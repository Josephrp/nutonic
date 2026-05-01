package com.nutonic.audio

import com.nutonic.MainTab
import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.ShellDetail
import kotlin.test.Test
import kotlin.test.assertEquals

class NutonicRouteBgmResolverTest {
    @Test
    fun preShellRoutes() {
        assertEquals(NutonicBgmTrack.MusicSplash, resolveNutonicBgmTrack(NutonicRoute.Splash))
        assertEquals(NutonicBgmTrack.MusicRole, resolveNutonicBgmTrack(NutonicRoute.RoleSelection))
    }

    @Test
    fun shellTabsWithoutDetail() {
        assertEquals(
            NutonicBgmTrack.MusicScanHub,
            resolveNutonicBgmTrack(NutonicRoute.Shell(MainTab.ScanHub)),
        )
        assertEquals(
            NutonicBgmTrack.MusicRank,
            resolveNutonicBgmTrack(NutonicRoute.Shell(MainTab.Rank)),
        )
        assertEquals(
            NutonicBgmTrack.MusicSetup,
            resolveNutonicBgmTrack(NutonicRoute.Shell(MainTab.Setup)),
        )
        assertEquals(
            NutonicBgmTrack.MusicPro,
            resolveNutonicBgmTrack(NutonicRoute.Shell(MainTab.Pro)),
        )
    }

    @Test
    fun shellGameplayAndResults() {
        assertEquals(
            NutonicBgmTrack.MusicGameplay,
            resolveNutonicBgmTrack(NutonicRoute.Shell(MainTab.ScanHub, ShellDetail.WorldMapGameplay)),
        )
        assertEquals(
            NutonicBgmTrack.MusicResults,
            resolveNutonicBgmTrack(NutonicRoute.Shell(MainTab.ScanHub, ShellDetail.FinalResults)),
        )
        assertEquals(
            NutonicBgmTrack.MusicRank,
            resolveNutonicBgmTrack(NutonicRoute.Shell(MainTab.Rank, ShellDetail.RankGlobal)),
        )
    }
}
