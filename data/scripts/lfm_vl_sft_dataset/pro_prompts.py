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

