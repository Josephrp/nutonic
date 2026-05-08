package com.nutonic

import com.nutonic.navigation.NutonicRoute
import com.nutonic.navigation.ShellDetail
import com.nutonic.navigation.decodeNutonicRoute
import com.nutonic.navigation.encode
import kotlin.test.Test
import kotlin.test.assertEquals

class KmpSanityTest {
    @Test
    fun commonTest_runner_wired() {
        assertEquals(4, 2 + 2)
    }

    @Test
    fun legacy_shell_intel_decodes_to_rank_tab() {
        assertEquals(NutonicRoute.Shell(MainTab.Rank), decodeNutonicRoute("shell.Intel"))
    }

    @Test
    fun nutonic_route_roundtrip_token() {
        val routes =
            listOf(
                NutonicRoute.Splash,
                NutonicRoute.RoleSelection,
                NutonicRoute.Shell(MainTab.ScanHub),
                NutonicRoute.Shell(MainTab.Rank, ShellDetail.IntelDashboard),
                NutonicRoute.Shell(MainTab.ScanHub, ShellDetail.WorldMapGameplay),
                NutonicRoute.Shell(MainTab.Rank, rankFocusMapId = "demo"),
                NutonicRoute.Shell(MainTab.Rank, ShellDetail.RankGlobal, rankFocusMapId = "idempotency-map"),
                NutonicRoute.Shell(MainTab.Rank, rankFocusMapId = "a%23x"),
            )
        routes.forEach { r ->
            assertEquals(r, decodeNutonicRoute(r.encode()))
        }
    }
}
