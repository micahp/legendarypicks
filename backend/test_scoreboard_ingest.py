"""The scoreboard snapshot store, the activity gate, and what the board serves.

These assert the two claims the design rests on:

  1. We do not ask a publisher about a league it says is not playing, and the
     decision comes from the publisher's own calendar rather than a hand list.
  2. Serving a board reads our store, and a store that cannot answer says so
     instead of handing back an empty slate.

The calendar fixtures are the real shapes, captured 2026-08-18 from the ESPN
cache: a `list` calendar with phase entries (NFL), one with per-event blocks
(UFC), and a `day` calendar whose day list is NOT the game-day list (MLB, whose
20 entries do not include a day it played 15 games).
"""
import datetime as dt
import os
import tempfile

import pytest

# Bound once, here. `conftest.py` restores LP_DB_PATH between tests, so a suite
# that reads the env at run time to find its own fixture DB finds the session's
# instead. The path is the constant; the env var is set for the modules to pick
# up when they resolve it.
_TMP = tempfile.TemporaryDirectory()
_DB_PATH = os.path.join(_TMP.name, "scoreboard-test.db")
os.environ["LP_DB_PATH"] = _DB_PATH

import league_activity  # noqa: E402
import scoreboard_store  # noqa: E402


def _payload(league_block, events=()):
    return {"leagues": [league_block], "events": list(events)}


NFL_CALENDAR = {
    "abbreviation": "NFL",
    "calendarType": "list",
    "season": {"startDate": "2026-08-06T07:00Z", "endDate": "2027-02-16T07:59Z"},
    "calendar": [
        {"label": "Preseason", "value": "1",
         "startDate": "2026-08-06T07:00Z", "endDate": "2026-09-06T06:59Z",
         "entries": [
             {"label": "Preseason Week 1", "startDate": "2026-08-13T07:00Z",
              "endDate": "2026-08-20T06:59Z"},
             {"label": "Preseason Week 2", "startDate": "2026-08-20T07:00Z",
              "endDate": "2026-08-27T06:59Z"},
         ]},
        {"label": "Off Season", "value": "4",
         "startDate": "2027-02-16T08:00Z", "endDate": "2027-08-01T06:59Z",
         "entries": []},
    ],
}

MLB_CALENDAR = {
    "abbreviation": "MLB",
    "calendarType": "day",
    "season": {"startDate": "2026-02-19T08:00Z", "endDate": "2026-11-12T07:59Z"},
    # Deliberately does not contain 2026-08-18, the day MLB played 15 games.
    "calendar": ["2026-02-19T08:00Z", "2026-07-13T07:00Z"],
}

NHL_CALENDAR = {
    "abbreviation": "NHL",
    "calendarType": "day",
    "season": {"startDate": "2025-09-20T07:00Z", "endDate": "2026-07-01T06:59Z"},
    "calendar": ["2025-09-20T07:00Z"],
}

UFC_CALENDAR = {
    "abbreviation": "UFC",
    "calendarType": "list",
    "season": {"startDate": "2026-01-01T05:00Z", "endDate": "2026-12-31T04:59Z"},
    "calendar": [
        {"label": "UFC 330", "startDate": "2026-08-16T22:00Z",
         "endDate": "2026-08-16T23:59Z"},
        {"label": "Contender Series Week 2", "startDate": "2026-08-19T01:30Z",
         "endDate": "2026-08-19T04:59Z"},
    ],
}


@pytest.fixture(autouse=True)
def clean_db():
    # `conftest.py` restores the SESSION's LP_DB_PATH before every test, and
    # these modules resolve the path per call -- so without this line the suite
    # is green when run alone and red under `LP_DB_PATH=data/picks.dev.db`,
    # reading the real dev database that the timers are writing to. Setting it
    # here, after conftest has had its turn, is what makes both runs the same.
    os.environ["LP_DB_PATH"] = _DB_PATH
    import sqlite3
    con = sqlite3.connect(_DB_PATH)
    con.executescript("DROP TABLE IF EXISTS league_activity;"
                      "DROP TABLE IF EXISTS scoreboard_snapshots;"
                      "DROP TABLE IF EXISTS scoreboard_refresh;")
    con.commit()
    con.close()
    league_activity.init()
    scoreboard_store.init()
    yield


class TestLeagueActivity:
    def test_off_season_block_is_excluded_by_its_published_type_id(self):
        league_activity.record_from_payload("nfl", _payload(NFL_CALENDAR))
        # In a preseason week: playing.
        assert league_activity.plays_on("nfl", "2026-08-18") is True
        # Inside the Off Season block, which carries season type id 4.
        assert league_activity.plays_on("nfl", "2027-04-01") is False

    def test_day_calendar_gates_on_the_season_not_the_day_list(self):
        """MLB is the reason a `day` calendar can never say no.

        Its list has 20 entries and does not include 2026-08-18, a day it played
        15 games. Gating on membership would have retired the busiest league on
        the board.
        """
        league_activity.record_from_payload("mlb", _payload(MLB_CALENDAR))
        assert league_activity.plays_on("mlb", "2026-08-18") is True

    def test_a_finished_season_is_refused(self):
        league_activity.record_from_payload("nhl", _payload(NHL_CALENDAR))
        assert league_activity.plays_on("nhl", "2026-08-18") is False

    def test_per_event_blocks_gate_to_the_event_days(self):
        league_activity.record_from_payload("ufc", _payload(UFC_CALENDAR))
        # An event at 01:30Z on the 19th is the evening of the 18th in the US,
        # which is why the window carries a day of padding on each side.
        assert league_activity.plays_on("ufc", "2026-08-19") is True
        assert league_activity.plays_on("ufc", "2026-08-18") is True
        assert league_activity.plays_on("ufc", "2026-09-15") is False

    def test_an_unknown_league_is_asked_not_assumed_idle(self):
        assert league_activity.plays_on("mls", "2026-08-18") is None
        ask, skip = league_activity.plan(["mls"], ["2026-08-18", "2026-08-19"])
        assert len(ask) == 2 and not skip

    def test_a_dormant_league_is_re_checked_rather_than_abandoned(self):
        league_activity.record_from_payload("nhl", _payload(NHL_CALENDAR))
        # Just checked: no request.
        ask, skip = league_activity.plan(["nhl"], ["2026-08-18", "2026-08-19"])
        assert ask == [] and len(skip) == 2

        # Stale: exactly one request, because a new season is only visible to
        # whoever asks.
        import sqlite3
        con = sqlite3.connect(_DB_PATH)
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
        con.execute("UPDATE league_activity SET checked_at=? WHERE league='nhl'", (old,))
        con.commit()
        con.close()
        ask, skip = league_activity.plan(["nhl"], ["2026-08-18", "2026-08-19"])
        assert len(ask) == 1


class TestScoreboardStore:
    def _game(self, gid, offset_hours, state):
        when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=offset_hours)
        return {"game_id": gid, "date": when.isoformat().replace("+00:00", "Z"),
                "state": state, "home": {"abbrev": "AAA"}, "away": {"abbrev": "BBB"}}

    def test_a_day_never_fetched_is_not_an_empty_day(self):
        assert scoreboard_store.read("mlb", "2026-08-18") is None
        scoreboard_store.save("mlb", "2026-08-18", [])
        stored = scoreboard_store.read("mlb", "2026-08-18")
        assert stored is not None and stored["games"] == []

    def test_a_dropped_game_disappears_instead_of_lingering(self):
        scoreboard_store.save("mlb", "2026-08-18",
                              [self._game("A", 2, "pre"), self._game("B", 3, "pre")])
        scoreboard_store.save("mlb", "2026-08-18", [self._game("A", 2, "pre")])
        stored = scoreboard_store.read("mlb", "2026-08-18")
        assert [g["game_id"] for g in stored["games"]] == ["A"]

    def test_live_targets_are_only_games_under_way(self):
        scoreboard_store.save("mlb", "2026-08-18", [
            self._game("started", -1, "in"),
            self._game("later", 4, "pre"),
        ])
        scoreboard_store.save("nhl", "2026-08-18", [self._game("done", -2, "post")])
        scoreboard_store.save("nba", "2026-08-18", [self._game("stuck", -30, "in")])
        targets = scoreboard_store.live_targets()
        assert ("mlb", "2026-08-18") in targets
        assert ("nhl", "2026-08-18") not in targets
        # A game 30 hours past its start and still not final is a row nobody
        # closed, not a live game. Polling it forever is a permanent cost.
        assert ("nba", "2026-08-18") not in targets

    def test_nothing_under_way_costs_nothing(self):
        scoreboard_store.save("mlb", "2026-08-18", [self._game("later", 5, "pre")])
        assert scoreboard_store.live_targets() == []

    def test_refresh_is_skipped_only_for_reasons_the_publisher_gave(self):
        wanted, reason = scoreboard_store.needs_refresh("mlb", "2026-08-18")
        assert wanted and reason == "never fetched"

        scoreboard_store.save("mlb", "2026-08-18", [])
        wanted, reason = scoreboard_store.needs_refresh("mlb", "2026-08-18")
        assert not wanted and "no games" in reason

        # Backed off, not abandoned: a late addition still lands.
        wanted, _ = scoreboard_store.needs_refresh(
            "mlb", "2026-08-18", empty_backoff=dt.timedelta(seconds=0))
        assert wanted

        scoreboard_store.save("nhl", "2026-08-17", [self._game("done", -5, "post")])
        wanted, reason = scoreboard_store.needs_refresh("nhl", "2026-08-17")
        assert not wanted and reason == "every game final"

        scoreboard_store.save("nba", "2026-08-18", [self._game("soon", 1, "pre")])
        wanted, reason = scoreboard_store.needs_refresh("nba", "2026-08-18")
        assert wanted and "not final" in reason

    def test_a_date_only_start_never_reads_as_under_way(self):
        """The DB result path publishes day precision on purpose.

        Storing `2026-08-18` as an instant would invent midnight UTC, which is
        in the past for most of a day and would make every finished game look
        like it had started and never ended.
        """
        scoreboard_store.save("mls", "2026-08-18", [
            {"game_id": "day-only", "date": "2026-08-18", "state": "post"}])
        assert scoreboard_store.live_targets() == []


class TestServingPath:
    def test_the_board_reads_the_store_and_reports_its_age(self):
        from routers.games import _scoreboard_snapshot
        scoreboard_store.save("mlb", "2026-08-18", [
            {"game_id": "1", "date": "2026-08-18T22:35Z", "state": "pre"}])
        games, age = _scoreboard_snapshot("mlb", "2026-08-18")
        assert len(games) == 1
        assert age is not None and age < 60

    def test_a_stale_snapshot_falls_through_rather_than_serving_quietly(self):
        import sqlite3
        from routers.games import _scoreboard_snapshot
        scoreboard_store.save("mlb", "2026-08-18", [
            {"game_id": "1", "date": "2026-08-18T22:35Z", "state": "in"}])
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat()
        con = sqlite3.connect(_DB_PATH)
        con.execute("UPDATE scoreboard_refresh SET fetched_at=? WHERE league='mlb'", (old,))
        con.commit()
        con.close()
        # A dead timer must degrade to calling the publisher, not serve a
        # two-hour-old live score as though it were now.
        assert _scoreboard_snapshot("mlb", "2026-08-18") is None

    def test_a_day_we_never_fetched_falls_through(self):
        from routers.games import _scoreboard_snapshot
        assert _scoreboard_snapshot("nhl", "2026-08-18") is None


class TestServingPathNeverSleeps:
    def test_an_exhausted_budget_refuses_instead_of_pausing(self):
        import paced_http
        paced_http.reset_host_budget()
        paced_http._host_spend["site.web.api.espn.com"] = 500
        try:
            with pytest.raises(paced_http.BudgetExhausted):
                paced_http._charge("https://site.web.api.espn.com/x", 100, 60,
                                   "refuse")
        finally:
            paced_http.reset_host_budget()

    def test_the_espn_client_the_handlers_use_is_the_refusing_one(self):
        import espn_client
        assert espn_client._FETCHER.on_exhausted == "refuse"


class TestStaleButFinished:
    def test_an_out_of_season_league_is_served_from_an_old_snapshot(self):
        """The age ceiling catches a dead timer, not a finished season.

        The ingest deliberately stops asking about the NHL in August, so its
        snapshot ages past the ceiling on purpose. Falling through to ESPN for
        it would restore the per-request upstream call on exactly the leagues
        that have nothing to say.
        """
        import sqlite3
        from routers.games import _scoreboard_snapshot
        league_activity.record_from_payload("nhl", _payload(NHL_CALENDAR))
        scoreboard_store.save("nhl", "2026-08-18", [])
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=6)).isoformat()
        con = sqlite3.connect(_DB_PATH)
        con.execute("UPDATE scoreboard_refresh SET fetched_at=? WHERE league='nhl'", (old,))
        con.commit()
        con.close()
        served = _scoreboard_snapshot("nhl", "2026-08-18")
        assert served is not None and served[0] == []

    def test_a_stale_live_day_still_falls_through(self):
        import sqlite3
        from routers.games import _scoreboard_snapshot
        league_activity.record_from_payload("mlb", _payload(MLB_CALENDAR))
        when = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
        scoreboard_store.save("mlb", "2026-08-18", [
            {"game_id": "1", "date": when.isoformat().replace("+00:00", "Z"),
             "state": "in"}])
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat()
        con = sqlite3.connect(_DB_PATH)
        con.execute("UPDATE scoreboard_refresh SET fetched_at=? WHERE league='mlb'", (old,))
        con.commit()
        con.close()
        assert _scoreboard_snapshot("mlb", "2026-08-18") is None
