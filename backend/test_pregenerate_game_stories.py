"""The timer sweep's league set comes from the database, never a list.

pregenerate_game_stories.DEFAULT_LEAGUES used to be the literal `nba nhl mlb nfl`,
and it went stale exactly the way league_offering's docstring predicts: the hub
offered mls, ncaaf and ufc, and the timer sweep never covered any of them — the
measurement that started this work (2026-08-14) found mls/ncaaf/ufc with zero
game_story rows while mlb had 541. The sweep must resolve its leagues through
`league_offering.offered_leagues`, the same registry every server gate reads, so
a league turns on the moment its coverage row is promoted and there is no second
list to remember.
"""
import sqlite3

import pytest

from conftest import real_db
from league_offering import ALWAYS_OFFERED


def _db(rows=()):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE team_stats_coverage(league TEXT, season INT, status TEXT)")
    con.executemany("INSERT INTO team_stats_coverage VALUES(?,?,?)", rows)
    return con


def _pregenerate():
    import pregenerate_game_stories as p
    return p


class TestDefaultLeagues:
    def test_the_literal_list_is_gone(self):
        # The regression itself: DEFAULT_LEAGUES was a second hardcoded list.
        assert not hasattr(_pregenerate(), "DEFAULT_LEAGUES")

    def test_resolves_through_offered_leagues(self):
        p = _pregenerate()
        con = _db([("nfl", 2025, "complete"), ("mlb", 2026, "in_progress")])
        # WC remains manually addressable but is excluded from recurring work.
        assert p.default_leagues(con) == ["mlb", "nfl", "ufc"]

    def test_a_promoted_league_turns_on_without_an_edit(self):
        p = _pregenerate()
        con = _db([("nfl", 2025, "complete"), ("mls", 2026, "complete"),
                   ("ncaaf", 2026, "complete")])
        assert {"mls", "ncaaf"} <= set(p.default_leagues(con))

    def test_an_unvouched_league_is_not_swept(self):
        p = _pregenerate()
        con = _db([("nfl", 2025, "complete"), ("ncaaf", 2025, "unverified")])
        assert "ncaaf" not in p.default_leagues(con)

    def test_missing_registry_fails_closed_to_shape_set(self):
        # No table: "could not check" must not open the sweep to everything,
        # and there is no fallback list for the job to quietly sweep instead.
        p = _pregenerate()
        con = sqlite3.connect(":memory:")
        assert p.default_leagues(con) == sorted(ALWAYS_OFFERED - {"wc"})

    def test_no_connection_uses_the_core_database(self, monkeypatch):
        p = _pregenerate()
        import _core
        con = _db([("nfl", 2025, "complete")])
        monkeypatch.setattr(_core, "_db", lambda: con)
        assert p.default_leagues() == ["nfl", "ufc"]


class TestDefaultLeaguesAgainstTheRealDatabases:
    """The leagues the old list missed must be in the set this database yields."""

    @pytest.mark.parametrize("name", ["picks.dev.db"])
    def test_the_zero_story_leagues_are_in_the_sweep_set(self, name):
        path = real_db(name)
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            pytest.skip(f"{path} not present")
        con.row_factory = sqlite3.Row
        try:
            leagues = _pregenerate().default_leagues(con)
        finally:
            con.close()
        # The 2026-08-14 measurement: mls/ncaaf/ufc had zero stories while the
        # old default list skipped them. The sweep must cover every one.
        assert {"mls", "ncaaf", "ufc"} <= set(leagues), leagues
