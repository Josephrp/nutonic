package com.nutonic

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineDispatcher

actual val ioDispatcher: CoroutineDispatcher = Dispatchers.IO
