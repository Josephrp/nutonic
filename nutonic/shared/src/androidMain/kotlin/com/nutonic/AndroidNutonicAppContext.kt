package com.nutonic

import android.content.Context

/**
 * Holds [applicationContext] for cache persistence (`IMP-080`, manifest + local leaderboard paths).
 */
object AndroidNutonicAppContext {
    private var applicationRef: Context? = null

    val application: Context?
        get() = applicationRef

    fun bind(context: Context) {
        applicationRef = context.applicationContext
    }
}
