import os
import glob
import base64
import io
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
import rioxarray as rxr
from PIL import Image
import streamlit as st

# =============================================================================
# 1) CONFIGURATION & CACHE SETUP (MUST BE FIRST)
# =============================================================================
st.set_page_config(
    page_title="Omnivision | TerraMind Geospatial Foundation Model",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Force ALL model/tokenizer caches to D: (must be set BEFORE importing terratorch/engine)
os.environ["HF_HOME"] = r"D:\ai_cache\huggingface"
os.environ["HUGGINGFACE_HUB_CACHE"] = r"D:\ai_cache\huggingface\hub"
os.environ["TORCH_HOME"] = r"D:\ai_cache\torch"

print(
    "✅ Cache locations:\n"
    f"HF_HOME={os.environ['HF_HOME']}\n"
    f"HUGGINGFACE_HUB_CACHE={os.environ['HUGGINGFACE_HUB_CACHE']}\n"
    f"TORCH_HOME={os.environ['TORCH_HOME']}"
)

# =============================================================================
# 2) ENGINE IMPORT (must happen after env vars)
# =============================================================================
from omnivision_engine import (
    SUPPORTED_MODALITIES,
    render_modality,
    run_generation,
)

# =============================================================================
# 3) HELPERS (download, background, preprocessing, metrics)
# =============================================================================
TILE_SIZE = 224  # TerraMind examples are 224x224


def convert_to_bytes(img_array: np.ndarray, fmt: str = "PNG") -> bytes:
    """Converts a numpy array (H,W,3) float [0..1] to bytes for download."""
    img_uint8 = np.clip(img_array * 255.0, 0, 255).astype(np.uint8)
    image = Image.fromarray(img_uint8)
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def get_base64_of_bin_file(bin_file: str) -> str:
    with open(bin_file, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()


def pick_background_file() -> str | None:
    """
    NEW: Auto-detect a local background image in the same folder as app.py.
    If found -> use it. If not -> use animated background.
    """
    candidates = [
        "earth_bg.jpg", "earth_bg.jpeg", "earth_bg.png",
        "background.jpg", "background.jpeg", "background.png",
        "bg.jpg", "bg.png",
    ]
    for f in candidates:
        if os.path.exists(f) and os.path.isfile(f):
            return f
    return None


def apply_background():
    """
    NEW: If a background image is present in the app folder, use it.
    Otherwise show an animated aurora/grid/stars background.
    IMPORTANT: This background is applied BEHIND everything (no foreground overlay).
    """
    bg_file = pick_background_file()

    if bg_file:
        try:
            b64 = get_base64_of_bin_file(bg_file)
            st.markdown(
                f"""
                <style>
                /* Put background on the main app view container */
                div[data-testid="stAppViewContainer"] {{
                    position: relative;
                    background:
                      linear-gradient(rgba(0,0,0,0.55), rgba(0,0,0,0.92)),
                      url("data:image/png;base64,{b64}");
                    background-size: cover;
                    background-position: center;
                    background-attachment: fixed;
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )
        except Exception as e:
            st.warning(f"Could not load background image '{bg_file}'. Using animated background instead. ({e})")
            _apply_animated_background()
    else:
        _apply_animated_background()


def _apply_animated_background():
    """
    Animated background that is clearly visible and stays BEHIND content.
    We attach it to stAppViewContainer pseudo-layers with negative z-index.
    """
    st.markdown(
        """
        <style>
        /* Ensure container is a stacking context for pseudo layers */
        div[data-testid="stAppViewContainer"]{
            position: relative;
            z-index: 0;
            background: transparent;
            overflow: hidden;
        }

        /* Animated aurora layer (behind everything) */
        div[data-testid="stAppViewContainer"]::before {
            content: "";
            position: fixed;  /* fixed so it doesn't scroll weirdly */
            inset: -25%;
            z-index: -3;
            pointer-events: none;

            background:
              radial-gradient(900px 520px at 20% 20%, rgba(34,211,238,0.28), transparent 60%),
              radial-gradient(800px 520px at 80% 25%, rgba(139,92,246,0.26), transparent 58%),
              radial-gradient(700px 520px at 60% 80%, rgba(59,130,246,0.20), transparent 55%),
              linear-gradient(120deg, rgba(2,6,23,1), rgba(15,23,42,1));
            filter: blur(42px) saturate(1.2);
            opacity: 1.0;
            transform: translate3d(0,0,0);
            animation: omniAurora 14s ease-in-out infinite alternate;
        }

        @keyframes omniAurora {
            0%   { transform: translate(-2%, -1%) scale(1.02); }
            50%  { transform: translate(2%, 1%) scale(1.05); }
            100% { transform: translate(-1%, 2%) scale(1.03); }
        }

        /* Grid + stars layer (also behind) */
        div[data-testid="stAppViewContainer"]::after {
            content: "";
            position: fixed;
            inset: 0;
            z-index: -2;
            pointer-events: none;

            background-image:
              /* subtle stars */
              radial-gradient(rgba(255,255,255,0.12) 1px, transparent 1px),
              radial-gradient(rgba(255,255,255,0.08) 1px, transparent 1px),
              /* subtle grid */
              linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px);

            background-size:
              120px 120px,
              220px 220px,
              90px 90px,
              90px 90px;

            background-position:
              0 0,
              40px 60px,
              0 0,
              0 0;

            opacity: 0.25;
            animation: omniDrift 55s linear infinite;
            mask-image: radial-gradient(circle at 50% 30%, rgba(0,0,0,1), rgba(0,0,0,0.15) 60%, rgba(0,0,0,0) 78%);
        }

        @keyframes omniDrift {
            0%   { transform: translateY(0px); }
            100% { transform: translateY(80px); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_global_css():
    """
    Global UI polish + animations + glass cards + error legend styles.
    Note: we do NOT set an opaque background here; background is handled by apply_background().
    """
    st.markdown(
        """
        <style>
        /* Ensure our fixed background layers show through */
        .stApp {
            position: relative;
            z-index: 0;
            background: transparent !important;
        }

        html, body, [class*="css"] {
            font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
            color: #e5e7eb;
        }

        /* Sidebar */
        section[data-testid="stSidebar"] {
            background: rgba(2, 6, 23, 0.92);
            border-right: 1px solid rgba(255,255,255,0.08);
            backdrop-filter: blur(10px);
        }

        /* Buttons */
        div.stButton > button {
            background: linear-gradient(90deg, #06b6d4 0%, #3b82f6 55%, #8b5cf6 100%);
            color: white;
            border: 0;
            border-radius: 10px;
            padding: 0.60rem 1.05rem;
            font-weight: 700;
            transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
        }
        div.stButton > button:hover {
            transform: translateY(-2px) scale(1.01);
            box-shadow: 0 12px 30px rgba(59,130,246,0.22), 0 10px 20px rgba(139,92,246,0.18);
            filter: brightness(1.05);
        }

        /* Gradient title animation */
        .hero-title {
            font-size: 3.0rem;
            font-weight: 900;
            line-height: 1.05;
            background: linear-gradient(90deg, #e5e7eb, #93c5fd, #c4b5fd, #e5e7eb);
            background-size: 250% 250%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: gradientFlow 6s ease infinite;
            margin-bottom: 0.3rem;
        }
        @keyframes gradientFlow {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        /* Fade/slide-in for sections */
        .fade-up {
            animation: fadeUp 0.6s ease both;
        }
        @keyframes fadeUp {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Glass cards */
        .glass-card {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 16px;
            padding: 18px 18px;
            backdrop-filter: blur(10px);
            box-shadow: 0 16px 40px rgba(0,0,0,0.25);
        }
        .glass-card:hover {
            border-color: rgba(255,255,255,0.18);
        }

        /* Subtle info blocks */
        div[data-testid="stAlert"] {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 14px;
            color: #e5e7eb;
        }

        /* Footer */
        .footer {
            margin-top: 4rem;
            padding-top: 1.5rem;
            border-top: 1px solid rgba(255,255,255,0.10);
            text-align: center;
            font-size: 0.85rem;
            color: #94a3b8;
        }
        .small {
            color: #94a3b8;
            font-size: 0.92rem;
        }

        /* Error visualization legend */
        .err-legend {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 14px;
            padding: 12px 14px;
            backdrop-filter: blur(10px);
        }
        .err-bar {
            height: 12px;
            border-radius: 999px;
            border: 1px solid rgba(255,255,255,0.12);
            background: linear-gradient(
                90deg,
                rgba(239,68,68,0.00) 0%,
                rgba(239,68,68,0.25) 35%,
                rgba(239,68,68,0.70) 70%,
                rgba(239,68,68,1.00) 100%
            );
        }
        .err-labels {
            display: flex;
            justify-content: space-between;
            margin-top: 6px;
            font-size: 0.86rem;
            color: #cbd5e1;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def load_tif_chw(path: str) -> np.ndarray:
    """Loads a raster to numpy array (C,H,W) float32."""
    arr = rxr.open_rasterio(path).values
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    return arr


def to_bchw(arr_chw: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(arr_chw).unsqueeze(0)  # (1,C,H,W)


def resize_or_crop_to_224(x_bchw: torch.Tensor, modality: str, strategy: str) -> torch.Tensor:
    """
    Match visualization to generation preprocessing:
    - LULC uses nearest
    - others use bilinear
    """
    mode = "nearest" if modality == "LULC" else "bilinear"
    _, _, h, w = x_bchw.shape

    if strategy == "resize":
        return F.interpolate(
            x_bchw.float(),
            size=(TILE_SIZE, TILE_SIZE),
            mode=mode,
            align_corners=False if mode == "bilinear" else None,
        )

    if strategy == "center_crop":
        if h < TILE_SIZE or w < TILE_SIZE:
            raise ValueError("Image smaller than 224; cannot center-crop.")
        top = (h - TILE_SIZE) // 2
        left = (w - TILE_SIZE) // 2
        return x_bchw[:, :, top : top + TILE_SIZE, left : left + TILE_SIZE].float()

    # center_crop_then_resize
    if h >= TILE_SIZE and w >= TILE_SIZE:
        top = (h - TILE_SIZE) // 2
        left = (w - TILE_SIZE) // 2
        return x_bchw[:, :, top : top + TILE_SIZE, left : left + TILE_SIZE].float()

    return F.interpolate(
        x_bchw.float(),
        size=(TILE_SIZE, TILE_SIZE),
        mode=mode,
        align_corners=False if mode == "bilinear" else None,
    )


# --- Metrics (continuous + LULC) ---
def mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)))


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def pearsonr(a: np.ndarray, b: np.ndarray) -> float:
    a = a.reshape(-1).astype(np.float64)
    b = b.reshape(-1).astype(np.float64)
    a = a - a.mean()
    b = b - b.mean()
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12
    return float(np.dot(a, b) / denom)


def sam(pred_chw: np.ndarray, ref_chw: np.ndarray) -> float:
    """Spectral Angle Mapper (radians), average over pixels. Expects (C,H,W) with C>=2."""
    C, _, _ = pred_chw.shape
    p = pred_chw.transpose(1, 2, 0).reshape(-1, C).astype(np.float64)
    r = ref_chw.transpose(1, 2, 0).reshape(-1, C).astype(np.float64)
    num = np.sum(p * r, axis=1)
    den = (np.linalg.norm(p, axis=1) * np.linalg.norm(r, axis=1)) + 1e-12
    cosang = np.clip(num / den, -1.0, 1.0)
    return float(np.mean(np.arccos(cosang)))


def lulc_accuracy_macro_f1(pred_labels: np.ndarray, gt_labels: np.ndarray, num_classes: int = 10):
    pred = pred_labels.reshape(-1)
    gt = gt_labels.reshape(-1)

    valid = (gt >= 0) & (gt < num_classes)
    pred = pred[valid]
    gt = gt[valid]

    acc = float(np.mean(pred == gt)) if gt.size else 0.0

    f1s = []
    for c in range(num_classes):
        tp = np.sum((pred == c) & (gt == c))
        fp = np.sum((pred == c) & (gt != c))
        fn = np.sum((pred != c) & (gt == c))
        denom = (2 * tp + fp + fn)
        f1 = float((2 * tp) / denom) if denom > 0 else 0.0
        f1s.append(f1)
    macro_f1 = float(np.mean(f1s)) if f1s else 0.0
    return acc, macro_f1


def compute_metrics(mod: str, pred_bchw: torch.Tensor, gt_bchw: torch.Tensor) -> dict:
    pred = pred_bchw.detach().cpu().numpy()[0]  # (C,H,W)
    gt = gt_bchw.detach().cpu().numpy()[0]      # (C,H,W)

    if mod == "LULC":
        if pred_bchw.shape[1] > 1:
            pred_lbl = pred_bchw.argmax(dim=1)[0].detach().cpu().numpy().astype(np.int32)
        else:
            pred_lbl = pred[0].astype(np.int32)
        gt_lbl = gt[0].astype(np.int32)
        acc, f1 = lulc_accuracy_macro_f1(pred_lbl, gt_lbl, num_classes=10)
        return {"overall_acc": acc, "macro_f1": f1}

    out = {
        "mae": mae(pred, gt),
        "rmse": rmse(pred, gt),
        "pearson_r": pearsonr(pred, gt),
    }
    if pred.shape[0] >= 2:
        out["sam_rad"] = sam(pred, gt)
    return out


def make_error_visual(mod: str, pred_bchw: torch.Tensor, gt_bchw: torch.Tensor) -> np.ndarray:
    if mod == "LULC":
        if pred_bchw.shape[1] > 1:
            pred_lbl = pred_bchw.argmax(dim=1)[0].detach().cpu().numpy().astype(np.int32)
        else:
            pred_lbl = pred_bchw[0, 0].detach().cpu().numpy().astype(np.int32)
        gt_lbl = gt_bchw[0, 0].detach().cpu().numpy().astype(np.int32)
        diff = (pred_lbl != gt_lbl).astype(np.float32)
        return np.stack([diff, np.zeros_like(diff), np.zeros_like(diff)], axis=-1)

    pred = pred_bchw.detach().cpu().numpy()[0]
    gt = gt_bchw.detach().cpu().numpy()[0]
    err = np.mean(np.abs(pred - gt), axis=0)
    p2, p98 = np.percentile(err, (2, 98))
    errn = (err - p2) / (p98 - p2 + 1e-6)
    errn = np.clip(errn, 0, 1).astype(np.float32)
    return np.stack([errn, errn * 0.2, np.zeros_like(errn)], axis=-1)


# =============================================================================
# 4) APPLY GLOBAL CSS + BACKGROUND (image if present else animated)
# =============================================================================
inject_global_css()
apply_background()

# =============================================================================
# 5) STATE MANAGEMENT
# =============================================================================
if "page" not in st.session_state:
    st.session_state.page = "landing"


def navigate_to(page: str):
    st.session_state.page = page
    st.rerun()


# =============================================================================
# 6) CONTACT DIALOG
# =============================================================================
@st.dialog("Contact Omnivision")
def contact_dialog():
    st.markdown("We are open to partnerships with academic institutions, climate organizations, and EO teams.")

    st.text_input("Your Email")
    st.selectbox("Inquiry Type", ["Research Collaboration", "Enterprise Access", "General Support"])
    st.text_area("Message", placeholder="Describe your project...")

    if st.button("Submit Inquiry"):
        st.success("Message sent! We will reach out to you shortly.")

    st.markdown("---")
    st.markdown("**Direct Emails:**")
    st.code(
        "tamseelhamdanii@gmail.com\nrohaanrasool110@gmail.com\nsolehsafida@gmail.com",
        language="text",
    )


# =============================================================================
# 7) LANDING PAGE
# =============================================================================
def render_landing():
    c_logo, c_space, c_contact, c_cta = st.columns([4, 3, 1.2, 1.2])

    with c_logo:
        st.markdown('<div class="fade-up"><div class="hero-title">Omnivision</div></div>', unsafe_allow_html=True)
        st.markdown(
            "<div class='small fade-up'>A product built on the <b>TerraMind</b> geospatial foundation model engine</div>",
            unsafe_allow_html=True,
        )

    with c_contact:
        if st.button("Contact Us", use_container_width=True):
            contact_dialog()

    with c_cta:
        if st.button("Get Started", type="primary", use_container_width=True):
            navigate_to("app")

    st.markdown("---")

    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns([1.5, 1])

    with col1:
        st.markdown(
            """
<div class="glass-card fade-up">
  <div style="font-size:1.1rem; line-height:1.65;">
    <b>Omnivision</b> is our end-to-end Earth intelligence interface.
    It leverages <b>TerraMind’s multi-modal generation</b> to translate between
    satellite modalities (Optical ↔ SAR), and to generate auxiliary geospatial layers
    (DEM, NDVI, Land Cover) from a single input.
    <br><br>
    This app is designed to be both a <b>demo</b> and an <b>educational tool</b>:
    you can inspect each modality, compare outputs to ground truth (examples set),
    and export visual results.
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 Launch Omnivision", use_container_width=False):
            navigate_to("app")

    with col2:
        st.markdown(
            """
<div class="glass-card fade-up">
  <div style="font-weight:800; font-size:1.1rem;">What you can do</div>
  <ul style="margin-top:10px; line-height:1.7;">
    <li><b>Any-to-any generation</b> across key EO modalities</li>
    <li><b>Ground-truth comparison</b> on the provided validation examples</li>
    <li><b>Per-tile metrics</b> (MAE/RMSE/SAM for continuous, Accuracy/F1 for LULC)</li>
    <li><b>Export</b> generated visualizations as PNG</li>
  </ul>
</div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br><br>", unsafe_allow_html=True)
    f1, f2, f3 = st.columns(3)

    with f1:
        st.markdown(
            """
<div class="glass-card fade-up">
  <div style="font-weight:800;">🌍 Multi-Modal</div>
  <div class="small" style="margin-top:8px;">
    Optical (S2), SAR (S1), DEM, NDVI, and LULC in one interface.
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

    with f2:
        st.markdown(
            """
<div class="glass-card fade-up">
  <div style="font-weight:800;">⚡ Real-Time Inference</div>
  <div class="small" style="margin-top:8px;">
    Generate analysis-ready layers using TerraMind diffusion inference.
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

    with f3:
        st.markdown(
            """
<div class="glass-card fade-up">
  <div style="font-weight:800;">🔬 Scientific Context</div>
  <div class="small" style="margin-top:8px;">
    Built to teach modality requirements and evaluate against ground truth.
  </div>
</div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="footer">© 2026 Omnivision. Engine: TerraMind (via TerraTorch). Built for the Blue Sky Challenge.</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# 8) APP PAGE
# =============================================================================
def render_app():
    with st.sidebar:
        if st.button("← Back to Home"):
            navigate_to("landing")

        st.markdown("---")
        st.header("🎛️ Controls")

        input_mod = st.selectbox("Input Modality", SUPPORTED_MODALITIES, index=0)

        with st.expander("📘 Modality Help (What to upload?)", expanded=False):
            st.markdown(
                """
**Optical — Sentinel‑2 (S2L2A)**  
- “Normal image” in visible + extra spectral bands.  
- Typically **12 bands** in EO pipelines (TerraMind examples use multi-band).  

**SAR — Sentinel‑1 (S1RTC / S1GRD)**  
- Synthetic Aperture Radar: sees through clouds/night; captures surface structure.  
- Usually **2 bands**: **VV, VH**.

**DEM**  
- Digital Elevation Model: terrain height (**1 band**).

**NDVI**  
- Vegetation index (**1 band**) generally in approximately [-1, 1].

**Land Cover — LULC**  
- Categorical segmentation maps.  
- Ground truth is typically **1 band** (class id).  
- Model output may be **logits** (e.g., 10 classes → argmax).
                """
            )
            st.caption("Tip: For best results, use the provided examples folder which matches TerraMind training formats.")

        mode = st.radio("Source", ["Upload GeoTIFF", "Examples Folder"], index=0)

        example_file = None
        upload_file = None

        if mode == "Upload GeoTIFF":
            upload_file = st.file_uploader("Upload .tif / .tiff", type=["tif", "tiff"])
        else:
            base = "examples"
            pattern = os.path.join(base, input_mod, "*.tif")
            candidates = sorted(glob.glob(pattern))
            if not candidates:
                st.warning(f"No files found in {pattern}")
                st.caption("Download TerraMind examples/ folder into this project directory.")
            else:
                example_file = st.selectbox("Choose Example", candidates)

        st.markdown("### Output Settings")
        valid_outputs = [m for m in SUPPORTED_MODALITIES if m != input_mod]

        defaults = []
        for candidate in ["S2L2A", "S1RTC", "S1GRD", "DEM", "LULC", "NDVI"]:
            if candidate in valid_outputs and len(defaults) < 2:
                defaults.append(candidate)
        if not defaults:
            defaults = valid_outputs[:2]

        outputs = st.multiselect("Target Modalities", valid_outputs, default=defaults)
        timesteps = st.slider("Diffusion Steps", 1, 30, 10)
        preprocess_strategy = st.selectbox("Resize Mode", ["center_crop_then_resize", "resize", "center_crop"])

        eval_enabled = st.checkbox(
            "Enable Ground Truth Comparison + Metrics (examples only)",
            value=(mode == "Examples Folder"),
            help="Loads matching ground truth from examples/{MODALITY}/{same_file}.tif and computes per-tile metrics.",
        )

        st.caption("VRAM note: more output modalities → more memory. On 6GB GPUs keep outputs ≤ 3.")
        st.markdown("<br>", unsafe_allow_html=True)
        run_btn = st.button("⚡ Run Generation", type="primary", use_container_width=True)

    st.title("Omnivision")
    st.markdown(
        "<div class='small'>Engine: TerraMind (TerraTorch) • Any-to-any geospatial generation + evaluation</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    tmp_path = None
    src_is_examples = False
    if upload_file:
        tmp_path = "temp_upload.tif"
        with open(tmp_path, "wb") as f:
            f.write(upload_file.getbuffer())
    elif example_file:
        tmp_path = example_file
        src_is_examples = True

    col_input, col_output = st.columns([1, 1.8], gap="large")

    with col_input:
        st.subheader("📥 Input")
        if tmp_path:
            st.success(f"Loaded: **{os.path.basename(tmp_path)}**")
            st.info(f"Modality: **{input_mod}**")
            try:
                arr = load_tif_chw(tmp_path)
                st.write(f"Shape (C,H,W): `{arr.shape}`")
            except Exception as e:
                st.warning(f"Could not read raster for shape preview: {e}")
        else:
            st.info("Select an example or upload a GeoTIFF from the sidebar.")

    with col_output:
        st.subheader("📤 Output")

        if not run_btn:
            st.markdown(
                """
                <div class="glass-card fade-up" style="border: 1px dashed rgba(255,255,255,0.20);">
                  <div style="font-weight:800; font-size:1.1rem;">System Standby</div>
                  <div class="small" style="margin-top:8px;">
                    Select parameters in the sidebar and click <b>Run Generation</b>.
                    If you choose <b>Examples Folder</b>, you can also enable Ground Truth comparison + metrics.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            return

        if not tmp_path:
            st.error("Please upload or select a file first.")
            return
        if not outputs:
            st.error("Select at least one output modality.")
            return

        with st.spinner("Running TerraMind Foundation Model…"):
            try:
                generated, info = run_generation(
                    tmp_path,
                    input_modality=input_mod,
                    output_modalities=outputs,
                    timesteps=int(timesteps),
                    preprocess_strategy=preprocess_strategy,
                )
            except Exception as e:
                st.error(f"Error during generation: {e}")
                return

        if getattr(info, "warnings", None):
            for w in info.warnings:
                st.warning(w)

        input_vis = None
        try:
            in_arr = load_tif_chw(tmp_path)
            in_t = to_bchw(in_arr)
            in_t = resize_or_crop_to_224(in_t, modality=input_mod, strategy=preprocess_strategy)
            input_vis = render_modality(input_mod, in_t)
        except Exception as e:
            input_vis = None
            st.warning(f"Input preview unavailable: {e}")

        tabs = st.tabs(list(generated.keys()))
        file_id = os.path.basename(tmp_path)
        base_examples_dir = "examples"

        for i, (mod, pred_tensor) in enumerate(generated.items()):
            with tabs[i]:
                st.markdown(f"### {mod}")
                st.caption("Tip: Metrics are computed on raw tensors; visuals are display mappings.")

                gen_img = render_modality(mod, pred_tensor)

                gt_img = None
                metrics = None
                err_img = None

                if eval_enabled and src_is_examples:
                    gt_path = os.path.join(base_examples_dir, mod, file_id)
                    if os.path.exists(gt_path):
                        try:
                            gt_arr = load_tif_chw(gt_path)
                            gt_t = to_bchw(gt_arr)
                            gt_t = resize_or_crop_to_224(gt_t, modality=mod, strategy=preprocess_strategy)
                            gt_img = render_modality(mod, gt_t)
                            metrics = compute_metrics(mod, pred_tensor, gt_t)
                            err_img = make_error_visual(mod, pred_tensor, gt_t)
                        except Exception as e:
                            st.warning(f"Could not compute ground truth comparison for {mod}: {e}")
                    else:
                        st.info(f"No ground truth file found at: {gt_path}")

                c1, c2, c3 = st.columns([1, 1, 1], gap="medium")

                with c1:
                    st.markdown("**Input**")
                    if input_vis is not None:
                        st.image(input_vis, use_container_width=True)
                    else:
                        st.info("No input visualization available.")

                with c2:
                    st.markdown("**Generated**")
                    st.image(gen_img, use_container_width=True)

                with c3:
                    st.markdown("**Ground Truth**")
                    if gt_img is not None:
                        st.image(gt_img, use_container_width=True)
                    else:
                        st.info("Ground truth shown only for Examples Folder + enabled evaluation.")

                if metrics is not None:
                    st.markdown("---")
                    st.markdown("#### 📏 Metrics (per tile)")
                    df = pd.DataFrame([metrics]).T
                    df.columns = ["value"]
                    st.dataframe(df, use_container_width=True)

                    if err_img is not None:
                        st.markdown("#### 🔥 Error visualization (quick check)")
                        st.image(err_img, caption="Error overlay (normalized for visualization)", use_container_width=True)

                        st.markdown(
                            """
                            <div class="err-legend">
                              <div style="font-weight:800; margin-bottom:6px;">How to read this</div>
                              <div class="small" style="margin-bottom:10px;">
                                This map shows <b>per-pixel mismatch</b> (normalized for visualization).
                                Dark/transparent means <b>low error</b>, bright red means <b>high error</b>.
                              </div>
                              <div class="err-bar"></div>
                              <div class="err-labels">
                                <span>Low error</span>
                                <span>High error</span>
                              </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                st.markdown("---")
                img_bytes = convert_to_bytes(gen_img, fmt="PNG")
                st.download_button(
                    label=f"⬇️ Download {mod} (PNG visualization)",
                    data=img_bytes,
                    file_name=f"omnivision_generated_{mod}_{file_id.replace('.tif','')}.png",
                    mime="image/png",
                )

        st.success("Generation complete.")


# =============================================================================
# 9) ROUTER
# =============================================================================
if st.session_state.get("page", "landing") == "landing":
    render_landing()
else:
    render_app()