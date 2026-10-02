import datetime as dt
import json
import sqlite3

import pytest

from dk_pool_store import DKPoolError, ensure_table, publish, read_unlocked

NOW = dt.datetime(2026, 10, 2, 12, 0, tzinfo=dt.timezone.utc)


def pool(slate_date="2026-10-03", lock="2026-10-03T20:00:00+00:00", fighters=24):
    return {"checked_at": NOW.isoformat(), "reason": None,
            "slate": {"slateDate": slate_date, "lockAt": lock, "fightCount": fighters // 2,
                      "source": "rotowire_live",
                      "fighters": [{"id": f"rw:{i}", "name": f"F {i}", "salary": 8000}
                                   for i in range(fighters)]}}


def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    ensure_table(connection)
    return connection


def test_round_trips_the_pool_and_stamps_when_it_was_captured():
    con = db()
    publish(con, pool(), captured_at=NOW.isoformat())
    got = read_unlocked(con, now=NOW)
    assert got["slate"]["fightCount"] == 12
    assert got["stored_captured_at"] == NOW.isoformat()


def test_a_locked_slate_is_never_served():
    """A past contest would read as the one you can still enter."""
    con = db()
    publish(con, pool(lock="2026-10-02T11:00:00+00:00"), captured_at=NOW.isoformat())
    assert read_unlocked(con, now=NOW) is None


def test_the_soonest_unlocked_slate_wins():
    con = db()
    publish(con, pool(slate_date="2026-10-10", lock="2026-10-10T20:00:00+00:00"),
            captured_at=NOW.isoformat())
    publish(con, pool(slate_date="2026-10-03", lock="2026-10-03T20:00:00+00:00"),
            captured_at=NOW.isoformat())
    assert read_unlocked(con, now=NOW)["slate"]["slateDate"] == "2026-10-03"


def test_recapturing_a_slate_replaces_it_rather_than_adding_a_row():
    con = db()
    publish(con, pool(), captured_at=NOW.isoformat())
    later = (NOW + dt.timedelta(minutes=30)).isoformat()
    publish(con, pool(fighters=22), captured_at=later)
    rows = con.execute("SELECT fighter_count,captured_at FROM dk_pool_snapshots").fetchall()
    assert len(rows) == 1
    assert rows[0]["fighter_count"] == 22 and rows[0]["captured_at"] == later


def test_a_pool_too_thin_for_a_lineup_is_refused():
    con = db()
    with pytest.raises(DKPoolError, match="six-fighter"):
        publish(con, pool(fighters=4), captured_at=NOW.isoformat())


def test_missing_table_reads_as_nothing_stored_not_an_error():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    assert read_unlocked(con, now=NOW) is None
