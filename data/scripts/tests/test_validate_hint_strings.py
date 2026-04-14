"""Tests for validate_hint_strings.py — SPEC-validate-hint-strings.md."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from validate_hint_strings import HintPolicy, Violation, validate_hints

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCRIPT = REPO_ROOT / "data" / "scripts" / "validate_hint_strings.py"


def test_valid_fixture_has_no_violations() -> None:
    data = json.loads((FIXTURES / "hints_valid.json").read_text(encoding="utf-8"))
    assert validate_hints(data) == []


def test_bad_coords_fixture() -> None:
    data = json.loads((FIXTURES / "hints_bad_coords.json").read_text(encoding="utf-8"))
    vs = validate_hints(data)
    assert any(v.code == "coordinate_literal" for v in vs)


def test_empty_tier_when_assist_full() -> None:
    data = json.loads((FIXTURES / "hints_empty_tier.json").read_text(encoding="utf-8"))
    vs = validate_hints(data)
    assert any(v.code == "empty_tier" for v in vs)


def test_assist_none_allows_empty_tiers() -> None:
    data = json.loads((FIXTURES / "hints_assist_none_ok.json").read_text(encoding="utf-8"))
    assert validate_hints(data) == []


def test_length_policy() -> None:
    policy = HintPolicy(
        tier_count=3,
        max_lens={"tier_1": 5, "tier_2": 80, "tier_3": 80},
    )
    vs = validate_hints(
        {"tier_1": "123456", "tier_2": "ok", "tier_3": "ok"},
        policy,
    )
    assert any(v.code == "length_cap" for v in vs)


def test_banned_substrings() -> None:
    policy = HintPolicy(
        tier_count=3,
        max_lens={"tier_1": 80, "tier_2": 120, "tier_3": 80},
        banned_substrings=["truth_lat"],
    )
    vs = validate_hints(
        {
            "tier_1": "ok",
            "tier_2": "mentions truth_lat leak",
            "tier_3": "ok",
        },
        policy,
    )
    assert any(v.code == "banned_substring" for v in vs)


def test_nested_useful_hints_and_parent_assist_level() -> None:
    vs = validate_hints(
        {
            "map_id": "m1",
            "assist_level": "full",
            "useful_hints": {
                "tier_1": "a",
                "tier_2": "b",
                "tier_3": "",
                "tier_4": "d",
                "tier_5": "e",
                "tier_6": "f",
            },
        }
    )
    assert any(v.code == "empty_tier" for v in vs)


def test_non_object_root() -> None:
    assert validate_hints([])[0].code == "root_type"


def test_enforce_max_tier_contains_admin0() -> None:
    policy = HintPolicy(
        tier_count=1,
        max_lens={"tier_1": 200},
        enforce_max_tier_contains_admin0=True,
    )
    vs = validate_hints(
        {
            "tier_1": "Wrong country generic",
            "facts_used": {"admin0_name": "Indonesia"},
        },
        policy,
    )
    assert any(v.code == "max_tier_admin0" for v in vs)


def test_cli_ok_exit_code() -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(FIXTURES / "hints_valid.json")],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_cli_bad_exit_code() -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(FIXTURES / "hints_bad_coords.json")],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1
    assert "coordinate_literal" in r.stderr


@pytest.mark.parametrize(
    "payload,expect_codes",
    [
        (
            '{"tier_1":"a","tier_2":"b","tier_3":"c","tier_4":"d","tier_5":"e","tier_6":"f"}',
            [],
        ),
        (
            '{"tier_1":"1.2345, 6.7890","tier_2":"b","tier_3":"c","tier_4":"d","tier_5":"e","tier_6":"f"}',
            ["coordinate_literal"],
        ),
    ],
)
def test_stdin_mode(payload: str, expect_codes: list[str]) -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--stdin"],
        cwd=str(REPO_ROOT),
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    if expect_codes:
        assert r.returncode == 1
        for c in expect_codes:
            assert c in r.stderr
    else:
        assert r.returncode == 0


def test_json_out_writes_array(tmp_path: Path) -> None:
    out = tmp_path / "violations.json"
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(FIXTURES / "hints_bad_coords.json"),
            "--json-out",
            str(out),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data and data[0]["code"] == "coordinate_literal"


def test_violation_format_line() -> None:
    v = Violation("x", "msg", path="tier_1")
    assert "tier_1" in v.format_line() and "[x]" in v.format_line()
