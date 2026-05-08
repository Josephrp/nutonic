package com.nutonic.map

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntSize
import com.nutonic.utils.onPointerEvent
import kotlin.math.PI
import kotlin.math.atan
import kotlin.math.cos
import kotlin.math.ln
import kotlin.math.pow
import kotlin.math.sinh
import kotlin.math.tan

@Composable
actual fun MapViewport(
    modifier: Modifier,
    basemapMode: BasemapMode,
    cameraState: MapCameraState,
    viewportBounds: ViewportBounds?,
    selfGuess: SelfGuessMarker?,
    peerMarker: LatLon?,
    aiMarker: LatLon?,
    enabled: Boolean,
    onCameraChange: (MapCameraState) -> Unit,
    onProvisionalGuess: (LatLon) -> Unit,
) {
    val boundedExternalCamera = cameraState.normalized(viewportBounds)
    var viewportSize by remember { mutableStateOf(IntSize(1, 1)) }
    var localCamera by remember { mutableStateOf(boundedExternalCamera) }
    var lastEmittedCamera by remember { mutableStateOf<MapCameraState?>(null) }

    LaunchedEffect(
        boundedExternalCamera.center.latitude,
        boundedExternalCamera.center.longitude,
        boundedExternalCamera.zoomLevel,
    ) {
        if (!boundedExternalCamera.isApproximately(localCamera)) {
            localCamera = boundedExternalCamera
        }
    }

    fun emitCamera(next: MapCameraState) {
        val normalized = next.normalized(viewportBounds)
        if (!normalized.isApproximately(localCamera)) {
            localCamera = normalized
        }
        if (!normalized.isApproximately(lastEmittedCamera)) {
            lastEmittedCamera = normalized
            onCameraChange(normalized)
        }
    }

    fun onZoomAt(
        centroid: Offset,
        zoomFactor: Float,
    ) {
        if (viewportSize.width <= 0 || viewportSize.height <= 0) {
            return
        }

        val safeZoomFactor = zoomFactor.toDouble().coerceAtLeast(0.0001)
        val projection = WebMercatorProjection(localCamera, viewportSize)
        val anchorGeo = projection.screenToLatLon(centroid)
        val nextZoom =
            (localCamera.zoomLevel + (ln(safeZoomFactor) / ln(2.0))).coerceIn(
                MIN_MAP_ZOOM_LEVEL,
                MAX_MAP_ZOOM_LEVEL,
            )
        val nextProjection =
            WebMercatorProjection(
                cameraState =
                    MapCameraState(
                        center = localCamera.center,
                        zoomLevel = nextZoom,
                    ),
                viewportSize = viewportSize,
            )
        val anchorWorld = nextProjection.latLonToWorld(anchorGeo)
        val screenOffset =
            Offset(
                x = centroid.x - viewportSize.width / 2f,
                y = centroid.y - viewportSize.height / 2f,
            )
        val centerWorld =
            Offset(
                x = anchorWorld.x - screenOffset.x,
                y = anchorWorld.y - screenOffset.y,
            )
        val nextCenter = nextProjection.worldToLatLon(centerWorld.x, centerWorld.y)
        emitCamera(MapCameraState(center = nextCenter, zoomLevel = nextZoom))
    }

    fun onPanBy(pan: Offset) {
        if (viewportSize.width <= 0 || viewportSize.height <= 0) {
            return
        }
        val projection = WebMercatorProjection(localCamera, viewportSize)
        val centerWorld =
            Offset(
                x = projection.centerWorld.x - pan.x,
                y = projection.centerWorld.y - pan.y,
            )
        val nextCenter = projection.worldToLatLon(centerWorld.x, centerWorld.y)
        emitCamera(MapCameraState(center = nextCenter, zoomLevel = localCamera.zoomLevel))
    }

    Box(
        modifier =
            modifier
                .fillMaxSize()
                .onSizeChanged { nextSize ->
                    if (nextSize.width > 0 && nextSize.height > 0) {
                        viewportSize = nextSize
                    }
                }.pointerInput(enabled, viewportBounds, viewportSize, localCamera) {
                    detectTransformGestures { centroid, pan, zoom, _ ->
                        if (zoom != 1f) {
                            onZoomAt(centroid = centroid, zoomFactor = zoom)
                        }
                        if (pan.x != 0f || pan.y != 0f) {
                            onPanBy(pan)
                        }
                    }
                }.onPointerEvent(PointerEventType.Scroll) { event ->
                    val first = event.changes.firstOrNull() ?: return@onPointerEvent
                    val zoomFactor = 1.18f.pow(-first.scrollDelta.y)
                    onZoomAt(centroid = first.position, zoomFactor = zoomFactor)
                }.pointerInput(enabled, viewportBounds, viewportSize, localCamera) {
                    detectTapGestures(
                        onTap = { tapPosition ->
                            if (!enabled) {
                                return@detectTapGestures
                            }
                            val projection = WebMercatorProjection(localCamera, viewportSize)
                            val rawTap = projection.screenToLatLon(tapPosition).normalized()
                            val clampedTap = viewportBounds?.clamp(rawTap) ?: rawTap
                            onProvisionalGuess(clampedTap)
                        },
                    )
                },
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            if (viewportSize.width <= 0 || viewportSize.height <= 0) {
                return@Canvas
            }

            val projection = WebMercatorProjection(localCamera, viewportSize)
            val palette = basemapMode.palette()

            drawRect(color = palette.background, size = size)
            drawMapGrid(projection = projection, majorColor = palette.majorGrid, minorColor = palette.minorGrid)

            drawMarker(
                projection = projection,
                coordinate = selfGuess?.coordinate,
                fill =
                    when (selfGuess?.state) {
                        MapGuessState.LOCKED -> Color(0xFFE53935)
                        MapGuessState.PROVISIONAL -> Color(0xFFFF9800)
                        null -> null
                    },
            )
            drawMarker(projection = projection, coordinate = peerMarker, fill = Color(0xFF039BE5))
            drawMarker(projection = projection, coordinate = aiMarker, fill = Color(0xFF43A047))

            viewportBounds?.let { bounds ->
                val topLeft = projection.latLonToScreen(LatLon(bounds.maxLatitude, bounds.minLongitude))
                val topRight = projection.latLonToScreen(LatLon(bounds.maxLatitude, bounds.maxLongitude))
                val bottomLeft = projection.latLonToScreen(LatLon(bounds.minLatitude, bounds.minLongitude))
                val bottomRight = projection.latLonToScreen(LatLon(bounds.minLatitude, bounds.maxLongitude))
                drawLine(color = Color(0xFFFFF59D), start = topLeft, end = topRight, strokeWidth = 2f)
                drawLine(color = Color(0xFFFFF59D), start = topRight, end = bottomRight, strokeWidth = 2f)
                drawLine(color = Color(0xFFFFF59D), start = bottomRight, end = bottomLeft, strokeWidth = 2f)
                drawLine(color = Color(0xFFFFF59D), start = bottomLeft, end = topLeft, strokeWidth = 2f)
            }
        }
    }
}

private data class WebBasemapPalette(
    val background: Color,
    val majorGrid: Color,
    val minorGrid: Color,
)

private fun BasemapMode.palette(): WebBasemapPalette =
    when (this) {
        BasemapMode.ROADMAP ->
            WebBasemapPalette(
                background = Color(0xFFDCE9D1),
                majorGrid = Color(0xFF769D70),
                minorGrid = Color(0xFF97B596),
            )
        BasemapMode.SATELLITE ->
            WebBasemapPalette(
                background = Color(0xFF243238),
                majorGrid = Color(0xFF607D8B),
                minorGrid = Color(0xFF455A64),
            )
        BasemapMode.HYBRID ->
            WebBasemapPalette(
                background = Color(0xFF3B4D39),
                majorGrid = Color(0xFF8EBF7B),
                minorGrid = Color(0xFF5F7C56),
            )
    }

private class WebMercatorProjection(
    cameraState: MapCameraState,
    viewportSize: IntSize,
) {
    private val center = cameraState.center.normalized()
    private val zoom = cameraState.zoomLevel.coerceIn(MIN_MAP_ZOOM_LEVEL, MAX_MAP_ZOOM_LEVEL)
    private val width = viewportSize.width.toFloat()
    private val height = viewportSize.height.toFloat()
    private val worldSize = TILE_SIZE * 2.0.pow(zoom)
    private val halfWidth = width / 2f
    private val halfHeight = height / 2f

    val centerWorld = latLonToWorld(center)

    fun latLonToWorld(value: LatLon): Offset {
        val lat = value.latitude.coerceIn(-WEB_MERCATOR_MAX_LATITUDE, WEB_MERCATOR_MAX_LATITUDE)
        val lon = normalizeLongitude(value.longitude)
        val x = ((lon + 180.0) / 360.0) * worldSize
        val latRad = lat * PI / 180.0
        val y = (1.0 - ln(tan(latRad) + (1.0 / cos(latRad))) / PI) / 2.0 * worldSize
        return Offset(x.toFloat(), y.toFloat())
    }

    fun worldToLatLon(
        worldX: Float,
        worldY: Float,
    ): LatLon {
        val wrappedX = worldX.wrap(worldSize)
        val clampedY = worldY.toDouble().coerceIn(0.0, worldSize)
        val longitude = wrappedX / worldSize * 360.0 - 180.0
        val n = PI - (2.0 * PI * clampedY / worldSize)
        val latitude = (atan(sinh(n)) * 180.0 / PI).coerceIn(-WEB_MERCATOR_MAX_LATITUDE, WEB_MERCATOR_MAX_LATITUDE)
        return LatLon(latitude = latitude, longitude = normalizeLongitude(longitude))
    }

    fun latLonToScreen(value: LatLon): Offset {
        val world = latLonToWorld(value.normalized())
        val deltaX = shortestWrappedDelta(world.x, centerWorld.x, worldSize.toFloat())
        val deltaY = world.y - centerWorld.y
        return Offset(
            x = halfWidth + deltaX,
            y = halfHeight + deltaY,
        )
    }

    fun screenToLatLon(screen: Offset): LatLon {
        val worldX = centerWorld.x + (screen.x - halfWidth)
        val worldY = centerWorld.y + (screen.y - halfHeight)
        return worldToLatLon(worldX, worldY)
    }

    private fun shortestWrappedDelta(
        x: Float,
        centerX: Float,
        span: Float,
    ): Float {
        var delta = x - centerX
        if (delta > span / 2f) {
            delta -= span
        } else if (delta < -span / 2f) {
            delta += span
        }
        return delta
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawMapGrid(
    projection: WebMercatorProjection,
    majorColor: Color,
    minorColor: Color,
) {
    for (longitude in -180..180 step 10) {
        val lineColor = if (longitude % 30 == 0) majorColor else minorColor
        val top = projection.latLonToScreen(LatLon(WEB_MERCATOR_MAX_LATITUDE, longitude.toDouble()))
        val bottom = projection.latLonToScreen(LatLon(-WEB_MERCATOR_MAX_LATITUDE, longitude.toDouble()))
        drawLine(
            color = lineColor,
            start = top,
            end = bottom,
            strokeWidth = if (longitude % 30 == 0) 1.6f else 0.8f,
        )
    }
    for (latitude in -80..80 step 10) {
        val lineColor = if (latitude % 30 == 0) majorColor else minorColor
        val left = projection.latLonToScreen(LatLon(latitude.toDouble(), -180.0))
        val right = projection.latLonToScreen(LatLon(latitude.toDouble(), 180.0))
        drawLine(
            color = lineColor,
            start = Offset(0f, left.y),
            end = Offset(size.width, right.y),
            strokeWidth = if (latitude % 30 == 0) 1.6f else 0.8f,
        )
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawMarker(
    projection: WebMercatorProjection,
    coordinate: LatLon?,
    fill: Color?,
) {
    if (coordinate == null || fill == null) {
        return
    }
    val point = projection.latLonToScreen(coordinate)
    if (point.x < -18f || point.x > size.width + 18f || point.y < -18f || point.y > size.height + 18f) {
        return
    }

    drawCircle(color = Color.White, radius = 10f, center = point)
    drawCircle(color = fill, radius = 6f, center = point)
}

private fun Float.wrap(worldSize: Double): Double {
    var value = this.toDouble()
    while (value < 0.0) {
        value += worldSize
    }
    while (value >= worldSize) {
        value -= worldSize
    }
    return value
}

private const val TILE_SIZE = 256.0
private const val WEB_MERCATOR_MAX_LATITUDE = 85.05112878
