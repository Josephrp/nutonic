from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock


@dataclass(frozen=True)
class HfSqliteSyncConfig:
    enabled: bool
    repo_id: str
    dataset_subdir: str
    startup_pull_mode: str = "if_missing"
    required: bool = False
    token: str | None = None


class HfSqliteSync:
    """Sync local SQLite files to a Hugging Face Dataset repo."""

    def __init__(self, config: HfSqliteSyncConfig) -> None:
        self._config = config
        self._lock = Lock()
        self._api = None

    @classmethod
    def from_settings(cls, settings) -> HfSqliteSync | None:
        enabled = bool(getattr(settings, "hf_persistence_enabled", False))
        required = bool(getattr(settings, "hf_persistence_required", False))
        # Lazy-check optional dependency and env wiring only when explicitly enabled.
        if not enabled:
            return None
        repo_id = str(getattr(settings, "hf_persistence_repo_id", "") or "").strip()
        if not repo_id:
            if required:
                raise RuntimeError(
                    "HF persistence is required but NUTONIC_HF_PERSISTENCE_REPO_ID/HF_PERSISTENCE_REPO_ID is missing."
                )
            return None
        token = (
            os.environ.get("NUTONIC_HF_PERSISTENCE_TOKEN")
            or os.environ.get("HF_API_WRITE")
            or os.environ.get("HF_TOKEN")
            or os.environ.get("HUGGING_FACE_HUB_TOKEN")
            or None
        )
        if required and not token:
            raise RuntimeError(
                "HF persistence is required but no HF write token is set "
                "(NUTONIC_HF_PERSISTENCE_TOKEN/HF_API_WRITE/HF_TOKEN/HUGGING_FACE_HUB_TOKEN)."
            )
        subdir = str(getattr(settings, "hf_persistence_dataset_subdir", "server-persistence") or "server-persistence").strip(
            "/"
        )
        startup_pull_mode = str(getattr(settings, "hf_persistence_startup_pull_mode", "if_missing") or "if_missing").strip().lower()
        if startup_pull_mode not in ("if_missing", "always"):
            raise RuntimeError(
                "Invalid HF persistence startup pull mode. "
                "Use NUTONIC_HF_PERSISTENCE_STARTUP_PULL_MODE=if_missing|always."
            )
        return cls(
            HfSqliteSyncConfig(
                enabled=True,
                repo_id=repo_id,
                dataset_subdir=subdir,
                startup_pull_mode=startup_pull_mode,
                required=required,
                token=token,
            )
        )

    def bootstrap_sqlite_file(self, *, local_path: Path, logical_name: str) -> None:
        """Pull remote DB file at startup based on configured pull mode."""
        if self._config.startup_pull_mode == "if_missing" and local_path.exists():
            return
        try:
            from huggingface_hub import hf_hub_download
        except Exception:
            if self._config.required:
                raise RuntimeError("HF persistence required but huggingface_hub is unavailable.")
            return
        local_path.parent.mkdir(parents=True, exist_ok=True)
        remote_path = self._remote_path(logical_name)
        try:
            hf_hub_download(
                repo_id=self._config.repo_id,
                repo_type="dataset",
                filename=remote_path,
                local_dir=str(local_path.parent),
                local_dir_use_symlinks=False,
                token=self._config.token,
            )
            downloaded = local_path.parent / remote_path
            if downloaded.exists() and downloaded != local_path:
                downloaded.replace(local_path)
        except Exception:
            if self._config.required:
                raise
            return

    def make_write_sync_hook(self, *, local_path: Path, logical_name: str):
        def _sync() -> None:
            if not local_path.exists():
                return
            try:
                self._upload_file(local_path=local_path, logical_name=logical_name)
            except Exception:
                if self._config.required:
                    raise
                return

        return _sync

    def _upload_file(self, *, local_path: Path, logical_name: str) -> None:
        with self._lock:
            api = self._get_api()
            api.create_repo(
                repo_id=self._config.repo_id,
                repo_type="dataset",
                private=True,
                exist_ok=True,
            )
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=self._remote_path(logical_name),
                repo_id=self._config.repo_id,
                repo_type="dataset",
            )

    def _remote_path(self, logical_name: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in logical_name).strip("._")
        safe = safe or "database"
        return f"{self._config.dataset_subdir}/{safe}.sqlite3"

    def _get_api(self):
        if self._api is not None:
            return self._api
        from huggingface_hub import HfApi

        self._api = HfApi(token=self._config.token)
        return self._api
