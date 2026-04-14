package com.nutonic.view

import android.annotation.SuppressLint
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@SuppressLint("ComposableNaming")
@Composable
actual fun ScrollableColumn(
    modifier: Modifier,
    content: @Composable ColumnScope.() -> Unit,
) = TouchScrollableColumn(modifier, content)
