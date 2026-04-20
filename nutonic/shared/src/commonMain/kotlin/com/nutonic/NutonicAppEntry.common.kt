package com.nutonic

import androidx.compose.runtime.Composable

@Composable
fun NutonicAppWithDependencies(dependencies: Dependencies) {
    NutonicApp(nutonicApiClient = dependencies.nutonicApiClient)
}
