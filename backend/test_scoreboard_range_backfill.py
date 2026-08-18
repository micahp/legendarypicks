"""Range-form backfill: chunking, the 100-event cap, and the tennis refusal.

The backfill used to cost one ESPN request per (league, day). The scoreboard
endpoint also answers `?dates=YYYYMMDD-YYYYMMDD`, measured 2026-08-18 (clean,
after the block): 200 for team/combat/soccer leagues, capped around 100
events, and `events: []` for tennis. These tests pin the three behaviours the
range path rests on:

  1. a run of missing days is chunked into windows (split at gaps and at the
     cap, never including a day we already hold),
  2. a chunk that comes back at the ceiling is split in half and retried so
     a truncated response cannot masquerade as a complete day,
  3. tennis stays per-day because the range form answers nothing for it.
"""
import datetime as dt
import os
import tempfile

import pytest

_TMP = tempfile.TemporaryDirectory()
_DB_PATH = os.path.join(_TMP.name, "range-backfill-test.db")
os.environ["LP_DB_PATH"] = _DB_PATH

import league_activity  # noqa: E402
import scoreboard_store  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
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


class TestRangeChunks:
    def test_contiguous_days_are_one_chunk(self):
        import ingest_scoreboards
        days = [f"2026-08-{d:02d}" for d in range(10, 15)]
        assert ingest_scoreboards._range_chunks(days) == [days]

    def test_a_gap_splits_the_chunk(self):
        import ingest_scoreboards
        days = ["2026-08-10", "2026-08-11", "2026-08-13", "2026-08-14"]
        assert ingest_scoreboards._range_chunks(days) == [
            ["2026-08-10", "2026-08-11"],
            ["2026-08-13", "2026-08-14"],
        ]

    def test_max_days_is_enforced(self):
        import ingest_scoreboards
        days = [f"2026-08-{d:02d}" for d in range(10, 22)]  # 12 consecutive
        chunks = ingest_scoreboards._range_chunks(days, max_days=5)
        assert [len(c) for c in chunks] == [5, 5, 2]

    def test_unsorted_input_is_sorted(self):
        import ingest_scoreboards
        # Sorted first, then split at the gap (10-11 vs 14).
        assert ingest_scoreboards._range_chunks(
            ["2026-08-14", "2026-08-10", "2026-08-11"]) == [
            ["2026-08-10", "2026-08-11"],
            ["2026-08-14"]]


class TestFetchRangeChunk:
    def test_saves_each_bucketed_day(self, monkeypatch):
        import ingest_scoreboards
        written = []

        def _fake_games_by_day(league, start, end):
            return ({
                "2026-08-10": [{"game_id": "1"}],
                "2026-08-11": [{"game_id": "2"}, {"game_id": "3"}],
            }, 3)

        def _fake_save(league, day, games, source="espn"):
            written.append((day, len(games)))
            return len(games)

        monkeypatch.setattr(ingest_scoreboards.espn, "games_by_day",
                            _fake_games_by_day)
        monkeypatch.setattr(ingest_scoreboards.espn, "scoreboard_raw_range",
                            lambda *a, **k: {"leagues": []})
        monkeypatch.setattr(scoreboard_store, "save", _fake_save)
        monkeypatch.setattr(league_activity, "record_from_payload",
                            lambda *a, **k: True)

        total, error = ingest_scoreboards._fetch_range_chunk(
            "mlb", ["2026-08-10", "2026-08-11"], verbose=False)
        assert error is None
        assert total == 3
        assert written == [("2026-08-10", 1), ("2026-08-11", 2)]

    def test_a_capped_chunk_is_split_and_retried(self, monkeypatch):
        import ingest_scoreboards
        import ingest_scoreboards as mod
        calls = []

        def _fake_games_by_day(league, start, end):
            calls.append((start, end))
            if start == "2026-08-10" and end == "2026-08-14":
                # A response at the ceiling: the tail was dropped.
                many = [{"game_id": f"x{i}"} for i in range(100)]
                return {"2026-08-10": many}, 100
            # The halves are complete. The split is len//2 = 2, so the first
            # half is [10, 11] and the second [12, 13, 14].
            if start == "2026-08-10":
                return ({"2026-08-10": [{"game_id": "a"}],
                         "2026-08-11": [{"game_id": "b"}]}, 2)
            return ({"2026-08-12": [{"game_id": "c"}],
                     "2026-08-13": [{"game_id": "d"}],
                     "2026-08-14": [{"game_id": "e"}]}, 3)

        monkeypatch.setattr(mod.espn, "games_by_day", _fake_games_by_day)
        monkeypatch.setattr(mod.espn, "scoreboard_raw_range",
                            lambda *a, **k: {"leagues": []})
        monkeypatch.setattr(scoreboard_store, "save",
                            lambda league, day, games, source="espn": len(games))
        monkeypatch.setattr(league_activity, "record_from_payload",
                            lambda *a, **k: True)

        total, error = ingest_scoreboards._fetch_range_chunk(
            "mlb", [f"2026-08-{d:02d}" for d in range(10, 15)], verbose=False)
        assert error is None
        assert total == 5
        # The full window was tried, hit the ceiling, and both halves refetched.
        assert len(calls) == 3

    def test_a_failed_range_reports_an_error(self, monkeypatch):
        import ingest_scoreboards
        import ingest_scoreboards as mod

        def _boom(*a, **k):
            raise RuntimeError("host refusing")

        monkeypatch.setattr(mod.espn, "games_by_day", _boom)
        total, error = ingest_scoreboards._fetch_range_chunk(
            "mlb", ["2026-08-10"], verbose=False)
        assert total == 0
        assert error is not None and "RuntimeError" in error

    def test_a_chunk_wide_empty_response_does_not_retire_the_days(
            self, monkeypatch):
        """An empty range is NOT "no games" -- it must not write empties.

        Tennis answers the range form with `events: []` while its per-day
        form answers, and nothing detects a new league that does the same.
        If an empty range were saved as authoritative, `needs_refresh` would
        retire each day forever with "day is over and published no games".
        The fallback to the per-day `_refresh` path resolves the ambiguity.
        """
        import ingest_scoreboards
        import ingest_scoreboards as mod
        per_day = []

        def _fake_games_by_day(league, start, end):
            return {}, 0

        def _fake_refresh(league, date, verbose=True):
            per_day.append((league, date))
            return 1, None

        monkeypatch.setattr(mod.espn, "games_by_day", _fake_games_by_day)
        monkeypatch.setattr(ingest_scoreboards, "_refresh", _fake_refresh)

        total, error = ingest_scoreboards._fetch_range_chunk(
            "mlb", ["2026-08-10", "2026-08-11"], verbose=False)
        assert error is None
        assert total == 2
        # The per-day fallback ran for every day in the chunk.
        assert per_day == [("mlb", "2026-08-10"), ("mlb", "2026-08-11")]
        # The days were never written as empty: they still want a fetch.
        wanted, reason = scoreboard_store.needs_refresh("mlb", "2026-08-10")
        assert wanted, f"empty range retired the day: {reason}"

    def test_a_single_day_at_the_cap_is_refused_not_retired(self, monkeypatch):
        """A 1-day chunk at the ~100-event ceiling must not be stored as final.

        The split guard only covers multi-day chunks. A single day at the
        ceiling is a truncated slate; storing it would make `needs_refresh`
        read "every game final" on a partial day. No league reaches this
        today (busiest NCAAF day held: 71 games; busiest MLB: 22), so the
        guard is a loud refusal that leaves the day un-retired.
        """
        import ingest_scoreboards
        import ingest_scoreboards as mod
        saved = []
        many = [{"game_id": f"x{i}",
                 "date": "2026-08-10T20:00:00+00:00", "state": "post"}
                for i in range(100)]

        def _fake_games_by_day(league, start, end):
            return {"2026-08-10": many}, 100

        def _fake_save(league, day, games, source="espn"):
            saved.append((day, len(games)))
            return len(games)

        monkeypatch.setattr(mod.espn, "games_by_day", _fake_games_by_day)
        monkeypatch.setattr(scoreboard_store, "save", _fake_save)

        total, error = ingest_scoreboards._fetch_range_chunk(
            "mlb", ["2026-08-10"], verbose=False)
        assert total == 0
        assert error is not None and "ceiling" in error
        assert saved == [], "a truncated single-day slate must not be stored"
        wanted, reason = scoreboard_store.needs_refresh("mlb", "2026-08-10")
        assert wanted, f"truncated slate retired the day: {reason}"


class TestRunBackfillRange:
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
             ]},
        ],
    }

    def _payload(self, league_block, events=()):
        return {"leagues": [league_block], "events": list(events)}

    def test_tennis_stays_per_day_and_others_use_ranges(self, monkeypatch):
        import ingest_scoreboards
        import ingest_scoreboards as mod
        range_calls = []
        per_day_calls = []

        # atp has no calendar -> plan asks everything (None verdicts).
        league_activity.record_from_payload(
            "nfl", self._payload(self.NFL_CALENDAR))

        def _fake_games_by_day(league, start, end):
            days = _days(start, end)
            range_calls.append((league, start, end))
            return {day: [{"game_id": day}] for day in days}, len(days)

        def _fake_refresh(league, date, verbose=True):
            per_day_calls.append((league, date))
            return 1, None

        def _days(start, end):
            s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
            out = []
            while s <= e:
                out.append(s.isoformat())
                s += dt.timedelta(days=1)
            return out

        monkeypatch.setattr(mod.espn, "games_by_day", _fake_games_by_day)
        monkeypatch.setattr(mod.espn, "scoreboard_raw_range",
                            lambda *a, **k: {"leagues": []})
        monkeypatch.setattr(mod.espn, "games", lambda *a, **k: [])
        monkeypatch.setattr(ingest_scoreboards, "_refresh", _fake_refresh)
        monkeypatch.setattr(scoreboard_store, "save",
                            lambda league, day, games, source="espn": len(games))
        monkeypatch.setattr(league_activity, "record_from_payload",
                            lambda *a, **k: True)
        monkeypatch.setattr(ingest_scoreboards, "_drain_stories",
                            lambda *a, **k: 0)

        status = ingest_scoreboards.run_backfill_range(
            ["nfl", "atp"], ["2026-08-13", "2026-08-14"], verbose=False)
        assert status == 0
        # NFL: one range request for both days. atp: two per-day requests.
        assert range_calls == [("nfl", "2026-08-13", "2026-08-14")]
        assert sorted(per_day_calls) == [("atp", "2026-08-13"),
                                         ("atp", "2026-08-14")]

    def test_dry_run_requests_nothing(self, monkeypatch):
        import ingest_scoreboards
        import ingest_scoreboards as mod
        fired = []

        monkeypatch.setattr(mod.espn, "games_by_day",
                            lambda *a, **k: fired.append(("games_by_day", a, k)))
        monkeypatch.setattr(ingest_scoreboards, "_refresh",
                            lambda *a, **k: fired.append(("_refresh", a, k)))

        status = ingest_scoreboards.run_backfill_range(
            ["mlb", "atp"], ["2026-08-13", "2026-08-14"], dry_run=True,
            verbose=False)
        assert status == 0
        assert fired == []


class TestEspnClientRange:
    def _payload(self, events):
        return {"leagues": [], "events": events}

    def _team_event(self, eid, ts, home, away, state="post"):
        return {
            "id": eid,
            "date": ts,
            "season": {"type": 2, "slug": "regular-season"},
            "competitions": [{
                "id": eid,
                "date": ts,
                "status": {"type": {"state": state, "completed": state == "post",
                                    "description": "Final" if state == "post" else "Scheduled"}},
                "competitors": [
                    {"homeAway": "home", "score": 3, "team": {"abbreviation": home}},
                    {"homeAway": "away", "score": 1, "team": {"abbreviation": away}},
                ],
            }],
        }

    def test_mlb_events_bucket_by_america_new_york_day(self, monkeypatch):
        import espn_client

        payload = self._payload([
            self._team_event("1", "2026-08-15T23:10Z", "CHC", "STL"),
            # 01:00Z on the 16th is still the evening of the 15th in the US.
            self._team_event("2", "2026-08-16T01:00Z", "LAD", "SF"),
            self._team_event("3", "2026-08-16T23:00Z", "NYY", "BOS"),
        ])
        monkeypatch.setattr(espn_client, "_get", lambda url, ttl=20: payload)
        by_day, raw_events = espn_client.games_by_day("mlb", "2026-08-15", "2026-08-16")
        assert raw_events == 3
        assert sorted(by_day) == ["2026-08-15", "2026-08-16"]
        assert [g["game_id"] for g in by_day["2026-08-15"]] == ["1", "2"]
        assert [g["game_id"] for g in by_day["2026-08-16"]] == ["3"]

    def test_tennis_refuses_ranges(self, monkeypatch):
        import espn_client
        fired = []
        monkeypatch.setattr(espn_client, "_get",
                            lambda url, ttl=20: fired.append(url))
        assert espn_client.games_by_day("atp", "2026-08-15", "2026-08-16") == ({}, 0)
        assert fired == [], "tennis must not even issue the range request"

    def test_empty_range_returns_empty(self, monkeypatch):
        import espn_client
        monkeypatch.setattr(espn_client, "_get",
                            lambda url, ttl=20: {"leagues": [], "events": []})
        assert espn_client.games_by_day("mlb", "2026-08-15", "2026-08-16") == ({}, 0)


class TestSlateDayRule:
    def test_us_league_uses_new_york_date(self):
        import espn_client
        # 01:00Z on the 16th -> the 15th in New York (EDT).
        assert espn_client._slate_day("mlb", "2026-08-16T01:00Z") == "2026-08-15"
        # A mid-afternoon ET game stays on its own day.
        assert espn_client._slate_day("mlb", "2026-08-15T20:00Z") == "2026-08-15"

    def test_tennis_uses_utc_date(self):
        import espn_client
        assert espn_client._slate_day("atp", "2026-08-16T00:10Z") == "2026-08-16"

    def test_winter_game_respects_est(self):
        import espn_client
        # November 2026: EST is UTC-5, so 01:00Z is still Nov 14, not Nov 15.
        assert espn_client._slate_day("nfl", "2026-11-15T01:00Z") == "2026-11-14"

    def test_dst_boundary_is_honoured(self):
        import espn_client
        # Second Sunday of March 2026 is the 8th; DST begins at 07:00Z (2am EST).
        # 06:59Z is EST (UTC-5) -> March 8; 07:01Z is EDT (UTC-4) -> March 8.
        assert espn_client._slate_day("mlb", "2026-03-08T06:59Z") == "2026-03-08"
        assert espn_client._slate_day("mlb", "2026-03-08T07:01Z") == "2026-03-08"
        # First Sunday of November 2026 is the 1st; DST ends at 06:00Z (2am EDT).
        # 03:30Z is still EDT (UTC-4) -> 23:30 on Oct 31. 06:30Z is EST
        # (UTC-5) -> 01:30 on Nov 1. The offset flip changes the calendar day.
        assert espn_client._slate_day("mlb", "2026-11-01T03:30Z") == "2026-10-31"
        assert espn_client._slate_day("mlb", "2026-11-01T06:30Z") == "2026-11-01"
