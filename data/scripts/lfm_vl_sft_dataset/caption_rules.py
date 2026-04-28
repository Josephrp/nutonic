"""Rule-based captions for profile-specific PRO dataset rows."""

from __future__ import annotations

from dataclasses import dataclass

from lfm_vl_sft_dataset.change_instances import ChangeRegion


@dataclass(frozen=True)
class ChangeStats:
    total_change_px: int
    total_px: int
    mean_change_score: float | None = None


@dataclass(frozen=True)
class FloodStats:
    inundated_px: int
    total_px: int
    water_expansion_ratio: float | None = None


def _pct(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round(100.0 * float(num) / float(den), 1)


def firewatch_caption(regions: list[ChangeRegion], stats: ChangeStats) -> str:
    n = len(regions)
    p = _pct(stats.total_change_px, stats.total_px)
    if n == 0:
        return (
            "No clear burn-scar regions are detected above threshold in this optical comparison. "
            "Confidence is low for subtle fire effects."
        )
    top = regions[0]
    msg = (
        f"The pair suggests fire-related change in {n} region(s), covering about {p}% of the tile. "
        f"The largest region spans roughly {top.area_px} pixels."
    )
    if stats.mean_change_score is not None:
        msg += f" Mean burn-change score is {round(stats.mean_change_score, 3)}."
    msg += " This is optical-only evidence and may be affected by clouds, haze, and seasonal effects."
    return msg


def oceanscout_caption(regions: list[ChangeRegion], water_frac: float, obs_quality: str) -> str:
    n = len(regions)
    water_pct = round(100.0 * max(0.0, min(1.0, water_frac)), 1)
    if n == 0:
        return (
            f"No strong vessel candidate regions are detected. Water coverage is about {water_pct}%. "
            f"Observation quality: {obs_quality}. Optical-only view may miss small or low-contrast vessels."
        )
    return (
        f"Detected {n} potential vessel candidate region(s) over water (~{water_pct}% water coverage). "
        f"Observation quality: {obs_quality}. Detections are candidate-level optical findings, not confirmations."
    )


def landshift_caption(transition_matrix: dict[str, int], regions: list[ChangeRegion]) -> str:
    if not transition_matrix:
        return (
            "No dominant land-cover transitions are detected above threshold. "
            "Observed differences may be minor seasonal or acquisition variations."
        )
    top = sorted(transition_matrix.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_txt = ", ".join(f"{k} ({v})" for k, v in top)
    return (
        f"Major land-cover transitions are: {top_txt}. "
        f"{len(regions)} region(s) were localized for grounding in this pair."
    )


def floodpulse_caption(regions: list[ChangeRegion], stats: FloodStats) -> str:
    p = _pct(stats.inundated_px, stats.total_px)
    if not regions:
        return (
            f"No clear inundation expansion is detected above threshold; estimated flood-extent change is {p}%. "
            "Optical-only constraints and cloud effects may limit sensitivity."
        )
    msg = (
        f"Flood-related water expansion is detected in {len(regions)} region(s), "
        f"covering about {p}% of the tile."
    )
    if stats.water_expansion_ratio is not None:
        msg += f" Water expansion ratio is {round(stats.water_expansion_ratio, 3)}."
    msg += " Interpretation is based on optical imagery and should be treated as provisional."
    return msg


def brief_caption(findings: list[dict], profile_mix: list[str]) -> str:
    prof_txt = ", ".join(profile_mix) if profile_mix else "unspecified profiles"
    if not findings:
        return (
            f"Brief summary across {prof_txt}: no strong high-confidence findings were aggregated. "
            "Recommend additional temporal coverage and cross-sensor corroboration."
        )
    bullets: list[str] = []
    for f in findings[:4]:
        profile = str(f.get("profile", "profile"))
        headline = str(f.get("headline", "finding"))
        bullets.append(f"- {profile}: {headline}")
    return (
        f"Executive summary ({prof_txt}):\n"
        + "\n".join(bullets)
        + "\nConfidence: moderate, limited by optical-only evidence and dataset-derived heuristics."
    )

