package com.nutonic.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.Button
import androidx.compose.material.Card
import androidx.compose.material.MaterialTheme
import androidx.compose.material.OutlinedButton
import androidx.compose.material.OutlinedTextField
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import com.nutonic.api.ApiResult
import com.nutonic.api.CacheManifestDocument
import com.nutonic.api.GuessRecordIn
import com.nutonic.api.ManifestRoundLocation
import com.nutonic.api.NutonicApiClient
import com.nutonic.api.RankedClue
import com.nutonic.api.RankedForfeitIn
import com.nutonic.api.RankedSubmitIn
import com.nutonic.api.RankedSubmitOut
import com.nutonic.api.StreetviewHintItem
import com.nutonic.api.UsefulHintsTiers
import com.nutonic.audio.LocalNutonicBgmOverlay
import com.nutonic.audio.NutonicBgmTrack
import com.nutonic.cache.AiGuessStore
import com.nutonic.cache.CachedDocumentWithMergeOutcome
import com.nutonic.cache.ContentCacheRepository
import com.nutonic.cache.ShippedManifestMergeOutcome
import com.nutonic.cache.locationForMap
import com.nutonic.cache.ensurePlayableLocationFromShipped
import com.nutonic.cache.mergeRankedClueWithPack
import com.nutonic.cache.readShippedFullManifest
import com.nutonic.cache.readShippedRankedCluePack
import com.nutonic.cache.truthLatLon
import com.nutonic.leaderboard.GuessRecordOutboxRepository
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRepository
import com.nutonic.leaderboard.LocalNonRankedLeaderboardRow
import com.nutonic.map.BasemapMode
import com.nutonic.map.LatLon
import com.nutonic.map.MapCameraState
import com.nutonic.map.MapGuessState
import com.nutonic.map.MapViewport
import com.nutonic.map.SelfGuessMarker
import com.nutonic.filter.PlatformContext
import com.nutonic.filter.getPlatformContext
import com.nutonic.map.ViewportBounds
import com.nutonic.resources.Res
import com.nutonic.style.NutonicColors
import com.nutonic.style.NutonicGhostButton
import com.nutonic.style.NutonicPrimaryButton
import com.nutonic.toImageBitmap
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.datetime.Clock
import kotlin.math.PI
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

private val demoPeerHint = LatLon(latitude = 50.8503, longitude = 4.3517)

private const val NON_RANKED_CONTENT_BLOCKED_MESSAGE =
    "Round data is unavailable for this map. Open the SCAN hub to refresh the catalog, check connectivity, or pick another map."

private val rankedBounds =
    ViewportBounds(
        minLatitude = 34.0,
        maxLatitude = 71.0,
        minLongitude = -12.0,
        maxLongitude = 32.0,
    )

private const val DEFAULT_ROUND_BUDGET_SECONDS = 180L
private const val REFERENCE_STILL_RESOURCE = "files/3.jpg"

/** `true` when forfeit succeeded or round was already non-open (HTTP 409). */
private suspend fun postRankedForfeitOr409(
    rankedSession: RankedPlaySession,
    api: NutonicApiClient?,
    reason: String,
): Boolean {
    if (api == null) {
        return false
    }
    val tok =
        when (val t = api.postAuthToken()) {
            is ApiResult.Ok -> t.value.accessToken
            else -> return false
        }
    return when (val r = api.postRankedForfeitIntegrity(rankedSession.roundId, RankedForfeitIn(reason), tok)) {
        is ApiResult.Ok -> true
        is ApiResult.HttpFailure -> r.statusCode == 409
        is ApiResult.NetworkFailure -> false
    }
}

/** Active server-ranked round + ticket from `POST /api/v1/ranked/rounds/start` (IMP-090 / W6). */
data class RankedPlaySession(
    val roundId: String,
    val roundTicket: String,
    val clue: RankedClue,
)

/**
 * SCAN gameplay detail: pass [contentCacheRepository] and [localLeaderboardRepository] from the app root
 * (same instances as SCAN hub) so rounds use manifest fixtures and local non-ranked rows persist (`IMP-083`).
 */
@Composable
fun WorldMapGameplayDetail(
    mapId: String,
    mapTitle: String? = null,
    playerRole: String? = null,
    contentCacheRepository: ContentCacheRepository? = null,
    localLeaderboardRepository: LocalNonRankedLeaderboardRepository? = null,
    nutonicApiClient: NutonicApiClient? = null,
    guessRecordOutboxRepository: GuessRecordOutboxRepository? = null,
    /** When set, local truth/score HUD is suppressed until server [postRankedRoundSubmit] resolves (W6). */
    rankedSession: RankedPlaySession? = null,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var manifestSnapshot by remember { mutableStateOf<CacheManifestDocument?>(null) }
    var manifestVersionNotice by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(mapId, contentCacheRepository) {
        val shippedOnly = readShippedFullManifest()
        val cached: CachedDocumentWithMergeOutcome? =
            when (val repo = contentCacheRepository) {
                null -> {
                    shippedOnly?.let {
                        CachedDocumentWithMergeOutcome(
                            document = it,
                            mergeOutcome = ShippedManifestMergeOutcome.OVERLAID_FROM_SHIPPED,
                            shippedContentVersion = it.contentVersion,
                        )
                    }
                }
                else -> {
                    repo.refreshManifest()
                    repo.cachedDocumentWithMergeOutcome()
                }
            }
        val baseDoc = cached?.document
        manifestSnapshot =
            if (baseDoc != null) {
                ensurePlayableLocationFromShipped(baseDoc, shippedOnly, mapId)
            } else {
                null
            }
        manifestVersionNotice =
            when (cached?.mergeOutcome) {
                ShippedManifestMergeOutcome.VERSION_MISMATCH ->
                    buildString {
                        append("Catalog versions differ. ")
                        append("Server ")
                        append(cached.document.contentVersion)
                        append(" and bundled ")
                        append(cached.shippedContentVersion ?: "unknown")
                        append(" are different. You can keep playing; guesses are saved and sent when possible.")
                    }
                else -> null
            }
    }

    var mergedRankedSession by remember(rankedSession) { mutableStateOf(rankedSession) }
    LaunchedEffect(rankedSession?.roundId, rankedSession?.roundTicket, rankedSession?.clue?.locationId) {
        val rs = rankedSession
        mergedRankedSession =
            if (rs == null) {
                null
            } else {
                val pack = readShippedRankedCluePack()
                RankedPlaySession(
                    roundId = rs.roundId,
                    roundTicket = rs.roundTicket,
                    clue = mergeRankedClueWithPack(rs.clue, pack),
                )
            }
    }
    val rankedForUi = mergedRankedSession ?: rankedSession

    val isRanked = rankedForUi != null
    val catalogLocation = remember(manifestSnapshot, mapId) { manifestSnapshot?.locationForMap(mapId) }
    val playableLocation = if (isRanked) null else catalogLocation
    val rankedStillSource =
        remember(rankedForUi) {
            rankedForUi?.let { rs ->
                ManifestRoundLocation(
                    mapId = rs.clue.mapId,
                    locationId = rs.clue.locationId,
                    truthLat = 0.0,
                    truthLon = 0.0,
                    rulesetVersion = null,
                    stillBundleId = rs.clue.stillBundleId,
                    stillBundledResource = rs.clue.stillBundledResource,
                    stillHttpUrl = null,
                    usefulHints = rs.clue.usefulHints,
                    streetviewHintPack = rs.clue.streetviewHintPack,
                    streetviewAssistNarrative = rs.clue.streetviewAssistNarrative,
                    playBudgetMs = rs.clue.playBudgetMs,
                    aiMarkerPhaseEnabled = rs.clue.aiMarkerPhaseEnabled,
                )
            }
        }
    val stillLocation = playableLocation ?: rankedStillSource
    val nonRankedContentBlocked = !isRanked && playableLocation == null
    val groundTruth =
        remember(playableLocation, isRanked) {
            if (isRanked) {
                null
            } else {
                playableLocation?.truthLatLon()
            }
        }
    val locationId =
        rankedForUi?.clue?.locationId
            ?: playableLocation?.locationId
            ?: mapId
    val stillResourcePath = stillLocation?.stillBundledResource ?: REFERENCE_STILL_RESOURCE
    val playBudgetSeconds =
        remember(stillLocation) {
            val budgetMs =
                stillLocation?.playBudgetMs?.toLong()
                    ?: (DEFAULT_ROUND_BUDGET_SECONDS * 1000L)
            (budgetMs / 1000L).coerceAtLeast(1L)
        }
    var basemapMode by remember { mutableStateOf(BasemapMode.ROADMAP) }
    var cameraState by
        remember {
            mutableStateOf(
                MapCameraState(
                    center = LatLon(latitude = 48.8566, longitude = 2.3522),
                    zoomLevel = 4.2,
                ),
            )
        }
    var provisionalGuess by remember { mutableStateOf<LatLon?>(null) }
    var lockedGuess by remember { mutableStateOf<LatLon?>(null) }
    var searchField by remember { mutableStateOf(TextFieldValue("")) }
    var gameplayStatus by remember { mutableStateOf("Tap the map or search a location, then submit one guess.") }
    var guessRecordRemoteStatus by remember { mutableStateOf<String?>(null) }

    var guessModalExpanded by remember { mutableStateOf(true) }
    var narrativeOverlayOpen by remember { mutableStateOf(false) }
    var streetAssistExpanded by remember { mutableStateOf(false) }
    var usefulHintsExpanded by remember { mutableStateOf(false) }
    var revealAssistExpanded by remember { mutableStateOf(false) }
    var peerRevealEnabled by remember { mutableStateOf(false) }
    var rankedBoundsEnabled by remember { mutableStateOf(false) }
    var userNarrativeText by remember { mutableStateOf(TextFieldValue("")) }
    var revealedHintTier by remember { mutableStateOf(0) }
    var roundInstanceId by remember { mutableStateOf<String?>(null) }

    val roundStartedMs = remember { Clock.System.now().toEpochMilliseconds() }
    var nowMs by remember { mutableStateOf(roundStartedMs) }

    LaunchedEffect(Unit) {
        while (true) {
            delay(1_000)
            nowMs = Clock.System.now().toEpochMilliseconds()
        }
    }

    LaunchedEffect(nonRankedContentBlocked) {
        if (nonRankedContentBlocked) {
            gameplayStatus = NON_RANKED_CONTENT_BLOCKED_MESSAGE
        }
    }

    var referenceStill by remember { mutableStateOf<ImageBitmap?>(null) }
    var referenceStillFailed by remember { mutableStateOf(false) }
    var guessesRecordEnabled by remember { mutableStateOf(false) }
    LaunchedEffect(nutonicApiClient) {
        val api = nutonicApiClient ?: return@LaunchedEffect
        guessesRecordEnabled =
            when (val c = api.getConfig()) {
                is ApiResult.Ok -> c.value.features.guessesRecord
                else -> false
            }
    }

    LaunchedEffect(
        stillLocation?.stillBundleId,
        stillLocation?.stillHttpUrl,
        stillResourcePath,
        nutonicApiClient,
    ) {
        referenceStillFailed = false
        referenceStill = null
        val api = nutonicApiClient
        val bundleId = stillLocation?.stillBundleId?.takeIf { it.isNotBlank() }
        val httpStill = stillLocation?.stillHttpUrl?.takeIf { it.isNotBlank() }
        val fromNetwork =
            when {
                bundleId != null && api != null ->
                    when (val r = api.getBundleStill(bundleId)) {
                        is ApiResult.Ok -> runCatching { r.value.toImageBitmap() }.getOrNull()
                        else -> null
                    }
                httpStill != null && api != null ->
                    when (val r = api.getHttpBytes(httpStill)) {
                        is ApiResult.Ok -> runCatching { r.value.toImageBitmap() }.getOrNull()
                        else -> null
                    }
                else -> null
            }
        val fromResource =
            runCatching {
                Res.readBytes(stillResourcePath).toImageBitmap()
            }.getOrNull()
        referenceStill = fromNetwork ?: fromResource
        referenceStillFailed = referenceStill == null
    }

    val aiGuessStore = remember(manifestSnapshot) { manifestSnapshot?.let(::AiGuessStore) }
    val effectiveMapId = rankedForUi?.clue?.mapId ?: mapId
    val aiForRoundResolution =
        when {
            stillLocation?.aiMarkerPhaseEnabled == false -> null
            else -> aiGuessStore?.resolution(effectiveMapId, locationId)
        }
    val aiForRound: LatLon? = aiForRoundResolution?.coordinates
    val aiMarkerSource = aiForRoundResolution?.source

    var rankedServerOutcome by remember { mutableStateOf<RankedSubmitOut?>(null) }
    var rankedServerError by remember { mutableStateOf<String?>(null) }

    /** After first successful (or idempotent 409) ranked forfeit, further assist opens skip HTTP (`IMP-091`). */
    var rankedAssistForfeitSatisfied by remember { mutableStateOf(false) }

    LaunchedEffect(rankedForUi?.roundId) {
        rankedServerOutcome = null
        rankedServerError = null
        rankedAssistForfeitSatisfied = false
    }

    LaunchedEffect(lockedGuess, rankedForUi) {
        if (lockedGuess == null && rankedForUi != null) {
            rankedServerOutcome = null
            rankedServerError = null
        }
    }

    LaunchedEffect(lockedGuess, rankedForUi, nutonicApiClient) {
        val rs = rankedForUi
        val guess = lockedGuess
        val api = nutonicApiClient
        if (rs == null || guess == null || api == null) {
            return@LaunchedEffect
        }
        if (rankedServerOutcome != null || rankedServerError != null) {
            return@LaunchedEffect
        }
        val tok =
            when (val t = api.postAuthToken()) {
                is ApiResult.Ok -> t.value.accessToken
                is ApiResult.HttpFailure -> {
                    rankedServerError = t.userMessage
                    return@LaunchedEffect
                }
                is ApiResult.NetworkFailure -> {
                    rankedServerError = t.debugMessage
                    return@LaunchedEffect
                }
            }
        val idem = "ranked|${rs.roundId}|submit"
        when (
            val sub =
                api.postRankedRoundSubmit(
                    rs.roundId,
                    RankedSubmitIn(
                        guessLat = guess.latitude,
                        guessLon = guess.longitude,
                        roundTicket = rs.roundTicket,
                    ),
                    tok,
                    idem,
                )
        ) {
            is ApiResult.Ok -> rankedServerOutcome = sub.value
            is ApiResult.HttpFailure -> rankedServerError = sub.userMessage
            is ApiResult.NetworkFailure -> rankedServerError = sub.debugMessage
        }
    }

    val elapsedSeconds = ((nowMs - roundStartedMs) / 1_000).coerceAtLeast(0)
    val remainingSeconds = (playBudgetSeconds - elapsedSeconds).coerceAtLeast(0)
    val viewportBounds = if (rankedBoundsEnabled) rankedBounds else null
    val selfGuess =
        when {
            lockedGuess != null -> SelfGuessMarker(lockedGuess!!, MapGuessState.LOCKED)
            provisionalGuess != null -> SelfGuessMarker(provisionalGuess!!, MapGuessState.PROVISIONAL)
            else -> null
        }

    val aiMarker = if (lockedGuess != null) aiForRound else null
    val distanceKm =
        rankedServerOutcome?.distanceKm
            ?: if (isRanked) {
                null
            } else {
                lockedGuess?.let { g -> groundTruth?.let { haversineKm(g, it) } }
            }
    val scorePoints =
        rankedServerOutcome?.scorePoints
            ?: if (isRanked) {
                null
            } else {
                distanceKm?.let(::scoreFromDistanceKm)
            }
    val aiVsTruthKm =
        if (isRanked || groundTruth == null) {
            null
        } else {
            aiMarker?.let { haversineKm(it, groundTruth) }
        }

    LaunchedEffect(lockedGuess, roundInstanceId, localLeaderboardRepository, rankedForUi) {
        val guess = lockedGuess
        val rid = roundInstanceId
        val repo = localLeaderboardRepository
        if (rankedForUi != null || guess == null || rid == null || repo == null) {
            return@LaunchedEffect
        }
        val truth = groundTruth ?: return@LaunchedEffect
        val humanKm = haversineKm(guess, truth)
        val humanScore = scoreFromDistanceKm(humanKm)
        val aiKm = aiMarker?.let { haversineKm(it, groundTruth) }
        val role = (playerRole ?: "HUMAN").uppercase()
        repo.appendRow(
            LocalNonRankedLeaderboardRow(
                roundInstanceId = rid,
                mapId = mapId,
                locationId = locationId,
                playerRole = role,
                matchupType = "HUMAN_VS_AI",
                humanDistanceKm = humanKm,
                humanScorePoints = humanScore,
                aiDistanceToTruthKm = aiKm,
                guessLat = guess.latitude,
                guessLon = guess.longitude,
                savedAtEpochMs = Clock.System.now().toEpochMilliseconds(),
                rulesetVersion = playableLocation?.rulesetVersion ?: stillLocation?.rulesetVersion,
            ),
        )
    }

    LaunchedEffect(
        lockedGuess,
        roundInstanceId,
        nutonicApiClient,
        distanceKm,
        mapId,
        locationId,
        playableLocation,
        stillLocation,
        guessesRecordEnabled,
        rankedForUi,
        guessRecordOutboxRepository,
    ) {
        val guess = lockedGuess
        val rid = roundInstanceId
        val api = nutonicApiClient
        val km = distanceKm
        val outbox = guessRecordOutboxRepository
        guessRecordRemoteStatus = null
        if (rankedForUi != null || !guessesRecordEnabled || guess == null || rid == null || api == null || km == null) {
            return@LaunchedEffect
        }
        if (outbox == null) {
            guessRecordRemoteStatus = "Saved locally; sync queue unavailable."
            return@LaunchedEffect
        }
        val idem = "guess-record|$rid"
        val body =
            GuessRecordIn(
                roundInstanceId = rid,
                locationId = locationId,
                guessLat = guess.latitude,
                guessLon = guess.longitude,
                clientDistanceKm = km,
                rulesetVersion = playableLocation?.rulesetVersion ?: stillLocation?.rulesetVersion,
            )
        outbox.enqueueOrReplace(mapId, idem, body)
        guessRecordRemoteStatus = outbox.flushPending(api)
    }

    var hideSuccessOverlay by remember(mapId) { mutableStateOf(false) }
    LaunchedEffect(mapId) {
        hideSuccessOverlay = false
    }

    val platformContext = getPlatformContext()

    val showSuccessOverlay =
        lockedGuess != null && !hideSuccessOverlay && (rankedServerOutcome != null || !isRanked)
    val bgmOverlayHolder = LocalNutonicBgmOverlay.current
    LaunchedEffect(showSuccessOverlay, bgmOverlayHolder) {
        val h = bgmOverlayHolder ?: return@LaunchedEffect
        h.value = if (showSuccessOverlay) NutonicBgmTrack.MusicSuccess else null
    }
    DisposableEffect(bgmOverlayHolder) {
        onDispose {
            bgmOverlayHolder?.value = null
        }
    }

    Box(modifier = Modifier.fillMaxSize().padding(12.dp)) {
        rankedServerError?.let { err ->
            Card(
                modifier =
                    Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 8.dp)
                        .testTag("worldMapRankedErrorBanner"),
                backgroundColor = MaterialTheme.colors.error.copy(alpha = 0.12f),
                elevation = 4.dp,
            ) {
                Text(
                    text = "Ranked server: $err",
                    modifier = Modifier.padding(12.dp),
                    style = MaterialTheme.typography.body2,
                    color = MaterialTheme.colors.error,
                )
            }
        }
        if (showSuccessOverlay) {
            RoundSuccessOverlay(
                mapId = mapId,
                mapTitle = mapTitle,
                locationId = locationId,
                scorePoints = scorePoints,
                distanceKm = distanceKm,
                serverVerified = rankedServerOutcome != null,
                platformContext = platformContext,
                onDismiss = { hideSuccessOverlay = true },
                modifier =
                    Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 8.dp)
                        .testTag("worldMapSuccessOverlay"),
            )
        }
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (nonRankedContentBlocked) {
                Card(
                    modifier = Modifier.fillMaxWidth().testTag("worldMapContentBlockedBanner"),
                    backgroundColor = MaterialTheme.colors.error.copy(alpha = 0.1f),
                    elevation = 2.dp,
                ) {
                    Text(
                        text = NON_RANKED_CONTENT_BLOCKED_MESSAGE,
                        modifier = Modifier.padding(12.dp),
                        style = MaterialTheme.typography.body2,
                        color = MaterialTheme.colors.error,
                    )
                }
            }
            manifestVersionNotice?.let { notice ->
                Card(
                    modifier = Modifier.fillMaxWidth().testTag("worldMapManifestVersionBanner"),
                    backgroundColor = MaterialTheme.colors.secondary.copy(alpha = 0.12f),
                    elevation = 2.dp,
                ) {
                    Text(
                        text = notice,
                        modifier = Modifier.padding(12.dp),
                        style = MaterialTheme.typography.body2,
                        color = MaterialTheme.colors.secondary,
                    )
                }
            }
            guessRecordRemoteStatus?.let { syncLine ->
                Text(
                    text = syncLine,
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.onBackground,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(
                        text = "World map gameplay",
                        style = MaterialTheme.typography.h6,
                        color = MaterialTheme.colors.primary,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text =
                            buildString {
                                append("Map: ")
                                append(mapId)
                                mapTitle?.takeIf { it.isNotBlank() }?.let { t ->
                                    append(" · ")
                                    append(t)
                                }
                            },
                        style = MaterialTheme.typography.caption,
                        color = MaterialTheme.colors.primary,
                    )
                    Text(
                        text = "Map, reference still, assists, and one scored submit.",
                        style = MaterialTheme.typography.caption,
                        color = MaterialTheme.colors.onBackground,
                    )
                    if (isRanked) {
                        Text(
                            text = "Ranked: distance stays server-verified; opening some assists may record a forfeit.",
                            style = MaterialTheme.typography.caption,
                            color = MaterialTheme.colors.secondary,
                        )
                    }
                }
                NutonicGhostButton(
                    text = "Back",
                    onClick = onBack,
                    modifier = Modifier.testTag("worldMapBackButton"),
                )
            }

            Box(modifier = Modifier.fillMaxWidth().weight(1f).testTag("worldMapGameplayRoot")) {
                MapViewport(
                    modifier = Modifier.fillMaxSize().testTag("worldMapViewport"),
                    basemapMode = basemapMode,
                    cameraState = cameraState,
                    viewportBounds = viewportBounds,
                    selfGuess = selfGuess,
                    peerMarker = if (peerRevealEnabled) demoPeerHint else null,
                    aiMarker = aiMarker,
                    enabled = lockedGuess == null && !nonRankedContentBlocked,
                    onCameraChange = { cameraState = it },
                    onProvisionalGuess = { tapped ->
                        if (lockedGuess == null) {
                            provisionalGuess = tapped
                            gameplayStatus =
                                "Provisional guess set at ${tapped.latitude.format()} / ${tapped.longitude.format()}."
                        }
                    },
                )

                GameplayHudCard(
                    elapsedSeconds = elapsedSeconds,
                    remainingSeconds = remainingSeconds,
                    scorePoints = scorePoints,
                    distanceKm = distanceKm,
                    aiDistanceToTruthKm = if (lockedGuess != null) aiVsTruthKm else null,
                    modifier = Modifier.align(Alignment.TopStart).padding(10.dp),
                )

                ReferenceStillCard(
                    referenceStill = referenceStill,
                    loadFailed = referenceStillFailed,
                    modifier = Modifier.align(Alignment.TopEnd).padding(top = 10.dp, end = 10.dp),
                )

                AssistDock(
                    streetviewPack = stillLocation?.streetviewHintPack,
                    streetviewNarrative = stillLocation?.streetviewAssistNarrative,
                    streetAssistExpanded = streetAssistExpanded,
                    onStreetAssistExpandedChange = { want ->
                        if (!want) {
                            streetAssistExpanded = false
                        } else if (rankedForUi == null) {
                            streetAssistExpanded = true
                        } else {
                            scope.launch {
                                val ok =
                                    rankedAssistForfeitSatisfied ||
                                        postRankedForfeitOr409(
                                            rankedForUi,
                                            nutonicApiClient,
                                            "assists",
                                        )
                                if (ok) {
                                    rankedAssistForfeitSatisfied = true
                                    streetAssistExpanded = true
                                    gameplayStatus = "Ranked: assist forfeit recorded (server)."
                                } else {
                                    gameplayStatus = "Ranked forfeit failed — location assist stayed closed."
                                }
                            }
                        }
                    },
                    usefulHintsExpanded = usefulHintsExpanded,
                    onUsefulHintsExpandedChange = { want ->
                        if (!want) {
                            usefulHintsExpanded = false
                        } else if (rankedForUi == null) {
                            usefulHintsExpanded = true
                        } else {
                            scope.launch {
                                val ok =
                                    rankedAssistForfeitSatisfied ||
                                        postRankedForfeitOr409(
                                            rankedForUi,
                                            nutonicApiClient,
                                            "assists",
                                        )
                                if (ok) {
                                    rankedAssistForfeitSatisfied = true
                                    usefulHintsExpanded = true
                                    gameplayStatus = "Ranked: assist forfeit recorded (server)."
                                } else {
                                    gameplayStatus = "Ranked forfeit failed — useful hints stayed closed."
                                }
                            }
                        }
                    },
                    revealAssistExpanded = revealAssistExpanded,
                    onRevealAssistExpandedChange = { revealAssistExpanded = it },
                    revealedHintTier = revealedHintTier,
                    onRevealHintTier = { tier ->
                        if (rankedForUi == null) {
                            revealedHintTier = tier
                        } else {
                            scope.launch {
                                val ok =
                                    rankedAssistForfeitSatisfied ||
                                        postRankedForfeitOr409(
                                            rankedForUi,
                                            nutonicApiClient,
                                            "assists",
                                        )
                                if (ok) {
                                    rankedAssistForfeitSatisfied = true
                                    revealedHintTier = tier
                                } else {
                                    gameplayStatus = "Ranked forfeit failed — hint tier stayed closed."
                                }
                            }
                        }
                    },
                    manifestHints = stillLocation?.usefulHints,
                    nonRankedBlocked = nonRankedContentBlocked,
                    peerRevealEnabled = peerRevealEnabled,
                    onPeerRevealToggle = {
                        if (rankedForUi == null) {
                            peerRevealEnabled = !peerRevealEnabled
                        } else if (peerRevealEnabled) {
                            peerRevealEnabled = false
                        } else {
                            scope.launch {
                                val ok =
                                    rankedAssistForfeitSatisfied ||
                                        postRankedForfeitOr409(
                                            rankedForUi,
                                            nutonicApiClient,
                                            "peer_reveal",
                                        )
                                if (ok) {
                                    rankedAssistForfeitSatisfied = true
                                    peerRevealEnabled = true
                                    gameplayStatus = "Ranked: peer-reveal forfeit recorded (server)."
                                } else {
                                    gameplayStatus = "Ranked forfeit failed — peer marker stayed hidden."
                                }
                            }
                        }
                    },
                    modifier = Modifier.align(Alignment.BottomStart).padding(10.dp),
                )

                GuessModal(
                    expanded = guessModalExpanded,
                    onExpandedChange = { guessModalExpanded = it },
                    searchField = searchField,
                    onSearchFieldChange = { searchField = it },
                    onSearch = {
                        val resolved = resolveGuessSearch(searchField.text)
                        if (resolved == null) {
                            gameplayStatus =
                                "Search accepts `lat, lon` or known cities (Paris, Rome, Brussels, Vienna)."
                        } else {
                            if (lockedGuess == null) {
                                provisionalGuess = resolved
                            }
                            cameraState = cameraState.copy(center = resolved).normalized(viewportBounds)
                            gameplayStatus =
                                "Search centered map at ${resolved.latitude.format()} / ${resolved.longitude.format()}."
                        }
                    },
                    canSubmit = provisionalGuess != null && lockedGuess == null && !nonRankedContentBlocked,
                    onSubmit = {
                        if (lockedGuess == null && provisionalGuess != null) {
                            roundInstanceId = "$mapId|$locationId|${Clock.System.now().toEpochMilliseconds()}"
                            lockedGuess = provisionalGuess
                            hideSuccessOverlay = false
                            gameplayStatus =
                                if (aiForRound != null) {
                                    "Guess submitted. AI marker placed from ${aiMarkerSource ?: "known"} source."
                                } else {
                                    "Guess submitted. AI marker unavailable for this slice — compare on map if shown."
                                }
                        }
                    },
                    currentGuess = lockedGuess ?: provisionalGuess,
                    locked = lockedGuess != null,
                    modifier = Modifier.align(Alignment.BottomEnd).padding(10.dp),
                )
            }

            Text(
                text = gameplayStatus,
                style = MaterialTheme.typography.body2,
                color = MaterialTheme.colors.onBackground,
            )
            aiMarkerSource?.let { source ->
                Text(
                    text = "AI marker source: $source",
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.onBackground,
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Button(
                    modifier = Modifier.weight(1f).testTag("worldMapBasemapButton"),
                    onClick = {
                        basemapMode = basemapMode.next()
                        gameplayStatus = "Basemap switched to ${basemapMode.name.lowercase()}."
                    },
                ) {
                    Text("Basemap: ${basemapMode.name.lowercase()}")
                }

                Button(
                    modifier = Modifier.weight(1f).testTag("worldMapBoundsButton"),
                    onClick = {
                        rankedBoundsEnabled = !rankedBoundsEnabled
                        cameraState = cameraState.normalized(if (rankedBoundsEnabled) rankedBounds else null)
                        gameplayStatus =
                            if (rankedBoundsEnabled) {
                                "Ranked-style viewport bounds enabled."
                            } else {
                                "Free camera enabled."
                            }
                    },
                ) {
                    Text(if (rankedBoundsEnabled) "Bounds on" else "Bounds off")
                }

                Button(
                    modifier = Modifier.weight(1f).testTag("worldMapPeerButton"),
                    onClick = {
                        peerRevealEnabled = !peerRevealEnabled
                        gameplayStatus = if (peerRevealEnabled) "Peer reveal uplink opened." else "Peer reveal hidden."
                    },
                ) {
                    Text(if (peerRevealEnabled) "Hide peer" else "Show peer")
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                NutonicGhostButton(
                    text = "Narrative",
                    onClick = { narrativeOverlayOpen = true },
                    modifier = Modifier.weight(1f).testTag("worldMapNarrativeButton"),
                )

                NutonicGhostButton(
                    text = "Clear round",
                    onClick = {
                        provisionalGuess = null
                        lockedGuess = null
                        roundInstanceId = null
                        peerRevealEnabled = false
                        revealedHintTier = 0
                        gameplayStatus = "Round state reset."
                    },
                    modifier = Modifier.weight(1f).testTag("worldMapClearButton"),
                )
            }
        }

        if (narrativeOverlayOpen) {
            NarrativeOverlay(
                textValue = userNarrativeText,
                onTextValueChange = { userNarrativeText = it },
                onClose = { narrativeOverlayOpen = false },
            )
        }
    }
}

@Composable
private fun GameplayHudCard(
    elapsedSeconds: Long,
    remainingSeconds: Long,
    scorePoints: Int?,
    distanceKm: Double?,
    aiDistanceToTruthKm: Double?,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.width(220.dp).testTag("worldMapHudCard"),
        backgroundColor = MaterialTheme.colors.surface.copy(alpha = 0.9f),
        elevation = 4.dp,
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text("Status", style = MaterialTheme.typography.caption, color = MaterialTheme.colors.primary)
            Text(
                "Elapsed (for fun, not scored): ${elapsedSeconds}s",
                style = MaterialTheme.typography.body2,
            )
            Text("Sector time (not scored): ${remainingSeconds}s", style = MaterialTheme.typography.body2)
            if (scorePoints != null && distanceKm != null) {
                Text("Distance: ${distanceKm.format(2)} km", style = MaterialTheme.typography.caption)
                Text("Score: $scorePoints", style = MaterialTheme.typography.caption)
                if (aiDistanceToTruthKm != null) {
                    Text(
                        "AI vs truth: ${aiDistanceToTruthKm.format(2)} km",
                        style = MaterialTheme.typography.caption,
                    )
                }
            } else {
                Text(
                    "Submit one guess to resolve distance and score (ranked: server verifies).",
                    style = MaterialTheme.typography.caption,
                )
            }
        }
    }
}

@Composable
private fun ReferenceStillCard(
    referenceStill: ImageBitmap?,
    loadFailed: Boolean,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.width(230.dp).testTag("worldMapReferenceStillCard"),
        backgroundColor = MaterialTheme.colors.surface.copy(alpha = 0.92f),
        elevation = 4.dp,
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Reference still", style = MaterialTheme.typography.subtitle2, color = MaterialTheme.colors.primary)
            if (referenceStill != null) {
                Image(
                    bitmap = referenceStill,
                    contentDescription = "Bundled map reference still",
                    modifier = Modifier.fillMaxWidth().height(128.dp).background(NutonicColors.stillImageMatte),
                    contentScale = ContentScale.Crop,
                )
            } else {
                Box(
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .height(128.dp)
                            .background(NutonicColors.stillImagePlaceholder, shape = RoundedCornerShape(8.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = if (loadFailed) "Still unavailable (bundle/resource miss)" else "Loading still…",
                        style = MaterialTheme.typography.caption,
                        color = NutonicColors.onStillImagePlaceholder,
                    )
                }
            }
            Text(
                "Primary clue layer for SCAN. Guess modal remains independent and collapsible.",
                style = MaterialTheme.typography.caption,
            )
        }
    }
}

@Composable
private fun AssistDock(
    streetviewPack: List<StreetviewHintItem>?,
    streetviewNarrative: String?,
    streetAssistExpanded: Boolean,
    onStreetAssistExpandedChange: (Boolean) -> Unit,
    usefulHintsExpanded: Boolean,
    onUsefulHintsExpandedChange: (Boolean) -> Unit,
    revealAssistExpanded: Boolean,
    onRevealAssistExpandedChange: (Boolean) -> Unit,
    revealedHintTier: Int,
    onRevealHintTier: (Int) -> Unit,
    manifestHints: UsefulHintsTiers?,
    nonRankedBlocked: Boolean,
    peerRevealEnabled: Boolean,
    onPeerRevealToggle: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier.width(260.dp).testTag("worldMapAssistDock"),
        backgroundColor = MaterialTheme.colors.surface.copy(alpha = 0.9f),
        shape = RoundedCornerShape(12.dp),
        elevation = 4.dp,
    ) {
        Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Assist panels", style = MaterialTheme.typography.subtitle2, color = MaterialTheme.colors.primary)
            if (nonRankedBlocked) {
                Text(
                    "Assists are hidden until catalog data is available for this map.",
                    style = MaterialTheme.typography.caption,
                    color = MaterialTheme.colors.error,
                )
            }

            AssistSection(
                title = "Location assist (text)",
                expanded = streetAssistExpanded,
                onExpandedChange = onStreetAssistExpandedChange,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (streetviewPack.isNullOrEmpty()) {
                        Text(
                            "No location assist text pack for this round.",
                            style = MaterialTheme.typography.caption,
                        )
                    } else {
                        streetviewPack.forEachIndexed { idx, item ->
                            Text(
                                text = "${idx + 1}. ${item.text}",
                                style = MaterialTheme.typography.caption,
                            )
                        }
                    }
                    streetviewNarrative?.takeIf { it.isNotBlank() }?.let { narr ->
                        Text(
                            text = "Narrative: $narr",
                            style = MaterialTheme.typography.caption,
                            color = MaterialTheme.colors.secondary,
                        )
                    }
                }
            }

            AssistSection(
                title = "Useful hints",
                expanded = usefulHintsExpanded,
                onExpandedChange = onUsefulHintsExpandedChange,
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        (1..3).forEach { tier ->
                            OutlinedButton(onClick = { onRevealHintTier(tier) }, modifier = Modifier.weight(1f)) {
                                Text("Tier $tier")
                            }
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        (4..6).forEach { tier ->
                            OutlinedButton(onClick = { onRevealHintTier(tier) }, modifier = Modifier.weight(1f)) {
                                Text("Tier $tier")
                            }
                        }
                    }
                }
                if (revealedHintTier > 0) {
                    Text(
                        text = usefulHintForTier(revealedHintTier, manifestHints),
                        style = MaterialTheme.typography.caption,
                    )
                }
            }

            AssistSection(
                title = "Reveal uplink",
                expanded = revealAssistExpanded,
                onExpandedChange = onRevealAssistExpandedChange,
            ) {
                OutlinedButton(onClick = onPeerRevealToggle, modifier = Modifier.fillMaxWidth()) {
                    Text(if (peerRevealEnabled) "Hide peer marker" else "Reveal peer marker")
                }
            }
        }
    }
}

@Composable
private fun AssistSection(
    title: String,
    expanded: Boolean,
    onExpandedChange: (Boolean) -> Unit,
    content: @Composable () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        OutlinedButton(onClick = { onExpandedChange(!expanded) }, modifier = Modifier.fillMaxWidth()) {
            Text(if (expanded) "$title (hide)" else "$title (show)")
        }
        if (expanded) {
            content()
        }
    }
}

@Composable
private fun GuessModal(
    expanded: Boolean,
    onExpandedChange: (Boolean) -> Unit,
    searchField: TextFieldValue,
    onSearchFieldChange: (TextFieldValue) -> Unit,
    onSearch: () -> Unit,
    canSubmit: Boolean,
    onSubmit: () -> Unit,
    currentGuess: LatLon?,
    locked: Boolean,
    modifier: Modifier = Modifier,
) {
    if (!expanded) {
        Button(modifier = modifier.testTag("worldMapGuessHandleButton"), onClick = { onExpandedChange(true) }) {
            Text("Guess")
        }
        return
    }

    Card(
        modifier = modifier.width(320.dp).testTag("worldMapGuessModal"),
        backgroundColor = MaterialTheme.colors.surface.copy(alpha = 0.95f),
        shape = RoundedCornerShape(12.dp),
        elevation = 5.dp,
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Guess modal", style = MaterialTheme.typography.subtitle2, color = MaterialTheme.colors.primary)
                TextButton(modifier = Modifier.testTag("worldMapGuessCollapseButton"), onClick = { onExpandedChange(false) }) {
                    Text("Collapse")
                }
            }

            OutlinedTextField(
                value = searchField,
                onValueChange = onSearchFieldChange,
                modifier = Modifier.fillMaxWidth().testTag("worldMapSearchField"),
                singleLine = true,
                label = { Text("Search place or lat,lon") },
            )

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    modifier = Modifier.weight(1f).testTag("worldMapSearchButton"),
                    onClick = onSearch,
                ) {
                    Text("Search")
                }
                Button(
                    modifier = Modifier.weight(1f).testTag("worldMapSubmitGuessButton"),
                    enabled = canSubmit,
                    onClick = onSubmit,
                ) {
                    Text(if (locked) "Submitted" else "Submit guess")
                }
            }

            val coords = currentGuess
            Text(
                text =
                    if (coords != null) {
                        "Current guess: ${coords.latitude.format()} / ${coords.longitude.format()}"
                    } else {
                        "Current guess: none"
                    },
                style = MaterialTheme.typography.caption,
            )
            Text(
                text = "Single primary submit per round.",
                style = MaterialTheme.typography.caption,
                color = MaterialTheme.colors.onBackground,
            )
        }
    }
}

@Composable
private fun NarrativeOverlay(
    textValue: TextFieldValue,
    onTextValueChange: (TextFieldValue) -> Unit,
    onClose: () -> Unit,
) {
    Box(
        modifier =
            Modifier
                .fillMaxSize()
                .background(NutonicColors.overlayScrim)
                .testTag("worldMapNarrativeOverlay"),
        contentAlignment = Alignment.Center,
    ) {
        Card(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp),
            shape = RoundedCornerShape(14.dp),
            elevation = 8.dp,
        ) {
            Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("Narrative overlay", style = MaterialTheme.typography.h6, color = MaterialTheme.colors.primary)
                Text(
                    "The uplink flags this region as a historical trade corridor. " +
                        "Watch coastline geometry, river mouths, and dense urban texture before committing.",
                    style = MaterialTheme.typography.body2,
                )
                OutlinedTextField(
                    value = textValue,
                    onValueChange = onTextValueChange,
                    modifier = Modifier.fillMaxWidth().height(120.dp),
                    label = { Text("Your notes") },
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(modifier = Modifier.testTag("worldMapNarrativeCloseButton"), onClick = onClose) {
                        Text("Close")
                    }
                }
            }
        }
    }
}

private fun resolveGuessSearch(query: String): LatLon? {
    val trimmed = query.trim()
    if (trimmed.isEmpty()) {
        return null
    }

    val byCoordinates =
        trimmed
            .split(',')
            .map { it.trim() }
            .takeIf { it.size == 2 }
            ?.let { parts ->
                val lat = parts[0].toDoubleOrNull()
                val lon = parts[1].toDoubleOrNull()
                if (lat != null && lon != null) {
                    LatLon(lat, lon).normalized()
                } else {
                    null
                }
            }
    if (byCoordinates != null) {
        return byCoordinates
    }

    return when (trimmed.lowercase()) {
        "paris" -> LatLon(48.8566, 2.3522)
        "rome" -> LatLon(41.9028, 12.4964)
        "brussels" -> LatLon(50.8503, 4.3517)
        "vienna" -> LatLon(48.2082, 16.3738)
        else -> null
    }
}

private fun BasemapMode.next(): BasemapMode =
    when (this) {
        BasemapMode.SATELLITE -> BasemapMode.ROADMAP
        BasemapMode.ROADMAP -> BasemapMode.HYBRID
        BasemapMode.HYBRID -> BasemapMode.SATELLITE
    }

private fun usefulHintForTier(
    tier: Int,
    hints: UsefulHintsTiers?,
): String {
    val fromManifest =
        when (tier) {
            1 -> hints?.tier1
            2 -> hints?.tier2
            3 -> hints?.tier3
            4 -> hints?.tier4
            5 -> hints?.tier5
            6 -> hints?.tier6
            else -> null
        }
    if (!fromManifest.isNullOrBlank()) return fromManifest
    return when (tier) {
        1 -> "Tier 1: Western edge of the Eurasian landmass near Atlantic influence."
        2 -> "Tier 2: Distinctive blue urban architecture with steep mountain-backed layout."
        3 -> "Tier 3: Morocco, Rif region, around Chefchaouen."
        4 -> "Tier 4: Subnational physiographic and hydro cues (no coordinates)."
        5 -> "Tier 5: Country-scale framing only."
        6 -> "Tier 6: Strongest scripted assist — still coordinate-free."
        else -> "Tier: no manifest text for this band."
    }
}

private fun scoreFromDistanceKm(distanceKm: Double): Int = (5_000.0 - (distanceKm * 2.8)).coerceAtLeast(0.0).roundToInt()

private fun haversineKm(
    from: LatLon,
    to: LatLon,
): Double {
    val r = 6_371.0
    val lat1 = from.latitude.toRadians()
    val lat2 = to.latitude.toRadians()
    val dLat = (to.latitude - from.latitude).toRadians()
    val dLon = (to.longitude - from.longitude).toRadians()

    val a =
        sin(dLat / 2).pow(2) +
            cos(lat1) * cos(lat2) * sin(dLon / 2).pow(2)
    val c = 2 * asin(sqrt(a.coerceIn(0.0, 1.0)))
    return r * c
}

private fun Double.toRadians(): Double = this / 180.0 * PI
