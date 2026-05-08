"""Optional non-ranked guess telemetry (`rules/05`, `docs/GAME-ENGINE.md` §12.3)."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Callable

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, insert, select, text

from nutonic_server.schemas import GuessRecordOut

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

metadata = MetaData()

guess_telemetry_rows = Table(
    "guess_telemetry_rows",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("map_id", String(256), nullable=False, index=True),
    Column("round_instance_id", String(512), nullable=False),
    Column("location_id", String(256), nullable=False),
    Column("guess_lat", Float, nullable=False),
    Column("guess_lon", Float, nullable=False),
    Column("client_distance_km", Float, nullable=True),
    Column("ruleset_version", String(128), nullable=True),
    Column("session_id", String(128), nullable=True),
    Column("display_handle", String(64), nullable=True),
    Column("score_points", Integer, nullable=True),
    Column("player_role", String(32), nullable=True),
)

guess_idempotency = Table(
    "guess_telemetry_idempotency",
    metadata,
    Column("map_id", String(256), primary_key=True, nullable=False),
    Column("idempotency_key", String(256), primary_key=True, nullable=False),
    Column("row_id", Integer, nullable=False),
)


@dataclass
class GuessTelemetryIn:
    map_id: str
    round_instance_id: str
    location_id: str
    guess_lat: float
    guess_lon: float
    client_distance_km: float | None = None
    ruleset_version: str | None = None
    session_id: str | None = None
    display_handle: str | None = None
    score_points: int | None = None
    player_role: str | None = None


class GuessTelemetryStore:
    def __init__(self, engine: Engine, *, on_write: Callable[[], None] | None = None) -> None:
        self._engine = engine
        self._lock = Lock()
        self._on_write = on_write

    def initialize_schema(self) -> None:
        metadata.create_all(self._engine)
        self._migrate_legacy_sqlite()

    def _migrate_legacy_sqlite(self) -> None:
        stmts = [
            "ALTER TABLE guess_telemetry_rows ADD COLUMN display_handle VARCHAR(64)",
            "ALTER TABLE guess_telemetry_rows ADD COLUMN score_points INTEGER",
            "ALTER TABLE guess_telemetry_rows ADD COLUMN player_role VARCHAR(32)",
        ]
        try:
            with self._engine.begin() as conn:
                for stmt in stmts:
                    try:
                        conn.execute(text(stmt))
                    except Exception:
                        pass
        except Exception:
            pass

    def _row_ack(self, conn: Connection, row_id: int) -> GuessRecordOut:
        row = conn.execute(
            select(
                guess_telemetry_rows.c.id,
                guess_telemetry_rows.c.client_distance_km,
                guess_telemetry_rows.c.score_points,
                guess_telemetry_rows.c.display_handle,
            ).where(guess_telemetry_rows.c.id == row_id),
        ).mappings().one()
        return GuessRecordOut(
            id=int(row["id"]),
            recorded=True,
            distance_km=row["client_distance_km"],
            score_points=row["score_points"],
            display_handle=row["display_handle"],
        )

    def record(
        self,
        row: GuessTelemetryIn,
        *,
        idempotency_key: str | None,
    ) -> GuessRecordOut:
        """Insert telemetry row; idempotent repeat returns the same acknowledgement payload."""
        key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
        with self._lock:
            with self._engine.begin() as conn:
                if key:
                    hit = conn.execute(
                        select(guess_idempotency.c.row_id).where(
                            guess_idempotency.c.map_id == row.map_id,
                            guess_idempotency.c.idempotency_key == key,
                        ),
                    ).scalar_one_or_none()
                    if hit is not None:
                        return self._row_ack(conn, int(hit))

                rid = conn.execute(
                    insert(guess_telemetry_rows)
                    .values(
                        map_id=row.map_id,
                        round_instance_id=row.round_instance_id,
                        location_id=row.location_id,
                        guess_lat=row.guess_lat,
                        guess_lon=row.guess_lon,
                        client_distance_km=row.client_distance_km,
                        ruleset_version=row.ruleset_version,
                        session_id=row.session_id,
                        display_handle=row.display_handle,
                        score_points=row.score_points,
                        player_role=row.player_role,
                    )
                    .returning(guess_telemetry_rows.c.id),
                ).scalar_one()
                if key:
                    conn.execute(
                        insert(guess_idempotency).values(
                            map_id=row.map_id,
                            idempotency_key=key,
                            row_id=rid,
                        ),
                    )
                self._sync_after_write()
                return self._row_ack(conn, int(rid))

    def _sync_after_write(self) -> None:
        if self._on_write is None:
            return
        self._on_write()


def create_guess_telemetry_engine(url: str):
    from nutonic_server.leaderboard_store import create_leaderboard_engine

    return create_leaderboard_engine(url)


def create_guess_telemetry_store(url: str) -> GuessTelemetryStore | None:
    from nutonic_server.hf_persistence import HfSqliteSync
    from nutonic_server.leaderboard_store import _ensure_parent_dir_for_sqlite_file, sqlite_file_path_from_url
    from nutonic_server.settings import load_settings

    u = url.strip()
    if not u or u.lower() == "disabled":
        return None
    _ensure_parent_dir_for_sqlite_file(u)
    sync_hook = None
    db_path = sqlite_file_path_from_url(u)
    if db_path is not None:
        hf = HfSqliteSync.from_settings(load_settings())
        if hf is not None:
            hf.bootstrap_sqlite_file(local_path=db_path, logical_name="guess_telemetry")
            sync_hook = hf.make_write_sync_hook(local_path=db_path, logical_name="guess_telemetry")
    eng = create_guess_telemetry_engine(u)
    st = GuessTelemetryStore(eng, on_write=sync_hook)
    st.initialize_schema()
    return st
