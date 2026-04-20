#!/usr/bin/env python3
"""
Validate useful-hints JSON for spoiler hygiene, length caps, and empty-tier rules.

Normative: docs/scripts/SPEC-validate-hint-strings.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Sequence
from typing import Any, Mapping

import yaml

# Two high-precision decimals separated by a comma — typical lat/lon literals.
_COORD_PAIR_RE = re.compile(
    r"(?P<a>-?\d{1,3}\.\d{4,})\s*,\s*(?P<b>-?\d{1,3}\.\d{4,})",
)

_DEFAULT_MAX = {1: 220, 2: 260, 3: 280, 4: 220, 5: 180, 6: 220}


def _tier_key(i: int) -> str:
    return f"tier_{i}"


@dataclass
class Violation:
    """Single validation failure (library + CLI)."""

    code: str
    message: str
    path: str = ""

    def format_line(self) -> str:
        prefix = f"{self.path}: " if self.path else ""
        return f"{prefix}[{self.code}] {self.message}"


@dataclass
class HintPolicy:
    """Loaded from optional YAML; defaults match six-tier coordinate-free hints."""

    tier_count: int = 6
    max_lens: dict[str, int] = field(default_factory=dict)
    banned_substrings: list[str] = field(default_factory=list)
    coordinate_literal_check: bool = True
    enforce_max_tier_contains_admin0: bool = False
    # Legacy single-field caps (used when YAML omits max_length block)
    max_len_tier_1: int = 280
    max_len_tier_2: int = 280
    max_len_tier_3: int = 200

    def __post_init__(self) -> None:
        if self.tier_count < 1:
            self.tier_count = 1
        if self.tier_count > 12:
            self.tier_count = 12
        if not self.max_lens:
            for i in range(1, self.tier_count + 1):
                k = _tier_key(i)
                if i == 1:
                    self.max_lens[k] = self.max_len_tier_1
                elif i == 2:
                    self.max_lens[k] = self.max_len_tier_2
                elif i == 3:
                    self.max_lens[k] = self.max_len_tier_3
                else:
                    self.max_lens[k] = _DEFAULT_MAX.get(i, 200)

    def max_len_for(self, tier_key: str) -> int:
        return int(self.max_lens.get(tier_key, 200))

    def tier_keys(self) -> tuple[str, ...]:
        return tuple(_tier_key(i) for i in range(1, self.tier_count + 1))

    @classmethod
    def from_yaml_path(cls, path: Path | None) -> HintPolicy:
        if path is None or not path.is_file():
            return cls()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            return cls()
        tier_count = int(raw.get("tier_count", 6))
        tier_count = max(1, min(12, tier_count))
        max_len_block = raw.get("max_length") or {}
        lens: dict[str, int] = {}
        for i in range(1, tier_count + 1):
            k = _tier_key(i)
            if isinstance(max_len_block, dict) and k in max_len_block:
                lens[k] = int(max_len_block[k])
            elif raw.get(f"max_len_{k}") is not None:
                lens[k] = int(raw[f"max_len_{k}"])
            elif i <= 3:
                legacy = (
                    int(max_len_block.get("tier_1", raw.get("max_len_tier_1", 280))),
                    int(max_len_block.get("tier_2", raw.get("max_len_tier_2", 280))),
                    int(max_len_block.get("tier_3", raw.get("max_len_tier_3", 200))),
                )
                lens[k] = legacy[i - 1]
            else:
                lens[k] = int(_DEFAULT_MAX.get(i, 200))
        banned = raw.get("banned_substrings") or []
        if not isinstance(banned, list):
            banned = []
        return cls(
            tier_count=tier_count,
            max_lens=lens,
            banned_substrings=[str(x) for x in banned],
            coordinate_literal_check=bool(raw.get("coordinate_literal_check", True)),
            enforce_max_tier_contains_admin0=bool(
                raw.get("enforce_max_tier_contains_admin0", raw.get("enforce_tier3_contains_admin0", False))
            ),
            max_len_tier_1=int(max_len_block.get("tier_1", raw.get("max_len_tier_1", 280))),
            max_len_tier_2=int(max_len_block.get("tier_2", raw.get("max_len_tier_2", 280))),
            max_len_tier_3=int(max_len_block.get("tier_3", raw.get("max_len_tier_3", 200))),
        )


def _nested_hints(obj: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return (hints dict, assist_level from wrapper)."""
    assist = obj.get("assist_level")
    if assist is not None and not isinstance(assist, str):
        assist = str(assist)
    inner = obj.get("useful_hints")
    if inner is not None and not isinstance(inner, dict):
        return {}, assist
    if isinstance(inner, dict):
        merged = {**inner}
        if "assist_level" not in merged and assist is not None:
            merged["assist_level"] = assist
        return merged, assist if assist is not None else merged.get("assist_level")
    keys = HintPolicy().tier_keys()
    if any(k in obj for k in keys):
        return dict(obj), assist
    return {}, assist


def _tier_strings(hints: Mapping[str, Any], tier_keys: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k in tier_keys:
        v = hints.get(k)
        if v is None:
            out[k] = ""
        elif isinstance(v, str):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _assist_requires_tiers(assist: str | None) -> bool:
    if assist is None or assist == "":
        return True
    return str(assist).strip().lower() != "none"


def _coordinate_violation(text: str, path: str) -> Violation | None:
    m = _COORD_PAIR_RE.search(text)
    if not m:
        return None
    return Violation(
        code="coordinate_literal",
        message="Possible decimal-degree pair (comma-separated high-precision numbers).",
        path=path,
    )


def _banned_hit(text: str, banned: list[str], path: str) -> Violation | None:
    lower = text.lower()
    for token in banned:
        t = token.lower()
        if t and t in lower:
            return Violation(
                code="banned_substring",
                message=f"Contains banned token {token!r}.",
                path=path,
            )
    return None


def validate_hints(obj: Any, policy: HintPolicy | None = None) -> list[Violation]:
    """
    Validate a parsed JSON object (standalone useful_hints or manifest slice).

    Accepts either {"tier_1": ...} or {"useful_hints": {...}, "assist_level": ...}.
    """
    pol = policy or HintPolicy()
    violations: list[Violation] = []
    tier_keys = pol.tier_keys()

    if not isinstance(obj, dict):
        return [
            Violation(
                code="root_type",
                message="Root JSON value must be an object.",
                path="$",
            )
        ]

    hints, _assist_outer = _nested_hints(obj)
    if not hints:
        return [
            Violation(
                code="missing_tiers",
                message=f"No useful_hints tier fields ({', '.join(tier_keys)}) found.",
                path="$",
            )
        ]

    assist = hints.get("assist_level")
    if assist is not None and not isinstance(assist, str):
        assist = str(assist)
    requires = _assist_requires_tiers(assist)

    for tk in tier_keys:
        if tk not in hints:
            violations.append(
                Violation(
                    code="missing_tier_key",
                    message=f"Missing required key {tk!r} for tier_count={pol.tier_count}.",
                    path=tk,
                )
            )

    tiers = _tier_strings(hints, tier_keys)

    for key in tier_keys:
        s = tiers.get(key, "")
        p = key
        cap = pol.max_len_for(key)
        if len(s) > cap:
            violations.append(
                Violation(
                    code="length_cap",
                    message=f"{key} length {len(s)} exceeds max {cap}.",
                    path=p,
                )
            )
        if pol.coordinate_literal_check:
            cv = _coordinate_violation(s, p)
            if cv:
                violations.append(cv)
        bv = _banned_hit(s, pol.banned_substrings, p)
        if bv:
            violations.append(bv)

    if requires:
        for key in tier_keys:
            if not tiers.get(key, "").strip():
                violations.append(
                    Violation(
                        code="empty_tier",
                        message=f"{key} must be non-empty when assist_level is not 'none'.",
                        path=key,
                    )
                )

    facts = obj.get("facts_used") if isinstance(obj, dict) else None
    if pol.enforce_max_tier_contains_admin0 and isinstance(facts, dict):
        admin0 = facts.get("admin0_name")
        max_key = _tier_key(pol.tier_count)
        if isinstance(admin0, str) and admin0.strip():
            tlast = tiers.get(max_key, "")
            if admin0.lower() not in tlast.lower():
                violations.append(
                    Violation(
                        code="max_tier_admin0",
                        message=f"{max_key} must mention facts_used.admin0_name when enforcement is on.",
                        path=max_key,
                    )
                )

    return violations


def violations_to_jsonable(violations: Sequence[Violation]) -> list[dict[str, str]]:
    """Serialize ``Violation`` rows for manifests and sidecars (attach, do not drop cache rows)."""
    return [{"code": v.code, "message": v.message, "path": v.path} for v in violations]


def validate_caption_text(
    text: str,
    *,
    max_len: int = 400,
    banned_substrings: Sequence[str] | None = None,
    path: str = "caption",
    coordinate_literal_check: bool = True,
) -> list[Violation]:
    """
    Validate a single Street View caption / narrative string (no tier schema).

    Used by ``tools/batch_streetview_hints`` before writing ``streetview_hint_pack``.
    """
    violations: list[Violation] = []
    if len(text) > max_len:
        violations.append(
            Violation(
                code="length_cap",
                message=f"Caption length {len(text)} exceeds max {max_len}.",
                path=path,
            )
        )
    if coordinate_literal_check:
        cv = _coordinate_violation(text, path)
        if cv:
            violations.append(cv)
    banned = list(banned_substrings or [])
    bv = _banned_hit(text, banned, path)
    if bv:
        violations.append(bv)
    return violations


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_path(path: Path, policy: HintPolicy) -> list[Violation]:
    try:
        data = _load_json(path)
    except json.JSONDecodeError as e:
        return [Violation("json_parse", str(e), path=str(path))]
    vs = validate_hints(data, policy)
    return [Violation(v.code, v.message, path=f"{path}:{v.path}" if v.path else str(path)) for v in vs]


def _scan_dir(root: Path, policy: HintPolicy) -> list[Violation]:
    all_v: list[Violation] = []
    for p in sorted(root.rglob("*.json")):
        all_v.extend(_validate_path(p, policy))
    return all_v


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate useful_hints JSON files.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=Path, help="Path to a single JSON file.")
    src.add_argument("--stdin", action="store_true", help="Read one JSON object from stdin.")
    src.add_argument("--scan-dir", type=Path, help="Validate every *.json under this directory.")
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="YAML policy (tier_count, max_length, banned_substrings, flags).",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write violations as JSON array to this path.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout (still writes stderr / json-out).",
    )
    args = parser.parse_args(argv)

    policy = HintPolicy.from_yaml_path(args.policy)
    violations: list[Violation] = []

    if args.input is not None:
        if not args.input.is_file():
            print(f"Not a file: {args.input}", file=sys.stderr)
            return 2
        violations = _validate_path(args.input, policy)
    elif args.stdin:
        try:
            raw = sys.stdin.read()
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            violations = [Violation("json_parse", str(e), path="stdin")]
        else:
            violations = [
                Violation(v.code, v.message, path=f"stdin:{v.path}" if v.path else "stdin")
                for v in validate_hints(data, policy)
            ]
    elif args.scan_dir is not None:
        if not args.scan_dir.is_dir():
            print(f"Not a directory: {args.scan_dir}", file=sys.stderr)
            return 2
        violations = _scan_dir(args.scan_dir, policy)

    if args.json_out is not None:
        payload = [{"code": v.code, "message": v.message, "path": v.path} for v in violations]
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if violations:
        for v in violations:
            print(v.format_line(), file=sys.stderr)
        return 1

    if not args.quiet:
        print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
