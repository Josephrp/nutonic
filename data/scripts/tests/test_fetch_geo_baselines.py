"""Offline tests for fetch_geo_baselines.py (mocked downloads)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from fetch_geo_baselines import (
    GEONAMES_COUNTRY_INFO_URL,
    fetch_geonames_country_info,
    fetch_natural_earth,
    main,
    merge_manifest_geonames,
    ne_50m_artifacts,
    sha256_file,
)


def _tiny_zip(filename: str = "stub.txt", body: bytes = b"nutonic-test") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, body)
    return buf.getvalue()


def test_sha256_file_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    p.write_bytes(b"abc")
    assert len(sha256_file(p)) == 64


def test_ne_fetch_mocked_writes_manifest_and_zips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    z = _tiny_zip()

    def fake_download(url: str, timeout_sec: int) -> bytes:
        assert timeout_sec > 0
        if "geonames" in url:
            return b"ISO\tISO3\tISO-Numeric\tfips\tCountry\tCapital\tArea\tPopulation\n"
        return z

    monkeypatch.setattr("fetch_geo_baselines._download_bytes", fake_download)

    rows = fetch_natural_earth(
        tmp_path,
        "5.1.2",
        timeout_sec=30,
        dry_run=False,
        force=False,
        download=fake_download,
    )
    assert len(rows) == len(ne_50m_artifacts())
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest.get("schema") == "nutonic.geo_baselines_manifest.v1"
    assert len(manifest["artifacts"]) == len(ne_50m_artifacts())
    for art in ne_50m_artifacts():
        assert (tmp_path / "zips" / f"{art.id}.zip").is_file()
        ex = tmp_path / "natural_earth" / "50m" / art.extract_name
        assert ex.is_dir() and any(ex.iterdir())


def test_ne_fetch_skips_download_when_sha_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    z = _tiny_zip()
    calls: list[str] = []

    def counting_download(url: str, timeout_sec: int) -> bytes:
        calls.append(url)
        return z

    monkeypatch.setattr("fetch_geo_baselines._download_bytes", counting_download)

    fetch_natural_earth(
        tmp_path, "5.1.2", timeout_sec=30, dry_run=False, force=False, download=counting_download
    )
    assert len(calls) == len(ne_50m_artifacts())
    calls.clear()
    fetch_natural_earth(
        tmp_path, "5.1.2", timeout_sec=30, dry_run=False, force=False, download=counting_download
    )
    assert calls == []


def test_fetch_geonames_merges_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    z = _tiny_zip()

    def fake_download(url: str, timeout_sec: int) -> bytes:
        if url == GEONAMES_COUNTRY_INFO_URL:
            return b"ISO\tISO3\tCountry\nXX\tXXX\tTestland\n"
        return z

    monkeypatch.setattr("fetch_geo_baselines._download_bytes", fake_download)

    rows = fetch_natural_earth(
        tmp_path, "5.1.2", timeout_sec=30, dry_run=False, force=False, download=fake_download
    )
    gn = fetch_geonames_country_info(
        tmp_path, timeout_sec=30, dry_run=False, force=False, download=fake_download
    )
    assert gn is not None
    merge_manifest_geonames(tmp_path, "5.1.2", rows, gn)
    m = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m.get("geonames", {}).get("countryInfo_relative") == "geonames/countryInfo.txt"
    assert (tmp_path / "geonames" / "NOTICE.txt").is_file()


def test_main_dry_run_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "fetch_geo_baselines._download_bytes",
        lambda url, t: (_ for _ in ()).throw(AssertionError("no network in dry-run")),
    )
    code = main(["--dry-run", "--output-dir", str(tmp_path)])
    assert code == 0


def test_main_smoke_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    z = _tiny_zip()

    def fake_download(url: str, timeout_sec: int) -> bytes:
        return z

    monkeypatch.setattr("fetch_geo_baselines._download_bytes", fake_download)
    code = main(["--output-dir", str(tmp_path), "--ne-version", "5.1.2"])
    assert code == 0
    assert (tmp_path / "MANIFEST.json").is_file()
