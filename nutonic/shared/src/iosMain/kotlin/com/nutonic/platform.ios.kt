package com.nutonic

import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers

// Kotlin/Native: Dispatchers.IO is internal; use Default (matches jsMain actual).
actual val ioDispatcher: CoroutineDispatcher = Dispatchers.Default
