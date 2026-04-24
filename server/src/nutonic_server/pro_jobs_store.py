from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, create_engine, delete, event, insert, select, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool

ProJobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
TerminalProJobStatus = Literal["completed", "failed", "cancelled"]

metadata = MetaData()

pro_jobs = Table(
    "pro_jobs",
    metadata,
    Column("job_id", String(64), primary_key=True, nullable=False),
    Column("session_id", String(128), nullable=False, index=True),
    Column("status", String(32), nullable=False, index=True),
    Column("error_class", String(64), nullable=True),
    Column("error_detail", String(500), nullable=True),
    Column("analysis_profile", String(128), nullable=False),
    Column("request_params", String, nullable=True),
    Column("created_at", String(64), nullable=False, index=True),
    Column("started_at", String(64), nullable=True),
    Column("finished_at", String(64), nullable=True),
    Column("progress_pct", Integer, nullable=False, server_default="0"),
    Column("artifact_manifest", String, nullable=True),
    Column("scene_provenance", String, nullable=True),
    Column("materialization_summary", String, nullable=True),
    Column("materialization_id", String(128), nullable=True),
    Column("cache_key", String(256), nullable=True),
    Column("cancel_requested", Boolean, nullable=False, server_default="0"),
)


@dataclass(frozen=True)
class ProJobRecord:
    job_id: str
    session_id: str
    status: ProJobStatus
    analysis_profile: str
    request_params: dict[str, Any]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    progress_pct: int = 0
    error_class: str | None = None
    error_detail: str | None = None
    artifact_manifest: list[dict[str, Any]] | None = None
    scene_provenance: dict[str, Any] | None = None
    materialization_summary: dict[str, Any] | None = None
    materialization_id: str | None = None
    cache_key: str | None = None
    cancel_requested: bool = False


class ProJobStore(Protocol):
    def create_job(self, *, session_id: str, analysis_profile: str, request_params: dict[str, Any]) -> ProJobRecord: ...

    def get_job(self, job_id: str, *, session_id: str | None = None) -> ProJobRecord | None: ...

    def list_jobs(
        self,
        *,
        session_id: str,
        limit: int = 20,
        statuses: set[str] | None = None,
    ) -> list[ProJobRecord]: ...

    def list_queued_jobs(self, *, limit: int = 100) -> list[ProJobRecord]: ...

    def transition(
        self,
        job_id: str,
        *,
        expected: set[str],
        status: ProJobStatus,
        progress_pct: int | None = None,
    ) -> ProJobRecord | None: ...

    def update_progress(self, job_id: str, *, progress_pct: int) -> None: ...

    def complete(
        self,
        job_id: str,
        *,
        artifacts: list[dict[str, Any]] | None = None,
        materialization_summary: dict[str, Any] | None = None,
        materialization_id: str | None = None,
        cache_key: str | None = None,
        scene_provenance: dict[str, Any] | None = None,
    ) -> ProJobRecord | None: ...

    def fail(self, job_id: str, *, error_class: str, error_detail: str | None = None) -> ProJobRecord | None: ...

    def request_cancel(self, job_id: str, *, session_id: str) -> str:
        ...

    def cleanup_finished(self, *, ttl_seconds: int, artifact_root: str | None = None) -> int: ...


class SqliteProJobStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = Lock()

    def initialize_schema(self) -> None:
        metadata.create_all(self._engine)
        self._ensure_columns()

    def _ensure_columns(self) -> None:
        required_columns = {
            "error_class": "TEXT",
            "error_detail": "TEXT",
            "analysis_profile": "TEXT NOT NULL DEFAULT 'brief_only'",
            "request_params": "TEXT",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "started_at": "TEXT",
            "finished_at": "TEXT",
            "progress_pct": "INTEGER NOT NULL DEFAULT 0",
            "artifact_manifest": "TEXT",
            "scene_provenance": "TEXT",
            "materialization_summary": "TEXT",
            "materialization_id": "TEXT",
            "cache_key": "TEXT",
            "cancel_requested": "BOOLEAN NOT NULL DEFAULT 0",
        }
        with self._lock:
            with self._engine.begin() as conn:
                rows = conn.execute(text("PRAGMA table_info(pro_jobs)")).fetchall()
                existing = {str(r[1]) for r in rows}
                for name, ddl in required_columns.items():
                    if name not in existing:
                        conn.execute(text(f"ALTER TABLE pro_jobs ADD COLUMN {name} {ddl}"))

    def create_job(self, *, session_id: str, analysis_profile: str, request_params: dict[str, Any]) -> ProJobRecord:
        now = _utc_now()
        record = ProJobRecord(
            job_id=uuid.uuid4().hex,
            session_id=session_id,
            status="queued",
            analysis_profile=analysis_profile,
            request_params=dict(request_params),
            created_at=now,
        )
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(pro_jobs).values(
                        job_id=record.job_id,
                        session_id=record.session_id,
                        status=record.status,
                        analysis_profile=record.analysis_profile,
                        request_params=_dump_json(record.request_params),
                        created_at=record.created_at,
                        progress_pct=record.progress_pct,
                    )
                )
        return record

    def get_job(self, job_id: str, *, session_id: str | None = None) -> ProJobRecord | None:
        stmt = select(pro_jobs).where(pro_jobs.c.job_id == job_id)
        if session_id is not None:
            stmt = stmt.where(pro_jobs.c.session_id == session_id)
        with self._lock:
            with self._engine.connect() as conn:
                row = conn.execute(stmt).mappings().first()
        return _record_from_row(row) if row is not None else None

    def list_jobs(
        self,
        *,
        session_id: str,
        limit: int = 20,
        statuses: set[str] | None = None,
    ) -> list[ProJobRecord]:
        stmt = select(pro_jobs).where(pro_jobs.c.session_id == session_id)
        if statuses:
            stmt = stmt.where(pro_jobs.c.status.in_(sorted(statuses)))
        stmt = stmt.order_by(pro_jobs.c.created_at.desc()).limit(max(1, min(int(limit), 100)))
        with self._lock:
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).mappings().all()
        return [_record_from_row(row) for row in rows]

    def list_queued_jobs(self, *, limit: int = 100) -> list[ProJobRecord]:
        stmt = (
            select(pro_jobs)
            .where(pro_jobs.c.status == "queued")
            .order_by(pro_jobs.c.created_at.asc())
            .limit(max(1, min(int(limit), 500)))
        )
        with self._lock:
            with self._engine.connect() as conn:
                rows = conn.execute(stmt).mappings().all()
        return [_record_from_row(row) for row in rows]

    def transition(
        self,
        job_id: str,
        *,
        expected: set[str],
        status: ProJobStatus,
        progress_pct: int | None = None,
    ) -> ProJobRecord | None:
        now = _utc_now()
        values: dict[str, Any] = {"status": status}
        if status == "running":
            values["started_at"] = now
        if status in {"completed", "failed", "cancelled"}:
            values["finished_at"] = now
        if progress_pct is not None:
            values["progress_pct"] = int(progress_pct)
        with self._lock:
            with self._engine.begin() as conn:
                res = conn.execute(
                    update(pro_jobs)
                    .where(pro_jobs.c.job_id == job_id, pro_jobs.c.status.in_(sorted(expected)))
                    .values(**values)
                )
                if not res.rowcount:
                    return None
        return self.get_job(job_id)

    def update_progress(self, job_id: str, *, progress_pct: int) -> None:
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    update(pro_jobs)
                    .where(pro_jobs.c.job_id == job_id)
                    .values(progress_pct=max(0, min(int(progress_pct), 100)))
                )

    def complete(
        self,
        job_id: str,
        *,
        artifacts: list[dict[str, Any]] | None = None,
        materialization_summary: dict[str, Any] | None = None,
        materialization_id: str | None = None,
        cache_key: str | None = None,
        scene_provenance: dict[str, Any] | None = None,
    ) -> ProJobRecord | None:
        with self._lock:
            with self._engine.begin() as conn:
                res = conn.execute(
                    update(pro_jobs)
                    .where(pro_jobs.c.job_id == job_id, pro_jobs.c.status == "running")
                    .values(
                        status="completed",
                        finished_at=_utc_now(),
                        progress_pct=100,
                        artifact_manifest=_dump_json(artifacts or []),
                        materialization_summary=_dump_json(materialization_summary),
                        materialization_id=materialization_id,
                        cache_key=cache_key,
                        scene_provenance=_dump_json(scene_provenance),
                    )
                )
                if not res.rowcount:
                    return None
        return self.get_job(job_id)

    def fail(self, job_id: str, *, error_class: str, error_detail: str | None = None) -> ProJobRecord | None:
        with self._lock:
            with self._engine.begin() as conn:
                res = conn.execute(
                    update(pro_jobs)
                    .where(pro_jobs.c.job_id == job_id, pro_jobs.c.status.in_(["queued", "running"]))
                    .values(
                        status="failed",
                        finished_at=_utc_now(),
                        error_class=error_class,
                        error_detail=(error_detail or "")[:500] or None,
                    )
                )
                if not res.rowcount:
                    return None
        return self.get_job(job_id)

    def request_cancel(self, job_id: str, *, session_id: str) -> str:
        with self._lock:
            with self._engine.begin() as conn:
                row = conn.execute(
                    select(pro_jobs.c.status).where(
                        pro_jobs.c.job_id == job_id,
                        pro_jobs.c.session_id == session_id,
                    )
                ).first()
                if row is None:
                    return "not_found"
                current = str(row[0])
                if current == "queued":
                    conn.execute(
                        update(pro_jobs)
                        .where(pro_jobs.c.job_id == job_id)
                        .values(status="cancelled", finished_at=_utc_now(), progress_pct=0, error_class="cancelled")
                    )
                    return "cancelled"
                if current == "running":
                    conn.execute(
                        update(pro_jobs)
                        .where(pro_jobs.c.job_id == job_id)
                        .values(cancel_requested=True)
                    )
                    return "cancelling"
                return current

    def cleanup_finished(self, *, ttl_seconds: int, artifact_root: str | None = None) -> int:
        cutoff = datetime.now(tz=UTC) - timedelta(seconds=max(1, int(ttl_seconds)))
        cutoff_s = cutoff.isoformat()
        with self._lock:
            with self._engine.begin() as conn:
                rows = conn.execute(
                    select(pro_jobs.c.job_id).where(
                        pro_jobs.c.finished_at.is_not(None),
                        pro_jobs.c.finished_at < cutoff_s,
                    )
                ).all()
                conn.execute(
                    delete(pro_jobs).where(
                        pro_jobs.c.finished_at.is_not(None),
                        pro_jobs.c.finished_at < cutoff_s,
                    )
                )
        if artifact_root:
            root = Path(artifact_root)
            for (job_id,) in rows:
                _delete_job_artifacts(root / str(job_id))
        return len(rows)


def create_pro_job_engine(url: str) -> Engine:
    u = make_url(url)
    engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
    connect_args: dict[str, Any] = {}
    if u.drivername in ("sqlite", "sqlite+pysqlite"):
        connect_args["check_same_thread"] = False
        if u.database == ":memory:" or ":memory:" in url:
            engine_kwargs["poolclass"] = StaticPool
        else:
            connect_args["timeout"] = 15.0
    engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragma(dbapi_conn, _connection_record) -> None:  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def create_pro_job_store(url: str) -> SqliteProJobStore:
    _ensure_parent_dir_for_sqlite_file(url)
    store = SqliteProJobStore(create_pro_job_engine(url))
    store.initialize_schema()
    return store


def _ensure_parent_dir_for_sqlite_file(url: str) -> None:
    u = make_url(url)
    if u.drivername not in ("sqlite", "sqlite+pysqlite"):
        return
    db = u.database
    if not db or db == ":memory:":
        return
    path = Path(db)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)


def _record_from_row(row: Any) -> ProJobRecord:
    return ProJobRecord(
        job_id=str(row["job_id"]),
        session_id=str(row["session_id"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        analysis_profile=str(row["analysis_profile"] or "brief_only"),
        request_params=_load_json_object(row["request_params"]),
        created_at=str(row["created_at"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        progress_pct=int(row["progress_pct"] or 0),
        error_class=row["error_class"],
        error_detail=row["error_detail"],
        artifact_manifest=_load_json_list(row["artifact_manifest"]),
        scene_provenance=_load_json_object(row["scene_provenance"]),
        materialization_summary=_load_json_object(row["materialization_summary"]),
        materialization_id=row["materialization_id"],
        cache_key=row["cache_key"],
        cancel_requested=bool(row["cancel_requested"]),
    )


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load_json_object(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(str(raw))
    return value if isinstance(value, dict) else {}


def _load_json_list(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    value = json.loads(str(raw))
    return value if isinstance(value, list) else []


def _delete_job_artifacts(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_dir():
            _delete_job_artifacts(child)
        else:
            child.unlink(missing_ok=True)
    path.rmdir()
