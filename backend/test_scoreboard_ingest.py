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
        scoreboard_store.save("wc", "2026-08-18", [self._game("stale-wc", -1, "in")])
        assert ("wc", "2026-08-18") not in scoreboard_store.live_targets()
        # A game 30 hours past its start and still not final is a row nobody
        # closed, not a live game. Polling it forever is a permanent cost.
        assert ("nba", "2026-08-18") not in targets

    def test_nothing_under_way_costs_nothing(self):
        scoreboard_store.save("mlb", "2026-08-18", [self._game("later", 5, "pre")])
        assert scoreboard_store.live_targets() == []

    def test_tonights_empty_slate_is_not_called_over_during_prime_time(self):
        """The UTC date rolls over at 20:00 ET, `game_date` does not.

        `needs_refresh` compared `game_date` against the UTC date, so from 8pm
        to midnight Eastern tonight's slate sorted as strictly less than
        "today" and answered "day is over and published no games". The backoff
        that exists to catch a late addition was skipped for the four hours a
        late addition is most likely. Fails against `_now().date()`.
        """
        for league, clock in (("mlb", "america/new_york"), ("atp", "utc")):
            today = scoreboard_store._today_for(league)
            scoreboard_store.save(league, today, [])
            wanted, reason = scoreboard_store.needs_refresh(
                league, today, empty_backoff=dt.timedelta(seconds=0))
            assert wanted, (
                "%s slate %s (%s) was called over; reason=%r"
                % (league, today, clock, reason))
            assert "day is over" not in reason

    def test_a_day_that_really_is_over_is_still_final(self):
        """The fix must not turn the backoff into an infinite retry."""
        today = scoreboard_store._today_for("mlb")
        yesterday = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
        scoreboard_store.save("mlb", yesterday, [])
        wanted, reason = scoreboard_store.needs_refresh(
            "mlb", yesterday, empty_backoff=dt.timedelta(seconds=0))
        assert not wanted and "day is over" in reason, reason

    def test_refresh_is_skipped_only_for_reasons_the_publisher_gave(self):
        # TODAY, computed, not a literal. This test hardcoded 2026-08-18, which
        # was today when it was written and became yesterday at midnight -- at
        # which point the "a day that is OVER and published no games is final"
        # rule correctly overrode the backoff and the test failed for a reason
        # that had nothing to do with the behaviour it was checking. A date
        # literal in a test about "is this day finished" is a time bomb.
        #
        # `dt.date.today()` was the second time bomb, and it went off on
        # 2026-08-19. It is the BOX's local date, and the store keys `game_date`
        # by the New York slate day -- two clocks that disagree for one hour a
        # night on a Central box, and for four hours against the UTC date the
        # store used to compare with. Ask the code for its own idea of today so
        # this cannot drift again.
        today = scoreboard_store._today_for("mlb")
        wanted, reason = scoreboard_store.needs_refresh("mlb", today)
        assert wanted and reason == "never fetched"

        scoreboard_store.save("mlb", today, [])
        wanted, reason = scoreboard_store.needs_refresh("mlb", today)
        assert not wanted and "no games" in reason

        # Backed off, not abandoned: a late addition still lands. Only true
        # while the day is still current; see TestAnEmptyFinishedDayIsNotReasked.
        wanted, _ = scoreboard_store.needs_refresh(
            "mlb", today, empty_backoff=dt.timedelta(seconds=0))
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

    def test_a_stale_scheduled_slate_remains_visible(self):
        """The hourly refresh boundary must not erase tomorrow's games."""
        import sqlite3
        from routers.games import _scoreboard_snapshot
        scoreboard_store.save("mlb", "2026-08-18", [
            {"game_id": "1", "date": "2026-08-18T22:35Z", "state": "pre"}])
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat()
        con = sqlite3.connect(_DB_PATH)
        con.execute("UPDATE scoreboard_refresh SET fetched_at=? WHERE league='mlb'", (old,))
        con.commit()
        con.close()
        games, age = _scoreboard_snapshot("mlb", "2026-08-18")
        assert [game["game_id"] for game in games] == ["1"]
        assert age > 3600


class TestServingPathNeverSleeps:
    def test_the_obsolete_lifetime_budget_does_not_refuse_a_handler(self):
        import paced_http
        paced_http.reset_host_budget()
        paced_http._host_spend["site.web.api.espn.com"] = 500
        try:
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


class TestUfcEventName:
    def test_the_week_survives_normalization(self, monkeypatch):
        """ESPN drops the week from `shortName` and keeps it on `name`.

        Measured 2026-08-18:
          name      "Dana White's Contender Series: Season 10, Week 2"
          shortName "Dana White's Contender Series"
        The board names a UFC card the way it names a tennis tournament, and
        "Contender Series" with no week is three different events a month
        sharing one heading.
        """
        import espn_client
        payload = {
            "leagues": [UFC_CALENDAR],
            "events": [{
                "id": "600060733",
                "name": "Dana White's Contender Series: Season 10, Week 2",
                "shortName": "Dana White's Contender Series",
                "date": "2026-08-18T23:00Z",
                "competitions": [{
                    "id": "401903488",
                    "date": "2026-08-18T23:00Z",
                    "startDate": "2026-08-18T23:00Z",
                    "status": {"type": {"state": "pre", "description": "Scheduled",
                                        "shortDetail": "8/18 - 7:00 PM EDT"}},
                    "competitors": [
                        {"id": "1", "order": 1, "athlete": {"displayName": "A Fighter"}},
                        {"id": "2", "order": 2, "athlete": {"displayName": "B Fighter"}},
                    ],
                }],
            }],
        }
        monkeypatch.setattr(espn_client, "_get", lambda url, ttl=20: payload)
        games = espn_client.games("ufc", "2026-08-18")
        assert games
        assert games[0]["event"] == "Dana White's Contender Series: Season 10, Week 2"
        assert games[0]["card_segment"] == "Main Card"


class TestDayNavigation:
    @staticmethod
    def _point_router_at_the_fixture(monkeypatch):
        """`routers.games` reaches the DB through `_core._db`, whose path is
        bound at IMPORT time. Run alone this module imports first and the fixture
        wins; run in the full suite another module imported `_core` already and
        the reads land on the session database. Patching the function the router
        actually calls is what makes both runs the same -- and is why no test
        here ever writes to a real database.
        """
        import sqlite3
        import routers.games as games_router

        def _fixture_db():
            con = sqlite3.connect(_DB_PATH)
            con.row_factory = sqlite3.Row
            return con

        monkeypatch.setattr(games_router, "_db", _fixture_db)

    def test_the_back_arrow_answers_from_what_we_hold(self, monkeypatch):
        self._point_router_at_the_fixture(monkeypatch)
        """The arrows used to ask ESPN on every click, so a 403 froze the board.

        Measured 2026-08-18: `schedule-dates` returned `source: unavailable` for
        every league and going back past Sunday was impossible, while UFC 330's
        start instants were sitting in our own `prop_games` the whole time.
        """
        import sqlite3
        from routers.games import _local_event_starts
        con = sqlite3.connect(_DB_PATH)
        con.executescript(
            "CREATE TABLE IF NOT EXISTS prop_games("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT NOT NULL,"
            " date TEXT NOT NULL, home TEXT, away TEXT, espn_event_id TEXT,"
            " final_home INTEGER, final_away INTEGER, start_time TEXT)")
        con.execute("DELETE FROM prop_games")
        con.execute("INSERT INTO prop_games (league, date, start_time)"
                    " VALUES ('ufc','2026-08-16','2026-08-16T01:20:00+00:00')")
        con.commit()
        con.close()

        past = _local_event_starts("ufc", dt.date(2026, 8, 18), "past")
        assert any(value.startswith("2026-08-16") for value in past)
        assert _local_event_starts("ufc", dt.date(2026, 8, 18), "future") == []

    def test_a_day_precision_row_is_never_promoted_to_an_instant(self, monkeypatch):
        self._point_router_at_the_fixture(monkeypatch)
        """`team_game_results` is day precision on purpose.

        Turning `2026-08-16` into midnight UTC moves the event onto the previous
        local day throughout the Americas. The contract promises instants, so a
        fabricated one is worse than a missing one.
        """
        import sqlite3
        from routers.games import _local_event_starts
        con = sqlite3.connect(_DB_PATH)
        con.execute("DELETE FROM prop_games")
        con.execute("INSERT INTO prop_games (league, date, start_time)"
                    " VALUES ('mlb','2026-08-16',NULL)")
        con.commit()
        con.close()
        assert _local_event_starts("mlb", dt.date(2026, 8, 18), "past") == []


class TestThePastIsNeverAsked:
    """A day that is over cannot change, so it is never worth a request.

    Anything we do not already hold for a finished day is a gap in our own
    capture, and asking a publisher about it spends a request per page view on a
    fact that is already fixed.
    """

    def _no_publisher(self, monkeypatch):
        import espn_client

        def _refuse(*args, **kwargs):
            raise AssertionError("the past must never reach the publisher")

        monkeypatch.setattr(espn_client, "games", _refuse)
        monkeypatch.setattr(espn_client, "schedule_event_starts", _refuse)

    def test_a_finished_day_we_do_not_hold_says_so_instead_of_asking(self, monkeypatch):
        from fastapi.testclient import TestClient
        import sports_service
        self._no_publisher(monkeypatch)
        client = TestClient(sports_service.app)
        yesterday = (dt.date.today() - dt.timedelta(days=3)).isoformat()
        response = client.get(f"/api/mlb/games?date={yesterday}")
        assert response.status_code == 200
        assert response.json() == []
        assert response.headers.get("X-LP-Data-Source") == "unavailable"

    def test_a_finished_day_we_do_hold_is_served_from_the_store(self, monkeypatch):
        from fastapi.testclient import TestClient
        import sports_service
        self._no_publisher(monkeypatch)
        past = (dt.date.today() - dt.timedelta(days=4)).isoformat()
        scoreboard_store.save("nhl", past, [
            {"game_id": "9", "date": f"{past}T23:00:00+00:00", "state": "post",
             "home": {"abbrev": "AAA", "score": 3}, "away": {"abbrev": "BBB", "score": 2}}])
        client = TestClient(sports_service.app)
        response = client.get(f"/api/nhl/games?date={past}")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.headers.get("X-LP-Data-Source") == "scoreboard_snapshots"


class TestOnlyOneRunSpendsTheBudget:
    """The per-host budget is shared; the counter that guards it is not.

    Each process keeps its own `paced_http._host_spend`, so two copies of the
    ingest each stop at HOST_BUDGET while together spending twice it. Measured
    2026-08-18: a backfill still running plus a second one started on top of it
    took all three ESPN hosts from answering to refusing this box. A declared
    ceiling that two processes can each spend is not a ceiling.
    """

    def test_the_second_run_declines_instead_of_overlapping(self):
        import tempfile
        import ingest_scoreboards
        with tempfile.NamedTemporaryFile(suffix=".lock") as tmp:
            first = ingest_scoreboards._only_one_run(tmp.name)
            assert first is not None, "the first run must be allowed to start"
            try:
                second = ingest_scoreboards._only_one_run(tmp.name)
                assert second is None, \
                    "a second concurrent run must decline, not double the spend"
            finally:
                first.close()

    def test_the_lock_is_released_so_the_next_timer_tick_runs(self):
        """A lock that outlives its holder is an outage, not a safeguard."""
        import tempfile
        import ingest_scoreboards
        with tempfile.NamedTemporaryFile(suffix=".lock") as tmp:
            ingest_scoreboards._only_one_run(tmp.name).close()
            again = ingest_scoreboards._only_one_run(tmp.name)
            assert again is not None
            again.close()


class TestAnEmptyFinishedDayIsNotReasked:
    def test_a_past_day_that_published_nothing_is_final(self):
        """Backoff is for a slate that might still change. A finished one cannot.

        Without this, every viewer of an old empty day re-triggered the fetch
        once the three-hour backoff lapsed -- a request per viewer for an
        answer that was fixed the moment the day ended.
        """
        import scoreboard_store
        scoreboard_store.save("nba", "2026-08-01", [], source="espn")
        wanted, reason = scoreboard_store.needs_refresh("nba", "2026-08-01")
        assert not wanted, reason
        assert "over" in reason


class TestTheLiveRunWaitsRatherThanSkipping:
    """A safeguard that costs live scores every hour is priced wrong.

    The lock exists to stop two runs spending one shared budget. Declining
    instantly also meant the once-a-minute live poll lost its whole tick to a
    schedule run that takes seven seconds -- measured 2026-08-18, three lost
    polls in one hour for no protection that a short wait would not give.
    """

    def test_a_waiting_run_acquires_once_the_holder_releases(self):
        import tempfile, threading, time as _t
        import ingest_scoreboards
        with tempfile.NamedTemporaryFile(suffix=".lock") as tmp:
            held = ingest_scoreboards._only_one_run(tmp.name)
            assert held is not None
            threading.Timer(0.6, held.close).start()
            started = _t.time()
            waited = ingest_scoreboards._only_one_run(tmp.name, wait_seconds=5.0)
            assert waited is not None, "the waiter must get in once the lock frees"
            assert _t.time() - started >= 0.5, "it must actually have waited"
            waited.close()

    def test_a_wait_that_expires_still_declines(self):
        """Waiting is bounded. A backfill running for minutes still wins."""
        import tempfile
        import ingest_scoreboards
        with tempfile.NamedTemporaryFile(suffix=".lock") as tmp:
            held = ingest_scoreboards._only_one_run(tmp.name)
            try:
                assert ingest_scoreboards._only_one_run(tmp.name, wait_seconds=1.0) is None
            finally:
                held.close()


class TestAFutureSlateIsNotRepolled:
    """A slate that has not started is re-read 144 times a day for nothing.

    Measured 2026-08-24, prod: `needs_refresh` answered `True, "N not final"`
    for tomorrow on every league carrying a published slate (atp, wta, mlb,
    ufc, lcup). The schedule run fires every 10 minutes, so five leagues cost
    720 requests a day per environment to re-read a schedule that cannot have
    changed, on a box that had already been 403'd twice that day.

    The asymmetry is what makes it a defect rather than a cost: a league that
    published NOTHING for tomorrow got the 3h empty backoff, while a league
    that published a schedule got no backoff at all. The more a publisher told
    us, the more we asked it.
    """

    def _game(self, gid, offset_hours, state):
        when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=offset_hours)
        return {"game_id": gid, "date": when.isoformat().replace("+00:00", "Z"),
                "state": state, "home": {"abbrev": "AAA"}, "away": {"abbrev": "BBB"}}

    def _tomorrow(self, league="mlb"):
        return (dt.date.fromisoformat(scoreboard_store._today_for(league))
                + dt.timedelta(days=1)).isoformat()

    def test_tomorrows_unstarted_slate_is_not_asked_again_immediately(self):
        tomorrow = self._tomorrow()
        scoreboard_store.save("mlb", tomorrow,
                              [self._game("A", 26, "pre"), self._game("B", 28, "pre")])
        wanted, reason = scoreboard_store.needs_refresh("mlb", tomorrow)
        assert not wanted, reason
        assert "future slate" in reason

    def test_the_backoff_expires_so_a_postponement_still_lands(self):
        """Backed off, not abandoned. A slate really can change."""
        tomorrow = self._tomorrow()
        scoreboard_store.save("mlb", tomorrow, [self._game("A", 26, "pre")])
        wanted, reason = scoreboard_store.needs_refresh(
            "mlb", tomorrow, future_backoff=dt.timedelta(seconds=0))
        assert wanted and "future slate" in reason, reason

    def test_todays_unstarted_slate_is_still_asked(self):
        """The whole point is the DATE, not the state.

        Today's games are `pre` for hours before first pitch and that window is
        exactly when a lineup, a start time or a postponement moves. Backing off
        here would be a regression, not a saving.
        """
        today = scoreboard_store._today_for("mlb")
        scoreboard_store.save("mlb", today, [self._game("A", 4, "pre")])
        wanted, reason = scoreboard_store.needs_refresh("mlb", today)
        assert wanted and "not final" in reason, reason

    def test_one_game_in_flight_overrides_the_date(self):
        """`game_date` is a slate day, so the clock can roll over mid-game.

        A date comparison alone would park a live board. One started game hands
        the day straight back to the unfinished path.
        """
        tomorrow = self._tomorrow()
        scoreboard_store.save("mlb", tomorrow,
                              [self._game("A", 1, "in"), self._game("B", 26, "pre")])
        wanted, reason = scoreboard_store.needs_refresh("mlb", tomorrow)
        assert wanted and "not final" in reason, reason

    def test_a_finished_game_on_a_future_date_also_overrides(self):
        tomorrow = self._tomorrow()
        scoreboard_store.save("mlb", tomorrow,
                              [self._game("A", -1, "post"), self._game("B", 26, "pre")])
        wanted, reason = scoreboard_store.needs_refresh("mlb", tomorrow)
        assert wanted and "not final" in reason, reason

    def test_a_past_day_is_unaffected(self):
        """The finished-day rule still owns yesterday."""
        today = scoreboard_store._today_for("mlb")
        yesterday = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
        scoreboard_store.save("mlb", yesterday, [self._game("A", -20, "post")])
        wanted, reason = scoreboard_store.needs_refresh("mlb", yesterday)
        assert not wanted and reason == "every game final", reason

    def test_tennis_gets_the_backoff_on_its_own_clock(self):
        """Tennis buckets `game_date` by UTC and every other league by ET.

        `_today_for` is league-aware for that reason, and the backoff must ask
        the same question on the same ruler rather than reintroducing the
        two-clock bug the empty backoff already had.
        """
        tomorrow = self._tomorrow("atp")
        scoreboard_store.save("atp", tomorrow, [self._game("A", 26, "pre")])
        wanted, reason = scoreboard_store.needs_refresh("atp", tomorrow)
        assert not wanted and "future slate" in reason, reason

    def test_an_empty_future_day_still_uses_the_empty_backoff(self):
        """The two backoffs must not fight. Empty is the publisher saying
        nothing is scheduled; future-unstarted is it saying something is."""
        tomorrow = self._tomorrow()
        scoreboard_store.save("mlb", tomorrow, [])
        wanted, reason = scoreboard_store.needs_refresh("mlb", tomorrow)
        assert not wanted and "no games" in reason, reason
