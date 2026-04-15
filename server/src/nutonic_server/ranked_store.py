"""Ranked round secrets + submit idempotency (IMP-090)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, delete, desc, insert, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

RankedForfeitResult = Literal["ok", "not_found", "forbidden", "not_open"]

metadata = MetaData()

ranked_rounds = Table(
    "ranked_rounds",
    metadata,
    Column("round_id", String(64), primary_key=True, nullable=False),
    Column("map_id", String(256), nullable=False),
    Column("location_id", String(256), nullable=False),
    Column("truth_lat", Float, nullable=False),
    Column("truth_lon", Float, nullable=False),
    Column("session_id", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("opened_at_epoch", Integer, nullable=False, server_default="0"),
)

ranked_submit_idem = Table(
    "ranked_submit_idempotency",
    metadata,
    Column("round_id", String(64), primary_key=True, nullable=False),
    Column("idempotency_key", String(256), primary_key=True, nullable=False),
    Column("distance_km", Float, nullable=False),
    Column("score_points", Integer, nullable=False),
)

ranked_verified_lb = Table(
    "ranked_verified_leaderboard",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("map_id", String(256), nullable=False, index=True),
    Column("round_id", String(64), nullable=False, unique=True),
    Column("session_id", String(128), nullable=False),
    Column("score_points", Integer, nullable=False),
    Column("distance_km", Float, nullable=False),
)


@dataclass
class RankedRoundRow:
    round_id: str
    map_id: str
    location_id: str
    truth_lat: float
    truth_lon: float
    session_id: str
    status: str


@dataclass
class RankedVerifiedLbRow:
    """Maps to ``LeaderboardRowOut`` for ``GET .../leaderboard/ranked`` responses."""

    display_handle: str
    player_role: str
    score_points: int
    distance_km: float


class SqliteRankedStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = Lock()

    def initialize_schema(self) -> None:
        metadata.create_all(self._engine)
        self._ensure_opened_at_epoch_column()

    def _ensure_opened_at_epoch_column(self) -> None:
        """SQLite: add ``opened_at_epoch`` when upgrading an older ranked DB file."""
        with self._lock:
            with self._engine.begin() as conn:
                rows = conn.execute(text("PRAGMA table_info(ranked_rounds)")).fetchall()
                names = {str(r[1]) for r in rows}
                if "opened_at_epoch" not in names:
                    conn.execute(text("ALTER TABLE ranked_rounds ADD COLUMN opened_at_epoch INTEGER NOT NULL DEFAULT 0"))

    def prune_stale_open_rounds(self, *, now_epoch: int, max_age_seconds: int) -> int:
        """Delete ``open`` rounds whose ``opened_at_epoch`` is older than ``now_epoch - max_age_seconds``."""
        cutoff = int(now_epoch) - int(max_age_seconds)
        if cutoff <= 0:
            return 0
        with self._lock:
            with self._engine.begin() as conn:
                res = conn.execute(
                    delete(ranked_rounds).where(
                        ranked_rounds.c.status == "open",
                        ranked_rounds.c.opened_at_epoch < cutoff,
                    )
                )
                return int(res.rowcount or 0)

    def create_round(
        self,
        *,
        map_id: str,
        location_id: str,
        truth_lat: float,
        truth_lon: float,
        session_id: str,
    ) -> str:
        rid = uuid.uuid4().hex
        opened = int(datetime.now(tz=UTC).timestamp())
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    insert(ranked_rounds).values(
                        round_id=rid,
                        map_id=map_id,
                        location_id=location_id,
                        truth_lat=truth_lat,
                        truth_lon=truth_lon,
                        session_id=session_id,
                        status="open",
                        opened_at_epoch=opened,
                    )
                )
        return rid

    def get_round(self, round_id: str) -> RankedRoundRow | None:
        with self._lock:
            with self._engine.connect() as conn:
                hit = conn.execute(
                    select(
                        ranked_rounds.c.round_id,
                        ranked_rounds.c.map_id,
                        ranked_rounds.c.location_id,
                        ranked_rounds.c.truth_lat,
                        ranked_rounds.c.truth_lon,
                        ranked_rounds.c.session_id,
                        ranked_rounds.c.status,
                    ).where(ranked_rounds.c.round_id == round_id)
                ).first()
        if hit is None:
            return None
        r, m, loc, tlat, tlon, sid, st = hit
        return RankedRoundRow(r, m, loc, tlat, tlon, sid, st)

    def mark_submitted(self, round_id: str) -> None:
        with self._lock:
            with self._engine.begin() as conn:
                conn.execute(
                    update(ranked_rounds)
                    .where(ranked_rounds.c.round_id == round_id)
                    .values(status="submitted")
                )

    def forfeit_round(self, round_id: str, session_id: str) -> RankedForfeitResult:
        """Mark ``open`` round as ``forfeited`` when ``session_id`` matches (IMP-091)."""
        with self._lock:
            with self._engine.begin() as conn:
                row = conn.execute(
                    select(
                        ranked_rounds.c.session_id,
                        ranked_rounds.c.status,
                    ).where(ranked_rounds.c.round_id == round_id)
                ).first()
                if row is None:
                    return "not_found"
                sid, st = row
                if str(sid) != session_id:
                    return "forbidden"
                if st != "open":
                    return "not_open"
                conn.execute(
                    update(ranked_rounds)
                    .where(ranked_rounds.c.round_id == round_id)
                    .values(status="forfeited")
                )
        return "ok"

    def get_submit_if_exists(self, round_id: str, idempotency_key: str) -> tuple[float, int] | None:
        """Return prior (distance_km, score_points) for this idempotency key, if any."""
        with self._lock:
            with self._engine.connect() as conn:
                hit = conn.execute(
                    select(ranked_submit_idem.c.distance_km, ranked_submit_idem.c.score_points).where(
                        ranked_submit_idem.c.round_id == round_id,
                        ranked_submit_idem.c.idempotency_key == idempotency_key,
                    )
                ).first()
        if hit is None:
            return None
        return float(hit[0]), int(hit[1])

    def submit_idempotent_result(
        self,
        round_id: str,
        idempotency_key: str,
        distance_km: float,
        score_points: int,
    ) -> tuple[float, int, bool]:
        """Return (distance_km, score_points, inserted_new_row)."""
        with self._lock:
            with self._engine.begin() as conn:
                hit = conn.execute(
                    select(ranked_submit_idem.c.distance_km, ranked_submit_idem.c.score_points).where(
                        ranked_submit_idem.c.round_id == round_id,
                        ranked_submit_idem.c.idempotency_key == idempotency_key,
                    )
                ).first()
                if hit is not None:
                    return float(hit[0]), int(hit[1]), False
                conn.execute(
                    insert(ranked_submit_idem).values(
                        round_id=round_id,
                        idempotency_key=idempotency_key,
                        distance_km=distance_km,
                        score_points=score_points,
                    )
                )
                return distance_km, score_points, True

    def append_verified_leaderboard(
        self,
        *,
        map_id: str,
        round_id: str,
        session_id: str,
        score_points: int,
        distance_km: float,
    ) -> None:
        """Persist one server-verified ranked row per ``round_id`` (idempotent on replay)."""
        with self._lock:
            with self._engine.begin() as conn:
                stmt = sqlite_insert(ranked_verified_lb).values(
                    map_id=map_id,
                    round_id=round_id,
                    session_id=session_id,
                    score_points=score_points,
                    distance_km=distance_km,
                )
                conn.execute(stmt.on_conflict_do_nothing(index_elements=["round_id"]))

    def list_ranked_leaderboard(self, map_id: str) -> list[RankedVerifiedLbRow]:
        """Verified ranked rows for ``map_id``, highest score first."""
        with self._lock:
            with self._engine.connect() as conn:
                hits = conn.execute(
                    select(
                        ranked_verified_lb.c.session_id,
                        ranked_verified_lb.c.score_points,
                        ranked_verified_lb.c.distance_km,
                    )
                    .where(ranked_verified_lb.c.map_id == map_id)
                    .order_by(desc(ranked_verified_lb.c.score_points))
                ).all()
        out: list[RankedVerifiedLbRow] = []
        for sid, pts, dkm in hits:
            sid_s = str(sid)
            handle = f"RNK-{sid_s[:8].upper()}" if len(sid_s) >= 8 else f"RNK-{sid_s.upper()}"
            out.append(
                RankedVerifiedLbRow(
                    display_handle=handle,
                    player_role="RANKED",
                    score_points=int(pts),
                    distance_km=float(dkm),
                )
            )
        return out


def create_ranked_engine(url: str) -> Engine:
    from nutonic_server.leaderboard_store import create_leaderboard_engine

    return create_leaderboard_engine(url)


def create_ranked_store(url: str) -> SqliteRankedStore:
    from nutonic_server.leaderboard_store import _ensure_parent_dir_for_sqlite_file

    _ensure_parent_dir_for_sqlite_file(url)
    eng = create_ranked_engine(url)
    st = SqliteRankedStore(eng)
    st.initialize_schema()
    return st
