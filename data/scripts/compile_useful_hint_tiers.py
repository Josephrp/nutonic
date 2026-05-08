#!/usr/bin/env python3
"""
Compile six-tier coordinate-free useful_hints from geo_context/*.json.

Normative: docs/scripts/SPEC-compile-useful-hint-tiers.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from string import Formatter
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GEO_DIR = REPO_ROOT / "data" / "cache" / "dev" / "geo_context"
DEFAULT_POLICY = Path(__file__).resolve().parent / "tier_policy.default.yaml"
DEFAULT_CONTENT_VERSION = "dev"


class _SafeFormat(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


def _load_policy(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Tier policy not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("Policy root must be a mapping")
    return raw


def _tier_count(pol: Mapping[str, Any]) -> int:
    n = int(pol.get("tier_count", 6))
    return max(1, min(12, n))


def _max_lens(pol: Mapping[str, Any], n: int) -> dict[str, int]:
    defaults = {1: 220, 2: 260, 3: 280, 4: 220, 5: 180, 6: 220}
    ml = pol.get("max_length") or {}
    out: dict[str, int] = {}
    for i in range(1, n + 1):
        k = f"tier_{i}"
        v = ml.get(k) if isinstance(ml, dict) else None
        if v is None:
            v = pol.get(f"max_len_{k}")
        if v is None:
            v = defaults.get(i, 200)
        out[k] = int(v)
    return out


def _templates(pol: Mapping[str, Any], n: int) -> dict[str, str]:
    t = pol.get("templates") or {}
    if not isinstance(t, dict):
        raise ValueError("Policy 'templates' must be a mapping")
    out: dict[str, str] = {}
    for i in range(1, n + 1):
        k = f"tier_{i}"
        s = t.get(k)
        if not isinstance(s, str) or not s.strip():
            raise ValueError(f"Missing template for {k}")
        out[k] = s.strip()
    return out


def _facts_from_geo_context(obj: Mapping[str, Any]) -> dict[str, Any]:
    inner = obj.get("hint_compile_facts")
    if isinstance(inner, dict) and inner.get("schema_version"):
        base = dict(inner)
    else:
        base = {
            "continent": obj.get("continent") or "Unknown continent",
            "hemisphere": "Northern" if float(obj.get("truth", {}).get("lat", 0.0) or 0.0) >= 0 else "Southern",
            "latitude_band": "unknown",
            "admin0_name": obj.get("admin0_name") or "",
            "admin1_name": obj.get("admin1_name") or "",
            "marine_framing": "Maritime framing unavailable.",
            "hydro_framing": "Hydrology framing unavailable.",
            "hydro_framing_short": "Hydrology context thin.",
        }
        nr = obj.get("nearest_river") or {}
        nl = obj.get("nearest_lake") or {}
        if isinstance(nr, dict):
            base["nearest_river_label"] = nr.get("name") or ""
        if isinstance(nl, dict):
            base["nearest_lake_label"] = nl.get("name") or ""

    admin0 = str(base.get("admin0_name") or "").strip()
    admin1 = str(base.get("admin1_name") or "").strip()
    base["admin0_clause"] = f"Country-scale name in use: {admin0}." if admin0 else "Country-scale name not resolved."
    base["admin1_clause"] = f"Subnational context: {admin1}." if admin1 else "Subnational context not resolved."
    if admin1:
        base["subnational_framing"] = f"Subnational unit emphasis: {admin1} (vector baseline labels only)."
    else:
        base["subnational_framing"] = "Subnational unit not resolved; stay with continental and hydro framing above."
    return base


def _cap(s: str, max_len: int) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    if max_len <= 1:
        return "…"
    return s[: max_len - 1].rstrip() + "…"


def compile_one(
    geo: Mapping[str, Any],
    pol: Mapping[str, Any],
) -> dict[str, Any]:
    n = _tier_count(pol)
    facts = _facts_from_geo_context(geo)
    tmpl = _templates(pol, n)
    max_lens = _max_lens(pol, n)
    fmt = _SafeFormat(facts)
    useful: dict[str, str] = {}
    for i in range(1, n + 1):
        k = f"tier_{i}"
        raw = Formatter().vformat(tmpl[k], (), fmt)
        useful[k] = _cap(raw, max_lens[k])
    location_id = str(geo.get("location_id") or "")
    facts_used = {k: facts[k] for k in sorted(facts) if k != "schema_version"}
    return {
        "location_id": location_id,
        "useful_hints": useful,
        "facts_used": facts_used,
        "facts_used_ref": f"geo_context/{location_id}.json",
    }


def run_compile(
    geo_context_dir: Path,
    policy_path: Path,
    output_dir: Path,
    *,
    skip_validate: bool,
) -> int:
    if not geo_context_dir.is_dir():
        print(f"Not a directory: {geo_context_dir}", file=sys.stderr)
        return 6
    try:
        pol = _load_policy(policy_path)
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 6

    paths = sorted(geo_context_dir.glob("*.json"))
    if not paths:
        print(f"No geo_context JSON in {geo_context_dir}", file=sys.stderr)
        return 6

    from validate_hint_strings import HintPolicy, validate_hints

    output_dir.mkdir(parents=True, exist_ok=True)

    for p in paths:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"{p}: {e}", file=sys.stderr)
            return 7
        if not isinstance(obj, dict):
            print(f"{p}: expected object", file=sys.stderr)
            return 7
        try:
            out = compile_one(obj, pol)
        except (ValueError, KeyError) as e:
            print(f"{p}: compile error: {e}", file=sys.stderr)
            return 7

        payload = {
            "location_id": out["location_id"],
            "useful_hints": out["useful_hints"],
            "facts_used": out["facts_used"],
            "facts_used_ref": out["facts_used_ref"],
        }
        if not skip_validate:
            violations = validate_hints(payload, HintPolicy.from_yaml_path(policy_path))
            if violations:
                for v in violations:
                    print(f"{p}: {v.format_line()}", file=sys.stderr)
                return 8

        dest = output_dir / f"{out['location_id']}.json"
        dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(dest.as_posix())

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile useful_hints tiers from geo_context JSON.")
    parser.add_argument("--geo-context-dir", type=Path, default=DEFAULT_GEO_DIR)
    parser.add_argument("--tier-policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument(
        "--content-version",
        default=__import__("os").environ.get("NUTONIC_CONTENT_VERSION", DEFAULT_CONTENT_VERSION),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Default: data/cache/<content-version>/useful_hints",
    )
    parser.add_argument("--skip-validate", action="store_true", help="Skip validate_hints (debug only).")
    args = parser.parse_args(argv)
    out_dir = args.output_dir
    if out_dir is None:
        out_dir = REPO_ROOT / "data" / "cache" / str(args.content_version) / "useful_hints"
    return run_compile(
        args.geo_context_dir.resolve(),
        args.tier_policy.resolve(),
        out_dir.resolve(),
        skip_validate=args.skip_validate,
    )


if __name__ == "__main__":
    raise SystemExit(main())
