from __future__ import annotations

from pathlib import Path

from nutonic_server.leaderboard_store import (
    InMemoryLeaderboardStore,
    LeaderboardRow,
    SqliteLeaderboardStore,
    create_leaderboard_engine,
    create_leaderboard_store,
)
from nutonic_server.settings import Settings


def test_sqlite_leaderboard_survives_process_reopen(tmp_path: Path) -> None:
    """Rows and idempotency survive a new Engine / store on the same file (IMP-060)."""
    db_path = tmp_path / "lb.sqlite3"
    url = f"sqlite+pysqlite:///{db_path.as_posix()}"

    e1 = create_leaderboard_engine(url)
    s1 = SqliteLeaderboardStore(e1)
    s1.initialize_schema()
    s1.append_row(
        "xmap",
        LeaderboardRow("A", "HUMAN", 10, 1.0),
        idempotency_key="k1",
    )
    e1.dispose()

    e2 = create_leaderboard_engine(url)
    s2 = SqliteLeaderboardStore(e2)
    s2.initialize_schema()
    rows = s2.list_rows("xmap")
    assert len(rows) == 1
    assert rows[0].display_handle == "A"

    dup = s2.append_row(
        "xmap",
        LeaderboardRow("B", "ALIEN", 20, 2.0),
        idempotency_key="k1",
    )
    assert dup.display_handle == "A"
    assert len(s2.list_rows("xmap")) == 1


def test_create_leaderboard_store_memory_is_in_memory() -> None:
    store = create_leaderboard_store(Settings(leaderboard_database_url="memory"))
    assert isinstance(store, InMemoryLeaderboardStore)
    assert len(store.list_rows("demo")) >= 1


def test_create_leaderboard_store_sqlite_via_settings(tmp_path: Path) -> None:
    db_path = tmp_path / "via_settings.sqlite3"
    url = f"sqlite+pysqlite:///{db_path.as_posix()}"
    store = create_leaderboard_store(Settings(leaderboard_database_url=url))
    assert isinstance(store, SqliteLeaderboardStore)
    store.append_row("m1", LeaderboardRow("Z", "HUMAN", 5, None))
    assert store.list_rows("m1")[0].display_handle == "Z"


def test_sqlite_list_rows_thread_safe_materialization() -> None:
    """Rows are fully fetched before connection closes (regression guard)."""
    url = "sqlite+pysqlite:///:memory:"
    engine = create_leaderboard_engine(url)
    store = SqliteLeaderboardStore(engine)
    store.initialize_schema()
    store.append_row("t", LeaderboardRow("P", "ALIEN", 1, 2.5))
    rows = store.list_rows("t")
    assert len(rows) == 1
    assert rows[0].player_role == "ALIEN"
