"""Prompt templates for PRO mini-app dataset builders."""

from __future__ import annotations

SYSTEM_GEOSPATIAL_ANALYST = (
    "You are a geospatial analyst specializing in satellite imagery interpretation. "
    "Analyze the provided Sentinel-2 satellite images and report findings grounded in visible evidence. "
    "Use [x1, y1, x2, y2] bounding boxes normalized to 0-1 relative to image dimensions."
)

SYSTEM_OPTICAL_LIMITS = (
    "This is optical-only observation. Avoid certainty claims beyond visible evidence, "
    "and state confidence and limitations where appropriate."
)

# Multi-image PRO assessment SFT / on-device VLM (keep aligned with Kotlin ``ProModelPromptContract``).
SYSTEM_ASSESSMENT = (
    f"{SYSTEM_GEOSPATIAL_ANALYST} {SYSTEM_OPTICAL_LIMITS} "
    "TerraMind or TiM modality summaries are **auxiliary model evidence**, not field truth unless "
    "independently validated. Never treat pseudo-SAR-like or optical-only signals as legal or operational "
    "confirmation of activity."
)

PRO_ASSESSMENT_TASK_FOOTER = (
    "\nTask: Assess the AOI using **all** images (in order) plus the TerraMind context. "
    "Separate **visible** evidence from **model-inferred** evidence. "
    "State confidence and limitations. Suggest practical follow-up checks. "
    "Do not claim legal outcomes or definitive vessel detections from optical-only data."
)

PRO_ON_DEVICE_VLM_USER_INSTRUCTION_LINES = "\n".join(
    [
        "NU:TONIC PRO on-device vision — describe the provided EO image set using visible evidence.",
        SYSTEM_GEOSPATIAL_ANALYST,
        SYSTEM_OPTICAL_LIMITS,
        "Return a concise caption followed by strict JSON with key `boxes`. "
        "Each box must be `{label,bbox,confidence}` with bbox normalized [x1,y1,x2,y2] in 0..1.",
    ]
)

PRO_LEAP_CHAT_SYSTEM_PREAMBLE = (
    "You are NU:TONIC PRO on-device vision (Liquid Leap). Follow the user message exactly. "
    f"{SYSTEM_OPTICAL_LIMITS} "
    "When producing structured output, use JSON with keys caption (string) and boxes "
    "(array of objects with label, bbox, confidence) using bbox normalized [x1,y1,x2,y2] in 0..1."
)

FIREWATCH_CHANGE_CAPTION = (
    "These two Sentinel-2 images show the same area at two times "
    "({date_t0} and {date_t1}). Identify wildfire damage or burn-scar changes."
)

FIREWATCH_GROUNDING = (
    "Locate burn-scar and fire-affected regions visible in the post-event image. "
    "Return JSON list with labels and normalized bboxes."
)

OCEANSCOUT_DETECT = (
    "Examine this Sentinel-2 coastal/ocean image and identify potential vessel candidates "
    "or maritime activity."
)

OCEANSCOUT_GROUNDING = (
    "Locate potential vessel candidates in this image and return JSON list with normalized bboxes."
)

LANDSHIFT_CHANGE_CAPTION = (
    "Compare these two Sentinel-2 images ({date_t0} and {date_t1}) and describe major land-cover transitions."
)

LANDSHIFT_GROUNDING = (
    "Locate major land-cover transition regions and return JSON list with labels and normalized bboxes."
)

FLOODPULSE_CHANGE_CAPTION = (
    "Compare these two Sentinel-2 images ({date_t0} baseline and {date_t1} flood period) "
    "and describe flood-related water expansion."
)

FLOODPULSE_GROUNDING = (
    "Locate flooded or newly inundated regions in the second image and return JSON list with normalized bboxes."
)

BRIEF_COMPOSER_PROMPT = (
    "You are given multiple geospatial analysis images from the same region. "
    "Write a concise analytical brief with key findings, confidence, and recommended follow-up actions."
)

