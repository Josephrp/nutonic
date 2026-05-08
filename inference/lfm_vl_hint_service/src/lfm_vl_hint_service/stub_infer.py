"""Deterministic caption stub (no torch) for local ``tools/batch_streetview_hints`` runs."""

from __future__ import annotations

from lfm_vl_hint_service.models import (
    HintFrame,
    SuggestionItem,
    SuggestionsFromFramesRequest,
    SuggestionsFromFramesResponse,
)


def _caption_for_frame(fr: HintFrame, idx: int, *, ranked_safe: bool) -> str:
    """Produce coordinate-free stub captions."""
    hid = fr.pano_id or f"frame-{idx}"
    head = int(fr.heading_deg) if fr.heading_deg is not None else idx * 60
    if ranked_safe:
        return (
            f"Street-level view {idx + 1}: mixed urban textures and roadside elements "
            f"at approximately {head % 360} degree bearing (viewpoint {hid})."
        )
    return f"Open scene {idx + 1} with varied lighting (viewpoint {hid})."


def infer_from_frames_stub(req: SuggestionsFromFramesRequest) -> SuggestionsFromFramesResponse:
    """Stub multi-image → suggestions (default ``LFM_VL_BACKEND=stub``)."""
    out: list[SuggestionItem] = []
    for i, fr in enumerate(req.frames):
        vid = fr.pano_id if fr.pano_id else f"decoy-{i}"
        text = _caption_for_frame(fr, i, ranked_safe=req.ranked_clue_safe)
        out.append(SuggestionItem(text=text, viewpoint_id=vid, rank=i + 1))
    return SuggestionsFromFramesResponse(suggestions=out)
