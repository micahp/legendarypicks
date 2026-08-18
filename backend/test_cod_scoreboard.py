"""COD is on the board and is not an ESPN league. The arrows must still work.

Measured 2026-08-18: `cod/schedule-dates` 404'd, because the handler gated on
`espn.LEAGUES` -- which answers "can we ask ESPN about this", not "can the
board navigate to a day of it". Nothing ever captured COD either, so even
without the 404 there were no days to navigate to. Both halves are fixed here:
the ingest captures breakingpoint's whole schedule in one request, and the
handler serves a local-only league from the store.

COD is out of season as of this date, so the empty case below is the state the
code is actually in and matters more than the populated one.
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(__file__))

_TMP = tempfile.TemporaryDirectory()
_DB_PATH = os.path.join(_TMP.name, "cod-test.db")
os.environ["LP_DB_PATH"] = _DB_PATH

import ingest_scoreboards
import scoreboard_store


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    # LP_DB_PATH alone is NOT enough. `conftest.py` restores the session value
    # between tests, and the games package reaches a database through its own
    # `_db()` rather than re-reading the environment, so an env-only fixture
    # reads whatever the timers have written to the real dev database. That is
    # exactly how this test passed alone and failed in the suite: the handler
    # answered with live Esports World Cup dates instead of the fixture's.
    os.environ["LP_DB_PATH"] = _DB_PATH
    import sqlite3
    con = sqlite3.connect(_DB_PATH)
    con.executescript("DROP TABLE IF EXISTS scoreboard_snapshots;"
                      "DROP TABLE IF EXISTS scoreboard_refresh;")
    con.commit()
    con.close()
    scoreboard_store.init()

    from routers import games

    def _fixture_db():
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(games, "_db", _fixture_db)
    # And pin the STORE's path too. `conftest.py`'s own autouse fixture
    # restores the session LP_DB_PATH after this one runs, so an env-only pin
    # leaves the writer on the real database while the reader is on the
    # fixture: the test then sees an empty result and reads as a code defect.
    monkeypatch.setattr(scoreboard_store, "_db_path", lambda: _DB_PATH)
    yield


def _matches():
    return [
        {"game_id": "BP-1", "date": "2026-01-24T20:00:00Z", "state": "post",
         "home": {"abbrev": "OpTic"}, "away": {"abbrev": "Breach"}},
        {"game_id": "BP-2", "date": "2026-01-24T23:00:00Z", "state": "post",
         "home": {"abbrev": "Faze"}, "away": {"abbrev": "Ravens"}},
        {"game_id": "BP-3", "date": "2026-01-25T20:00:00Z", "state": "pre",
         "home": {"abbrev": "Surge"}, "away": {"abbrev": "Thieves"}},
    ]


class TestOneRequestCapturesEveryDay:
    def test_the_whole_schedule_is_bucketed_by_day(self, monkeypatch):
        """`get_cod_matches()` with no date returns everything, so one call is
        the entire calendar. Per-day requests would be pure waste."""
        import breakingpoint_client
        monkeypatch.setattr(breakingpoint_client, "get_cod_matches",
                            lambda *a, **k: _matches())
        days, error = ingest_scoreboards.refresh_cod(verbose=False)
        assert error is None
        assert days == 2
        assert len(scoreboard_store.read("cod", "2026-01-24")["games"]) == 2
        assert len(scoreboard_store.read("cod", "2026-01-25")["games"]) == 1

    def test_bucketing_is_utc_because_the_handler_filters_on_utc(self, monkeypatch):
        """`get_cod_matches(date_str)` compares UTC dates. Keying the store any
        other way puts a match on a day the handler will not look for it."""
        import breakingpoint_client
        monkeypatch.setattr(breakingpoint_client, "get_cod_matches",
                            lambda *a, **k: [
                                {"game_id": "BP-9", "date": "2026-01-25T02:00:00Z",
                                 "state": "post", "home": {}, "away": {}}])
        ingest_scoreboards.refresh_cod(verbose=False)
        # 02:00Z is the 25th in UTC and the 24th in every US timezone.
        assert scoreboard_store.read("cod", "2026-01-25") is not None
        assert scoreboard_store.read("cod", "2026-01-24") is None


class TestOffSeasonIsNotAnEmptyCalendar:
    def test_an_empty_schedule_writes_nothing(self, monkeypatch):
        """COD is dark for months. Writing empty slates across a whole calendar
        would retire those days permanently, because a finished empty day is
        treated as final and never re-asked. Absent evidence is not a zero."""
        import breakingpoint_client
        monkeypatch.setattr(breakingpoint_client, "get_cod_matches", lambda *a, **k: [])
        days, error = ingest_scoreboards.refresh_cod(verbose=False)
        assert days == 0
        assert error is None
        assert scoreboard_store.read("cod", "2026-01-24") is None

    def test_a_publisher_failure_is_reported_not_swallowed(self, monkeypatch):
        import breakingpoint_client
        def boom(*a, **k):
            raise RuntimeError("breakingpoint unreachable")
        monkeypatch.setattr(breakingpoint_client, "get_cod_matches", boom)
        days, error = ingest_scoreboards.refresh_cod(verbose=False)
        assert days == 0
        assert error and "breakingpoint unreachable" in error


class TestTheArrowsCanReachACodDay:
    def test_schedule_dates_serves_cod_from_the_store(self, monkeypatch):
        import breakingpoint_client
        from routers import games
        monkeypatch.setattr(breakingpoint_client, "get_cod_matches",
                            lambda *a, **k: _matches())
        ingest_scoreboards.refresh_cod(verbose=False)
        body = games.get_schedule_dates("cod", "2026-01-25").body.decode()
        assert '"source":"local"' in body.replace(" ", "")
        assert "2026-01-24T20:00:00" in body

    def test_cod_never_reaches_the_espn_search_path(self, monkeypatch):
        """A local-only league has no publisher to fall through to. Calling one
        would log a failure and return the same answer."""
        from routers import games
        with mock_raises(games.espn, "schedule_event_starts"):
            body = games.get_schedule_dates("cod", "2026-01-25").body.decode()
        assert '"source":"local"' in body.replace(" ", "")

    def test_no_days_held_is_an_honest_empty_not_a_404(self):
        """Off season. The route must answer, so the client can tell 'no COD
        games that way' from 'this endpoint is broken'."""
        from routers import games
        response = games.get_schedule_dates("cod", "2026-01-25")
        assert response.status_code == 200
        body = response.body.decode().replace(" ", "")
        assert '"past_event_starts":[]' in body
        assert '"future_event_starts":[]' in body

    def test_a_league_nobody_carries_is_still_a_404(self):
        from fastapi import HTTPException
        from routers import games
        with pytest.raises(HTTPException) as exc:
            games.get_schedule_dates("quidditch", "2026-01-25")
        assert exc.value.status_code == 404


class mock_raises:
    """Patch an attribute to raise, so a call to it fails the test loudly."""
    def __init__(self, target, name):
        self.target, self.name = target, name

    def __enter__(self):
        self.prev = getattr(self.target, self.name)
        def boom(*a, **k):
            raise AssertionError(f"{self.name} must not be called for a local-only league")
        setattr(self.target, self.name, boom)

    def __exit__(self, *exc):
        setattr(self.target, self.name, self.prev)
        return False


class TestOneUnreadableSourceDoesNotLoseTheOther:
    """`_local_event_starts` reads two tables. A single UNION lost both.

    Found 2026-08-18 against a database with no `prop_games`: COD's stored days
    were discarded because of a table COD never writes to. Partial evidence is
    still evidence, and only "no source answered" is honestly empty.
    """

    def test_days_survive_a_missing_second_table(self, monkeypatch):
        import datetime as dt
        import sqlite3
        import breakingpoint_client
        from routers import games

        monkeypatch.setattr(breakingpoint_client, "get_cod_matches",
                            lambda *a, **k: _matches())
        ingest_scoreboards.refresh_cod(verbose=False)
        con = sqlite3.connect(_DB_PATH)
        con.execute("DROP TABLE IF EXISTS prop_games")
        con.commit()
        con.close()

        starts = games._local_event_starts("cod", dt.date(2026, 1, 25), "past")
        assert starts, "a missing prop_games must not discard scoreboard_snapshots"
        assert any("2026-01-24" in s for s in starts)
