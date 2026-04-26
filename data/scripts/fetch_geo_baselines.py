#!/usr/bin/env python3
"""
Download Natural Earth 1:50m vector baselines (and optionally GeoNames countryInfo)
into data/geo/ for offline use by build_poi_geo_context and related scripts.

Normative: docs/scripts/SPEC-fetch-geo-baselines.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "geo"
MANIFEST_NAME = "MANIFEST.json"
USER_AGENT = "nutonic-fetch-geo-baselines/1.0 (+https://github.com/)"

# naciscdn.org mirrors Natural Earth; paths are stable for 50m scale.
NE50M_BASE = "https://naciscdn.org/naturalearth/50m"
GEONAMES_COUNTRY_INFO_URL = "https://download.geonames.org/export/dump/countryInfo.txt"

DownloadFn = Callable[[str, int], bytes]


@dataclass(frozen=True)
class NeArtifact:
    """One Natural Earth zip + extraction folder name."""

    id: str
    url: str
    """Relative to output_dir / natural_earth / 50m /"""

    extract_name: str


def ne_50m_artifacts() -> list[NeArtifact]:
    return [
        NeArtifact(
            id="ne_50m_admin_0_countries",
            url=f"{NE50M_BASE}/cultural/ne_50m_admin_0_countries.zip",
            extract_name="ne_50m_admin_0_countries",
        ),
        NeArtifact(
            id="ne_50m_admin_1_states_provinces",
            url=f"{NE50M_BASE}/cultural/ne_50m_admin_1_states_provinces.zip",
            extract_name="ne_50m_admin_1_states_provinces",
        ),
        NeArtifact(
            id="ne_50m_rivers_lake_centerlines",
            url=f"{NE50M_BASE}/physical/ne_50m_rivers_lake_centerlines.zip",
            extract_name="ne_50m_rivers_lake_centerlines",
        ),
        NeArtifact(
            id="ne_50m_lakes",
            url=f"{NE50M_BASE}/physical/ne_50m_lakes.zip",
            extract_name="ne_50m_lakes",
        ),
        NeArtifact(
            id="ne_50m_coastline",
            url=f"{NE50M_BASE}/physical/ne_50m_coastline.zip",
            extract_name="ne_50m_coastline",
        ),
    ]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_bytes(url: str, timeout_sec: int) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout_sec) as resp:
        return resp.read()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _artifact_sha_from_manifest(manifest: dict[str, Any], artifact_id: str) -> str | None:
    arts = manifest.get("artifacts")
    if not isinstance(arts, list):
        return None
    for row in arts:
        if isinstance(row, dict) and row.get("id") == artifact_id:
            sha = row.get("sha256")
            return str(sha) if sha else None
    return None


def _build_manifest(
    ne_version: str,
    artifact_rows: list[dict[str, Any]],
    geonames: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": "nutonic.geo_baselines_manifest.v1",
        "natural_earth_version": ne_version,
        "artifacts": artifact_rows,
        "geonames": geonames,
    }


def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def _write_geonames_notice(geonames_dir: Path) -> None:
    notice = geonames_dir / "NOTICE.txt"
    text = (
        "GeoNames — countryInfo.txt\n"
        "----------------------------\n"
        "Source: https://www.geonames.org/export/\n"
        "License: Creative Commons Attribution 4.0 International (CC BY 4.0)\n"
        "https://creativecommons.org/licenses/by/4.0/\n\n"
        "This directory may contain a downloaded `countryInfo.txt` produced by\n"
        "`data/scripts/fetch_geo_baselines.py --fetch-geonames`.\n"
        "Retain this notice alongside any redistributed GeoNames extract.\n"
    )
    _atomic_write_text(notice, text)


def fetch_natural_earth(
    output_dir: Path,
    ne_version: str,
    *,
    timeout_sec: int,
    dry_run: bool,
    force: bool,
    download: DownloadFn,
) -> list[dict[str, Any]]:
    zips_dir = output_dir / "zips"
    ne_root = output_dir / "natural_earth" / "50m"
    manifest_path = output_dir / MANIFEST_NAME
    manifest = _load_manifest(manifest_path)
    geo_meta = manifest.get("geonames")
    if not isinstance(geo_meta, dict):
        geo_meta = None
    rows_out: list[dict[str, Any]] = []

    for art in ne_50m_artifacts():
        zip_rel = Path("zips") / f"{art.id}.zip"
        zip_path = output_dir / zip_rel
        extract_rel = Path("natural_earth") / "50m" / art.extract_name
        extract_dir = output_dir / extract_rel
        expected_sha = _artifact_sha_from_manifest(manifest, art.id)

        need_download = force or not zip_path.is_file()
        if not need_download and expected_sha and sha256_file(zip_path) != expected_sha:
            need_download = True

        if dry_run:
            print(f"[dry-run] {art.id}: download={need_download} -> {zip_path}")
            if zip_path.is_file():
                sha = sha256_file(zip_path)
            else:
                sha = "<would compute after download>"
            rows_out.append(
                {
                    "id": art.id,
                    "url": art.url,
                    "zip_relative": zip_rel.as_posix(),
                    "sha256": sha if isinstance(sha, str) else str(sha),
                    "extract_relative": extract_rel.as_posix(),
                }
            )
            continue

        if need_download:
            print(f"Downloading {art.id} …", file=sys.stderr)
            try:
                data = download(art.url, timeout_sec)
            except URLError as e:
                print(f"Download failed for {art.url}: {e}", file=sys.stderr)
                raise SystemExit(3) from e
            zips_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(zip_path, data)

        sha = sha256_file(zip_path)
        if expected_sha and sha != expected_sha and not force:
            print(
                f"Warning: SHA256 for {art.id} changed since last manifest "
                f"(old {expected_sha[:12]}… vs new {sha[:12]}…). Updating manifest.",
                file=sys.stderr,
            )

        need_extract = (
            force
            or need_download
            or not extract_dir.is_dir()
            or not any(extract_dir.iterdir())
        )
        if need_extract:
            print(f"Extracting {art.id} …", file=sys.stderr)
            if not zip_path.is_file():
                print(f"Missing zip after download: {zip_path}", file=sys.stderr)
                raise SystemExit(4)
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True, exist_ok=True)
            _extract_zip(zip_path, extract_dir)

        rows_out.append(
            {
                "id": art.id,
                "url": art.url,
                "zip_relative": zip_rel.as_posix(),
                "sha256": sha,
                "extract_relative": extract_rel.as_posix(),
            }
        )

    if not dry_run:
        new_manifest = _build_manifest(ne_version, rows_out, geo_meta)
        _atomic_write_text(manifest_path, json.dumps(new_manifest, indent=2) + "\n")

    return rows_out


def fetch_geonames_country_info(
    output_dir: Path,
    *,
    timeout_sec: int,
    dry_run: bool,
    force: bool,
    download: DownloadFn,
) -> dict[str, Any] | None:
    gdir = output_dir / "geonames"
    out_path = gdir / "countryInfo.txt"
    if dry_run:
        print(f"[dry-run] geonames: would fetch -> {out_path}", file=sys.stderr)
        return {"countryInfo_relative": "geonames/countryInfo.txt", "sha256": "<dry-run>"}

    _write_geonames_notice(gdir)

    if out_path.is_file() and not force:
        sha = sha256_file(out_path)
        return {"countryInfo_relative": "geonames/countryInfo.txt", "sha256": sha}

    print("Downloading GeoNames countryInfo.txt …", file=sys.stderr)
    try:
        data = download(GEONAMES_COUNTRY_INFO_URL, timeout_sec)
    except URLError as e:
        print(f"GeoNames download failed: {e}", file=sys.stderr)
        raise SystemExit(3) from e
    gdir.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(out_path, data)
    sha = sha256_file(out_path)
    return {"countryInfo_relative": "geonames/countryInfo.txt", "sha256": sha}


def merge_manifest_geonames(
    output_dir: Path,
    ne_version: str,
    artifact_rows: list[dict[str, Any]],
    geonames_meta: dict[str, Any] | None,
) -> None:
    manifest_path = output_dir / MANIFEST_NAME
    m = _load_manifest(manifest_path)
    geo = geonames_meta if geonames_meta is not None else m.get("geonames")
    merged = _build_manifest(ne_version, artifact_rows, geo if isinstance(geo, dict) else None)
    _atomic_write_text(manifest_path, json.dumps(merged, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Natural Earth 50m baselines into data/geo/ (see data/geo/README.md).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Root directory for zips, extracts, and MANIFEST.json.",
    )
    parser.add_argument(
        "--ne-version",
        default="5.1.2",
        help="Recorded in MANIFEST.json (dataset release pin; CDN zips follow Natural Earth packaging).",
    )
    parser.add_argument(
        "--fetch-geonames",
        action="store_true",
        help="Also download GeoNames countryInfo.txt (CC BY); default is Natural Earth only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned work without downloading or writing files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download / re-extract even when on-disk SHA256 matches the last manifest.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout seconds per request.",
    )
    args = parser.parse_args(argv)

    output_dir = args.output_dir.resolve()
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    download: DownloadFn = _download_bytes

    rows = fetch_natural_earth(
        output_dir,
        args.ne_version,
        timeout_sec=args.timeout,
        dry_run=args.dry_run,
        force=args.force,
        download=download,
    )

    geonames_meta: dict[str, Any] | None = None
    if args.fetch_geonames:
        geonames_meta = fetch_geonames_country_info(
            output_dir,
            timeout_sec=args.timeout,
            dry_run=args.dry_run,
            force=args.force,
            download=download,
        )

    if not args.dry_run and args.fetch_geonames and geonames_meta is not None:
        merge_manifest_geonames(output_dir, args.ne_version, rows, geonames_meta)

    if args.dry_run:
        print(f"OK (dry-run) — output would be under {output_dir}")
        return 0

    print(f"OK — baselines under {output_dir}; manifest {output_dir / MANIFEST_NAME}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
