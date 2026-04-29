#!/usr/bin/env python3
"""
Post-process existing VLM SFT datasets to reduce data leakage / over-precision.

Targets common issues observed in:
- NuTonic/sat-bbox-metadata-sft-v1
- NuTonic/sat-image-boundingbox-sft-full

This script is intentionally deterministic (rule-based) so it can be applied
reproducibly in CI and to already-published corpora.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ----------------------------
# Redaction / normalization
# ----------------------------

# Percent-like tokens (e.g. 23.9%, 0.31%, 15.0%).
_PCT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)%")

# Coordinate-ish tokens (lat/lon fields or "centered near 52.44480°, -8.92879°").
_COORD_KW_RE = re.compile(r"\b(latitude|longitude|coordinates_wgs84)\b", flags=re.IGNORECASE)
_CENTERED_NEAR_RE = re.compile(
    r"centered near\s+[-+]?\d+(?:\.\d+)?°\s*,\s*[-+]?\d+(?:\.\d+)?°\.?",
    flags=re.IGNORECASE,
)

# Mapbox geocoding / address leakage patterns.
_ISO_COUNTRY_RE = re.compile(r"\bISO country:\s*[A-Z]{2}\.?", flags=re.IGNORECASE)
_VICINITY_RE = re.compile(r"\bVicinity:\s*[^.\n]{1,200}\.?", flags=re.IGNORECASE)

# "Production-like analysis" prompt bloat: large embedded JSON blocks.
_TIM_JSON_BLOCK_RE = re.compile(
    r"(?s)(- TiM-style analytics JSON.*?:\s*)\{.*?\}\s*\n\s*\nTask:",
    flags=re.IGNORECASE,
)

# Same block, but capturing the JSON so we can minify it (keep content, drop whitespace).
_TIM_JSON_BLOCK_CAPTURE_RE = re.compile(
    r"(?s)(- TiM-style analytics JSON.*?:\s*)"
    r"(?P<json>\{.*?\})"
    r"(\s*\n\s*\nTask:)",
    flags=re.IGNORECASE,
)

# Very technical user-turn signals (keep broad, we only use this as a trigger).
_TECH_TRIGGER_RE = re.compile(
    r"\b(schema_version|class_fractions|tok_lulc@224|tim_modality_outputs|procedural_fraction_delta)\b",
    flags=re.IGNORECASE,
)


def _quantize_percent(num_str: str, *, step: int = 5) -> str:
    """
    Map a percent string to a coarse, non-precise band.
    Example: 23.9% -> ~25%, 0.31% -> <1%, 1.4% -> ~0% or ~0? (we map smalls to <1%).
    """
    try:
        v = float(num_str)
    except ValueError:
        return f"~{num_str}%"
    if v < 1.0:
        return "<1%"
    if v < 3.0:
        return "~2%"
    q = int(step * round(v / step))
    q = max(step, min(100, q))
    return f"~{q}%"


def deprecision_percentages(text: str) -> tuple[str, int]:
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        return _quantize_percent(m.group("num"))

    return _PCT_RE.sub(_sub, text), n


def redact_location_leaks(text: str) -> tuple[str, int]:
    """
    Remove direct location references like coordinates, ISO country tags, and vicinity/address strings.
    Keeps the prompt semantics but eliminates place leakage.
    """
    changed = 0
    out = text

    out2 = _CENTERED_NEAR_RE.sub("centered near an unspecified location.", out)
    if out2 != out:
        changed += 1
        out = out2

    out2 = _ISO_COUNTRY_RE.sub("", out)
    if out2 != out:
        changed += 1
        out = out2

    out2 = _VICINITY_RE.sub("", out)
    if out2 != out:
        changed += 1
        out = out2

    # If user text embeds lat/lon keys (usually via JSON), do not try to surgically rewrite it here;
    # the TiM JSON block redaction handles most cases. This keyword check is for reporting only.
    return out, changed


def redact_tim_json_blob(text: str) -> tuple[str, int]:
    """
    Replace a long embedded TiM-shaped JSON block with a compact placeholder.
    This removes high-precision numeric signals (fractions, thresholds) and coordinates in one shot.
    """
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        head = m.group(1).rstrip()
        return (
            f"{head}\n"
            "<omitted: TiM-shaped JSON removed to avoid overfitting to precise numeric/geo details>\n\n"
            "Task:"
        )

    return _TIM_JSON_BLOCK_RE.sub(_sub, text), n


def minify_tim_json_blob(text: str) -> tuple[str, int]:
    """
    Keep the TiM JSON content but remove indentation/whitespace by re-parsing and re-dumping compactly.
    This often saves a large number of tokens while preserving the full signal.
    """
    n = 0

    def _sub(m: re.Match[str]) -> str:
        nonlocal n
        js = m.group("json")
        try:
            obj = json.loads(js)
        except Exception:
            return m.group(0)
        n += 1
        compact = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        return f"{m.group(1)}{compact}{m.group(3)}"

    return _TIM_JSON_BLOCK_CAPTURE_RE.sub(_sub, text), n


def trim_assistant_text(text: str, *, max_chars: int) -> tuple[str, int]:
    if len(text) <= max_chars:
        return text, 0
    # Prefer trimming at a sentence boundary.
    cut = text[: max_chars - 1]
    m = re.search(r"[\.\!\?]\s", cut[::-1])
    if m:
        # m.start() is in reversed string; compute forward index.
        idx = len(cut) - m.start()
        cut = cut[:idx].rstrip()
    return cut.rstrip() + "\n\n[trimmed]", 1


def normalize_text(
    text: str,
    *,
    max_chars: int,
    redact_tim_json: bool,
    minify_tim_json: bool,
) -> tuple[str, dict[str, int]]:
    stats: dict[str, int] = {}

    if minify_tim_json and not redact_tim_json:
        t, n = minify_tim_json_blob(text)
        if n:
            stats["tim_json_minified"] = n
        text = t

    if redact_tim_json:
        t, n = redact_tim_json_blob(text)
        if n:
            stats["tim_json_redacted"] = n
        text = t

    t, n = redact_location_leaks(text)
    if n:
        stats["location_redacted"] = n
    text = t

    # Only de-precision after removing big JSON blocks (otherwise we'd touch huge blobs).
    t, n = deprecision_percentages(text)
    if n:
        stats["percent_deprecision"] = n
    text = t

    t, n = trim_assistant_text(text, max_chars=max_chars)
    if n:
        stats["assistant_trimmed"] = n
    text = t

    # If any coord keywords remain, flag them (best-effort; not a rewrite).
    if _COORD_KW_RE.search(text):
        stats["coord_kw_remaining"] = stats.get("coord_kw_remaining", 0) + 1

    return text, stats


# ----------------------------
# JSON row traversal
# ----------------------------


def _iter_message_text_parts(row: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """
    Return list of (part_dict, role) for text parts across all messages.
    `part_dict` is mutated in-place by the caller.
    """
    out: list[tuple[dict[str, Any], str]] = []
    msgs = row.get("messages")
    if not isinstance(msgs, list):
        return out
    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        content = msg.get("content")
        if isinstance(content, str):
            # Some datasets store plain strings. Normalize to a virtual text part.
            out.append(({"_string_content": True, "text": content}, role))
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    out.append((part, role))
    return out


def _iter_text_parts_in_message(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return mutable text parts inside a single {role, content} message."""
    out: list[dict[str, Any]] = []
    content = msg.get("content")
    if isinstance(content, str):
        out.append({"_string_content": True, "text": content})
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                out.append(part)
    return out


def _rewrite_row_in_place(row: dict[str, Any], *, max_assistant_chars: int) -> dict[str, int]:
    pp = row.get("_postprocess")
    redact_tim_json = bool(pp.get("redact_tim_json")) if isinstance(pp, dict) else False
    minify_tim_json = bool(pp.get("minify_tim_json")) if isinstance(pp, dict) else False
    counts: dict[str, int] = {}

    parts = _iter_message_text_parts(row)
    for part, role in parts:
        key = "text"
        if part.get("_string_content") is True:
            key = "text"
        old = part.get(key)
        if not isinstance(old, str) or not old.strip():
            continue

        # Different trimming policy for user vs assistant.
        max_chars = max_assistant_chars if role == "assistant" else 64_000

        new, st = normalize_text(
            old,
            max_chars=max_chars,
            redact_tim_json=redact_tim_json,
            minify_tim_json=minify_tim_json,
        )

        # Extra guard: if the user prompt is extremely technical (trigger) *and* still contains JSON-ish braces,
        # squash it to a short instruction so it doesn't dominate the finetune mix.
        if role == "user" and _TECH_TRIGGER_RE.search(new) and "{" in new and "}" in new and len(new) > 4000:
            counts["tech_user_squashed"] = counts.get("tech_user_squashed", 0) + 1
            new = (
                "You are given satellite imagery and a compact model-produced analytics summary. "
                "Write a brief, evidence-grounded analytical summary and clearly distinguish what you see "
                "in the imagery from what is suggested by the auxiliary analytics."
            )

        if new != old:
            part[key] = new

        for k, v in st.items():
            counts[k] = counts.get(k, 0) + int(v)

    # If we created virtual text part(s), fold them back into string content.
    msgs = row.get("messages")
    if isinstance(msgs, list):
        for msg in msgs:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, list):
                continue
            # If content is a string, we replaced it via a virtual part and should persist.
            # Find first virtual part for this role.
            if isinstance(content, str):
                role = str(msg.get("role") or "")
                for part, r in parts:
                    if r == role and part.get("_string_content") is True:
                        msg["content"] = str(part.get("text") or "")
                        break

    return counts


def _rewrite_message_in_place(
    msg: dict[str, Any],
    *,
    max_assistant_chars: int,
    redact_tim_json: bool,
    minify_tim_json: bool,
) -> dict[str, int]:
    """Rewrite a single message dict in-place; returns change counters."""
    counts: dict[str, int] = {}
    role = str(msg.get("role") or "")
    parts = _iter_text_parts_in_message(msg)

    for part in parts:
        old = part.get("text")
        if not isinstance(old, str) or not old.strip():
            continue
        max_chars = max_assistant_chars if role == "assistant" else 64_000
        new, st = normalize_text(
            old,
            max_chars=max_chars,
            redact_tim_json=redact_tim_json,
            minify_tim_json=minify_tim_json,
        )

        if role == "user" and _TECH_TRIGGER_RE.search(new) and "{" in new and "}" in new and len(new) > 4000:
            counts["tech_user_squashed"] = counts.get("tech_user_squashed", 0) + 1
            new = (
                "You are given satellite imagery and a compact model-produced analytics summary. "
                "Write a brief, evidence-grounded analytical summary and clearly distinguish what you see "
                "in the imagery from what is suggested by the auxiliary analytics."
            )

        if new != old:
            part["text"] = new

        for k, v in st.items():
            counts[k] = counts.get(k, 0) + int(v)

    # Persist virtual part back to string content if needed.
    if isinstance(msg.get("content"), str):
        for part in parts:
            if part.get("_string_content") is True:
                msg["content"] = str(part.get("text") or "")
                break

    return counts


def _load_any_json(path: Path) -> Any:
    """
    Load JSON from disk.

    Supports:
    - Standard JSON (single top-level value)
    - "Multi-JSON" files that contain multiple top-level JSON values concatenated
      (commonly multiple lists one after another), as seen in some sample extracts.
    """
    text = path.read_text(encoding="utf-8")
    dec = json.JSONDecoder()
    i = 0
    values: list[Any] = []
    n = len(text)
    while i < n:
        # Skip whitespace.
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        val, end = dec.raw_decode(text, i)
        values.append(val)
        i = end
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    # If the file is multiple lists, concatenate them; otherwise return the sequence.
    if all(isinstance(v, list) for v in values):
        out: list[Any] = []
        for v in values:
            out.extend(v)
        return out
    return values


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        rows.append(json.loads(s))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


@dataclass
class RunStats:
    rows_in: int = 0
    rows_out: int = 0
    by_change: dict[str, int] = field(default_factory=dict)

    def add(self, counts: dict[str, int]) -> None:
        for k, v in counts.items():
            self.by_change[k] = self.by_change.get(k, 0) + int(v)


def postprocess_rows(rows: list[dict[str, Any]], *, max_assistant_chars: int) -> tuple[list[dict[str, Any]], RunStats]:
    stats = RunStats(rows_in=len(rows), rows_out=len(rows))
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Back-compat: allow callers to set a per-row flag via a reserved key.
        row.setdefault("_postprocess", {})
        counts = _rewrite_row_in_place(row, max_assistant_chars=max_assistant_chars)
        stats.add(counts)
        out.append(row)
    stats.rows_out = len(out)
    return out, stats


def postprocess_message_list(
    messages: list[dict[str, Any]],
    *,
    max_assistant_chars: int,
    redact_tim_json: bool,
    minify_tim_json: bool,
) -> tuple[list[dict[str, Any]], RunStats]:
    """
    Post-process a standalone list of {role, content} messages.
    Some sample extracts are stored as message arrays rather than HF rows.
    """
    stats = RunStats(rows_in=len(messages), rows_out=len(messages))
    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict) or "role" not in msg:
            continue
        counts = _rewrite_message_in_place(
            msg,
            max_assistant_chars=max_assistant_chars,
            redact_tim_json=redact_tim_json,
            minify_tim_json=minify_tim_json,
        )
        stats.add(counts)
        out.append(msg)
    stats.rows_out = len(out)
    return out, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--in",
        dest="in_path",
        type=Path,
        required=True,
        help="Input file: .jsonl (HF-style rows) or .json (list of chat rows).",
    )
    ap.add_argument("--out", dest="out_path", type=Path, required=True, help="Output file path.")
    ap.add_argument(
        "--max-assistant-chars",
        type=int,
        default=900,
        help="Hard cap assistant text length (post-trim).",
    )
    ap.add_argument(
        "--redact-tim-json",
        action="store_true",
        help="Opt-in: redact large embedded TiM JSON blocks in prompts (default: keep).",
    )
    ap.add_argument(
        "--minify-tim-json",
        action="store_true",
        help="Opt-in: keep TiM JSON but minify it (compact JSON, no indentation).",
    )
    ap.add_argument(
        "--max-user-chars",
        type=int,
        default=0,
        help="If >0: drop examples whose user text exceeds this many characters (after processing).",
    )
    ap.add_argument(
        "--max-total-chars",
        type=int,
        default=0,
        help="If >0: drop examples whose combined (user+assistant) text exceeds this many characters (after processing).",
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON report path for change counts.",
    )
    args = ap.parse_args()

    in_path: Path = args.in_path
    out_path: Path = args.out_path

    if in_path.suffix.lower() == ".jsonl":
        rows = _iter_jsonl(in_path)
        for r in rows:
            if not isinstance(r, dict):
                continue
            r.setdefault("_postprocess", {})
            if isinstance(r["_postprocess"], dict):
                if args.redact_tim_json:
                    r["_postprocess"]["redact_tim_json"] = True
                if args.minify_tim_json:
                    r["_postprocess"]["minify_tim_json"] = True
        out_rows, st = postprocess_rows(rows, max_assistant_chars=int(args.max_assistant_chars))
        out_rows = filter_overlong_rows(
            out_rows,
            max_user_chars=int(args.max_user_chars),
            max_total_chars=int(args.max_total_chars),
            stats=st,
        )
        _write_jsonl(out_path, out_rows)
    else:
        data = _load_any_json(in_path)
        if not isinstance(data, list):
            raise SystemExit(f"--in must be .jsonl or a .json list; got {type(data).__name__}")
        # If this looks like a raw messages array (extracts), process as messages.
        if data and isinstance(data[0], dict) and "role" in data[0] and "content" in data[0] and "messages" not in data[0]:
            out_rows, st = postprocess_message_list(
                [m for m in data if isinstance(m, dict)],
                max_assistant_chars=int(args.max_assistant_chars),
                redact_tim_json=bool(args.redact_tim_json),
                minify_tim_json=bool(args.minify_tim_json),
            )
            _write_json(out_path, out_rows)
        else:
            # In JSON list-of-rows mode, we only support redacting TiM JSON when requested.
            for r in data:
                if not isinstance(r, dict):
                    continue
                r.setdefault("_postprocess", {})
                if isinstance(r["_postprocess"], dict):
                    if args.redact_tim_json:
                        r["_postprocess"]["redact_tim_json"] = True
                    if args.minify_tim_json:
                        r["_postprocess"]["minify_tim_json"] = True
            out_rows, st = postprocess_rows(
                [r for r in data if isinstance(r, dict)],
                max_assistant_chars=int(args.max_assistant_chars),
            )
            out_rows = filter_overlong_rows(
                out_rows,
                max_user_chars=int(args.max_user_chars),
                max_total_chars=int(args.max_total_chars),
                stats=st,
            )
            _write_json(out_path, out_rows)

    report_obj = {
        "rows_in": st.rows_in,
        "rows_out": st.rows_out,
        "changes": dict(sorted(st.by_change.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    if args.report is not None:
        _write_json(Path(args.report), report_obj)
    else:
        print(json.dumps(report_obj, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def _row_text_lengths(row: dict[str, Any]) -> tuple[int, int]:
    """
    Return (user_chars, assistant_chars) based on concatenated text parts.
    This is a cheap proxy for token budget.
    """
    user = 0
    assistant = 0
    msgs = row.get("messages")
    if not isinstance(msgs, list):
        return (0, 0)
    for msg in msgs:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        content = msg.get("content")
        if isinstance(content, str):
            n = len(content)
        elif isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
                    parts.append(p["text"])
            n = len("\n".join(parts))
        else:
            n = 0
        if role == "user":
            user += n
        elif role == "assistant":
            assistant += n
    return (user, assistant)


def filter_overlong_rows(
    rows: list[dict[str, Any]],
    *,
    max_user_chars: int,
    max_total_chars: int,
    stats: RunStats | None = None,
) -> list[dict[str, Any]]:
    """
    Drop rows exceeding char budgets. Updates stats.by_change with drop counters.
    """
    if max_user_chars <= 0 and max_total_chars <= 0:
        return rows
    out: list[dict[str, Any]] = []
    dropped_user = 0
    dropped_total = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        u, a = _row_text_lengths(r)
        if max_user_chars > 0 and u > max_user_chars:
            dropped_user += 1
            continue
        if max_total_chars > 0 and (u + a) > max_total_chars:
            dropped_total += 1
            continue
        out.append(r)
    if stats is not None:
        if dropped_user:
            stats.by_change["dropped_user_too_long"] = stats.by_change.get("dropped_user_too_long", 0) + dropped_user
        if dropped_total:
            stats.by_change["dropped_total_too_long"] = stats.by_change.get("dropped_total_too_long", 0) + dropped_total
        stats.rows_out = len(out)
    return out

