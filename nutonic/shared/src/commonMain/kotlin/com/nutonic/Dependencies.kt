package com.nutonic

import com.nutonic.api.NutonicApiClient

abstract class Dependencies {
    /** Optional game server REST client; null when networking is disabled. */
    open val nutonicApiClient: NutonicApiClient? = null
}
