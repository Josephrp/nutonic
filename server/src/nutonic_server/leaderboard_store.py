from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    insert,
    select,
)
from sqlalchemy.engine import Engine, make_url

if TYPE_CHECKING:
    from nutonic_server.settings import Settings

metadata = MetaData()

leaderboard_rows = Table(
    "leaderboard_rows",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("map_id", String(256), nullable=False, index=True),
    Column("display_handle", String(64), nullable=False),
    Column("player_role", String(32), nullable=False),
    Column("score_points", Integer, nullable=False),
    Column("distance_km", Float, nullable=True),
)

leaderboard_idempotency = Table(
    "leaderboard_idempotency",
    metadata,
    Column("map_id", String(256), primary_key=True, nullable=False),
    Column("idempotency_key", String(256), primary_key=True, nullable=False),
    Column(
        "row_id",
        Integer,
        ForeignKey("leaderboard_rows.id", ondelete="CASCADE"),
        nullable=False,
    ),
)


@dataclass
class LeaderboardRow:
    display_handle: str
    player_role: str
    score_points: int
    distance_km: float | None = None


@runtime_checkable
class LeaderboardStore(Protocol):
    def list_rows(self, map_id: str) -> list[LeaderboardRow]: ...

    def append_row(
        self,
        map_id: str,
        row: LeaderboardRow,
        *,
        idempotency_key: str | None = None,
    ) -> LeaderboardRow: ...


@dataclass
class InMemoryLeaderboardStore:
    """S0 reference store (IMP-031); kept for tests and explicit `memory` URL."""

    _rows: dict[str, list[LeaderboardRow]] = field(default_factory=dict)
    _idempotency: dict[tuple[str, str], LeaderboardRow] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def __post_init__(self) -> None:
        with self._lock:
            if "demo" not in self._rows:
                self._rows["demo"] = [
                    LeaderboardRow("ECHO-1", "HUMAN", 9200, 12.4),
                    LeaderboardRow("VOID-WALKER", "ALIEN", 8800, 45.2),
                ]

    def list_rows(self, map_id: str) -> list[LeaderboardRow]:
        with self._lock:
            return list(self._rows.get(map_id, []))

    def append_row(
        self,
        map_id: str,
        row: LeaderboardRow,
        *,
        idempotency_key: str | None = None,
    ) -> LeaderboardRow:
        with self._lock:
            if idempotency_key:
                key = (map_id, idempotency_key.strip())
                if key in self._idempotency:
                    return self._idempotency[key]
            self._rows.setdefault(map_id, []).append(row)
            if idempotency_key:
                self._idempotency[(map_id, idempotency_key.strip())] = row
            return row


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


def create_leaderboard_engine(url: str) -> Engine:
    """Create engine; SQLite allows cross-thread checkout (FastAPI / uvicorn thread pool)."""
    engine_kwargs: dict = {}
    connect_args: dict[str, object] = {}
    u = make_url(url)
    if u.drivername in ("sqlite", "sqlite+pysqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool

            engine_kwargs["poolclass"] = StaticPool
        else:
            connect_args["timeout"] = 30.0
    engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragma(dbapi_conn, _connection_record) -> None:  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def _row_from_db(
    display_handle: str,
    player_role: str,
    score_points: int,
    distance_km: float | None,
) -> LeaderboardRow:
    return LeaderboardRow(
        display_handle=display_handle,
        player_role=player_role,
        score_points=score_points,
        distance_km=distance_km,
    )


class SqliteLeaderboardStore:
    """IMP-060: durable community leaderboard rows + POST idempotency."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = Lock()

    def initialize_schema(self) -> None:
        metadata.create_all(self._engine)
        self._seed_demo_if_empty()

    def _seed_demo_if_empty(self) -> None:
        with self._lock:
            with self._engine.begin() as conn:
                n = conn.execute(
                    select(leaderboard_rows.c.id).where(leaderboard_rows.c.map_id == "demo").limit(1)
                ).first()
                if n is not None:
                    return
                for r in (
                    LeaderboardRow("ECHO-1", "HUMAN", 9200, 12.4),
                    LeaderboardRow("VOID-WALKER", "ALIEN", 8800, 45.2),
                ):
                    conn.execute(
                        insert(leaderboard_rows).values(
                            map_id="demo",
                            display_handle=r.display_handle,
                            player_role=r.player_role,
                            score_points=r.score_points,
                            distance_km=r.distance_km,
                        )
                    )

    def list_rows(self, map_id: str) -> list[LeaderboardRow]:
        with self._lock:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    select(
                        leaderboard_rows.c.display_handle,
                        leaderboard_rows.c.player_role,
                        leaderboard_rows.c.score_points,
                        leaderboard_rows.c.distance_km,
                    )
                    .where(leaderboard_rows.c.map_id == map_id)
                    .order_by(leaderboard_rows.c.id)
                ).all()
                return [
                    _row_from_db(h, role, pts, dist) for h, role, pts, dist in rows
                ]

    def append_row(
        self,
        map_id: str,
        row: LeaderboardRow,
        *,
        idempotency_key: str | None = None,
    ) -> LeaderboardRow:
        key = idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
        with self._lock:
            with self._engine.begin() as conn:
                if key:
                    hit = conn.execute(
                        select(
                            leaderboard_rows.c.display_handle,
                            leaderboard_rows.c.player_role,
                            leaderboard_rows.c.score_points,
                            leaderboard_rows.c.distance_km,
                        )
                        .select_from(
                            leaderboard_idempotency.join(
                                leaderboard_rows,
                                leaderboard_idempotency.c.row_id == leaderboard_rows.c.id,
                            )
                        )
                        .where(
                            leaderboard_idempotency.c.map_id == map_id,
                            leaderboard_idempotency.c.idempotency_key == key,
                        )
                    ).first()
                    if hit is not None:
                        h, role, pts, dist = hit
                        return _row_from_db(h, role, pts, dist)

                row_id = conn.execute(
                    insert(leaderboard_rows)
                    .values(
                        map_id=map_id,
                        display_handle=row.display_handle,
                        player_role=row.player_role,
                        score_points=row.score_points,
                        distance_km=row.distance_km,
                    )
                    .returning(leaderboard_rows.c.id)
                ).scalar_one()
                if key:
                    conn.execute(
                        insert(leaderboard_idempotency).values(
                            map_id=map_id,
                            idempotency_key=key,
                            row_id=row_id,
                        )
                    )
        return row


def create_leaderboard_store(settings: Settings) -> LeaderboardStore:
    """Factory: SQLite by default; `memory` (case-insensitive) keeps in-process S0 store."""
    url = settings.leaderboard_database_url.strip()
    if url.lower() == "memory":
        return InMemoryLeaderboardStore()
    _ensure_parent_dir_for_sqlite_file(url)
    engine = create_leaderboard_engine(url)
    store = SqliteLeaderboardStore(engine)
    store.initialize_schema()
    return store
