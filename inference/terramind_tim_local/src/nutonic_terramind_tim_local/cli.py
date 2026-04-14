"""CLI: ``nutonic-tim-local``."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _repo_root_from_here() -> Path:
    return Path(__file__).resolve().parents[4]


def cmd_run(ns: argparse.Namespace) -> int:
    from nutonic_terramind_tim_local.run import (
        append_jsonl,
        load_run_config,
        run_tim_batch_export,
        run_tim_forward_export,
        write_json,
    )

    cfg_path = Path(ns.config).resolve()
    cfg = load_run_config(cfg_path)
    if ns.device:
        cfg["device"] = ns.device
    out_dir = Path(ns.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if isinstance(cfg.get("batch"), list) and cfg["batch"]:
        rows = run_tim_batch_export(cfg)
        write_json(out_dir / "tim_run.json", {"runs": rows})
        jsonl_path = out_dir / Path(ns.jsonl_name)
        if jsonl_path.exists():
            jsonl_path.unlink()
        for row in rows:
            append_jsonl(jsonl_path, row)
    else:
        payload = run_tim_forward_export(cfg)
        write_json(out_dir / "tim_run.json", payload)
        jsonl_path = out_dir / Path(ns.jsonl_name)
        if jsonl_path.exists():
            jsonl_path.unlink()
        append_jsonl(jsonl_path, payload)
    print((out_dir / ns.jsonl_name).as_posix())
    print((out_dir / "tim_run.json").as_posix())
    return 0


def cmd_ingest(ns: argparse.Namespace) -> int:
    repo = _repo_root_from_here()
    script = repo / "data" / "scripts" / "generate_ai_guess_fixture.py"
    if not script.is_file():
        print(f"Missing {script}", file=sys.stderr)
        return 2
    out = Path(ns.output).resolve() if ns.output else repo / "data" / "cache" / str(ns.content_version) / "ai_guesses.json"
    cmd = [
        sys.executable,
        str(script),
        "--catalog-root",
        str(Path(ns.catalog_root).resolve()),
        "--mode",
        "terramind_tim_jsonl",
        "--tim-export",
        str(Path(ns.tim_jsonl).resolve()),
        "--output",
        str(out),
        "--content-version",
        str(ns.content_version),
    ]
    print(" ".join(cmd))
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nutonic-tim-local")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run TiM forward and write JSON + JSONL export")
    r.add_argument("--config", type=Path, required=True)
    r.add_argument("--output-dir", type=Path, required=True)
    r.add_argument("--jsonl-name", default="tim_export.jsonl")
    r.add_argument("--device", default=None, help="Override YAML device (cpu|cuda)")
    r.set_defaults(func=cmd_run)

    i = sub.add_parser("ingest", help="Call generate_ai_guess_fixture.py on a tim_export.jsonl")
    i.add_argument("--tim-jsonl", type=Path, required=True)
    i.add_argument("--catalog-root", type=Path, required=True)
    i.add_argument("--content-version", default="dev")
    i.add_argument("--output", type=Path, default=None)
    i.set_defaults(func=cmd_ingest)

    ns = p.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
