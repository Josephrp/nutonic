"""Ranked round secrets + submit idempotency (IMP-090)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, insert, select, update

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
)

ranked_submit_idem = Table(
    "ranked_submit_idempotency",
    metadata,
    Column("round_id", String(64), primary_key=True, nullable=False),
    Column("idempotency_key", String(256), primary_key=True, nullable=False),
    Column("distance_km", Float, nullable=False),
    Column("score_points", Integer, nullable=False),
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


class SqliteRankedStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = Lock()

    def initialize_schema(self) -> None:
        metadata.create_all(self._engine)

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
