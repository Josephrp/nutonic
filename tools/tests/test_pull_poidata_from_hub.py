"""Tests for tools/pull_poidata_from_hub.py and tools/submit_nutonic_hydration_job.py."""

from __future__ import annotations

from pathlib import Path

import huggingface_hub
import pytest


def test_pull_poidata_calls_snapshot_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    called: list[dict] = []

    def fake_snapshot_download(**kwargs):
        called.append(kwargs)
        return str(tmp_path)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)

    import pull_poidata_from_hub as mod

    out = tmp_path / "downloads"
    rc = mod.main(["--local-dir", str(out), "--repo-id", "NuTonic/poidata"])
    assert rc == 0
    assert called[0]["repo_id"] == "NuTonic/poidata"
    assert called[0]["repo_type"] == "dataset"
    assert called[0]["allow_patterns"] == ["geoguessr_poi_12/**", "geoguessr_poi_120/**"]


def test_submit_hydration_dry_run_json(capsys: pytest.CaptureFixture[str]) -> None:
    from submit_nutonic_hydration_job import main

    rc = main(
        [
            "streetview-lfm",
            "--docker-image",
            "example/nutonic:1",
            "--flavor",
            "cpu-basic",
            "--no-dataset-volume",
            "--dry-run",
            "--",
            "/bin/echo",
            "ok",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "example/nutonic:1" in out
    assert "/bin/echo" in out
