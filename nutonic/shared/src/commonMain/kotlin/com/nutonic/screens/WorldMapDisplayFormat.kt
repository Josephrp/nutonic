package com.nutonic.screens

import kotlin.math.pow
import kotlin.math.round

internal fun Double.format(decimals: Int = 4): String {
    val factor = 10.0.pow(decimals)
    val rounded = round(this * factor) / factor
    return rounded.toString()
}
