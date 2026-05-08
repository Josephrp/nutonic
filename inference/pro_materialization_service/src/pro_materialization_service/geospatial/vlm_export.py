"""Resize raster sources to ``vlm_image_set`` roles (PNG, sRGB 8-bit)."""



from __future__ import annotations



import hashlib

import io



import numpy as np

from PIL import Image





def png_sha256(data: bytes) -> str:

    return hashlib.sha256(data).hexdigest()





def resize_png_to_rgb_square(png_bytes: bytes, width: int, height: int) -> bytes:

    """Decode PNG/JPEG bytes, convert to RGB, resize with bilinear, emit PNG."""

    im = Image.open(io.BytesIO(png_bytes))

    im = im.convert("RGB")

    im = im.resize((width, height), Image.Resampling.BILINEAR)

    buf = io.BytesIO()

    im.save(buf, format="PNG", optimize=True)

    return buf.getvalue()





# TerraMind / Earth Search 12-band order (``s2_stac_load.EARTH_SEARCH_S2L2A_ASSET_KEYS``).

_IDX_RED = 3

_IDX_NIR = 7

_IDX_SWIR22 = 11





def false_color_swir_nir_red_png(

    stack12: np.ndarray,

    width: int,

    height: int,

    *,

    p_lo: float = 2.0,

    p_hi: float = 98.0,

) -> bytes:

    """

    §6.4 ``sentinel_fc``: composite **R**=SWIR2, **G**=NIR, **B**=red; per-band

    ``p_lo``–``p_hi`` percentile stretch; bilinear resize to VLM canvas.

    """



    if stack12.ndim != 3 or stack12.shape[0] < 12:

        raise ValueError(f"expected stack (12,H,W), got {stack12.shape!r}")



    swir = stack12[_IDX_SWIR22].astype(np.float32, copy=False)

    nir = stack12[_IDX_NIR].astype(np.float32, copy=False)

    red = stack12[_IDX_RED].astype(np.float32, copy=False)



    planes = []

    for plane in (swir, nir, red):

        lo = float(np.nanpercentile(plane, p_lo))

        hi = float(np.nanpercentile(plane, p_hi))

        if hi <= lo:

            hi = lo + 1e-6

        u = (np.clip(plane, lo, hi) - lo) / (hi - lo)

        planes.append((u * 255.0).clip(0, 255).astype(np.uint8))



    rgb = np.stack(planes, axis=-1)



    im = Image.fromarray(rgb)

    im = im.resize((width, height), Image.Resampling.BILINEAR)

    buf = io.BytesIO()

    im.save(buf, format="PNG", optimize=True)

    return buf.getvalue()





def cloud_mask_thumb_from_scl_png(

    scl_hw: np.ndarray,

    width: int,

    height: int,

) -> bytes:

    """

    §6.4 ``cloud_mask_thumb``: SCL class codes, **nearest** downscale, RGBA

    overlay (clear pixels transparent; cloud classes tinted).

    """



    if scl_hw.ndim != 2:

        raise ValueError(f"expected SCL (H,W), got {scl_hw.shape!r}")



    codes = np.rint(np.nan_to_num(scl_hw, nan=0.0)).astype(np.int16)

    codes = np.clip(codes, 0, 15)



    h, w = codes.shape

    rgba = np.zeros((h, w, 4), dtype=np.uint8)



    # Cloud / shadow / snow — semi-opaque; scene content left transparent for compositor.

    cloud_hi = (codes == 8) | (codes == 9) | (codes == 10)

    cloud_lo = codes == 7

    shadow = codes == 3

    snow = codes == 11



    rgba[cloud_hi] = (255, 140, 0, 190)

    rgba[cloud_lo] = (255, 220, 100, 110)

    rgba[shadow] = (40, 40, 90, 130)

    rgba[snow] = (210, 230, 255, 150)



    im = Image.fromarray(rgba)

    im = im.resize((width, height), Image.Resampling.NEAREST)

    buf = io.BytesIO()

    im.save(buf, format="PNG", optimize=True)

    return buf.getvalue()

