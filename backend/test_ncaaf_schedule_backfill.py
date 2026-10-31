import datetime as dt
from unittest import mock

import pytest

import ingest_scoreboards as ingest
import scoreboard_store


PHASES = [
    {"season_type": 2, "weeks": [{"start_time": "2026-10-19T07:00Z", "end_time": "2026-10-26T06:59Z"}]},
    {"season_type": 3, "weeks": [{"start_time": "2026-12-18T08:00Z", "end_time": "2026-12-20T07:59Z"}]},
]
TODAY = dt.date(2026, 10, 24)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("LP_DB_PATH", str(tmp_path / "picks.db"))
    scoreboard_store.init()


def placeholder_games(league, day):
    # Postseason days carry TBD placeholders; regular-season days here have no games.
    if day > "2026-10-24":
        return [{"game_id": "tbd-" + day, "date": day + "T19:00Z", "season_type": 3, "state": "pre"}]
    return []


def asked(games_mock):
    return [call.args[1] for call in games_mock.call_args_list]


def test_calendar_days_are_every_day_inside_each_published_window(db):
    with mock.patch.object(ingest.espn, "football_schedule_weeks", return_value=PHASES):
        days = ingest.ncaaf_calendar_days(today=TODAY)

    assert days[0] == "2026-10-19"
    assert days[-1] == "2026-12-20"
    assert len(days) == 8 + 3


def test_the_calendar_is_asked_for_once_a_day(db):
    with mock.patch.object(ingest.espn, "football_schedule_weeks", return_value=PHASES) as catalog:
        ingest.ncaaf_calendar_days(today=TODAY)
        ingest.ncaaf_calendar_days(today=TODAY)
        ingest.ncaaf_calendar_days(today=TODAY + dt.timedelta(days=1))

    assert catalog.call_count == 2


def test_january_reads_the_season_that_started_the_year_before(db):
    with mock.patch.object(ingest.espn, "football_schedule_weeks", return_value=PHASES) as catalog:
        ingest.ncaaf_calendar_days(today=dt.date(2027, 1, 5))

    catalog.assert_called_once_with("ncaaf", 2026)


def test_each_run_reads_only_the_next_unread_days(db):
    with mock.patch.object(ingest.espn, "football_schedule_weeks", return_value=PHASES), \
         mock.patch.object(ingest.espn, "games", side_effect=placeholder_games) as games:
        assert ingest.backfill_ncaaf_schedule(today=TODAY, limit=3, verbose=False) == []
        assert asked(games) == ["2026-10-19", "2026-10-20", "2026-10-21"]

        assert ingest.backfill_ncaaf_schedule(today=TODAY, limit=3, verbose=False) == []
        assert asked(games)[3:] == ["2026-10-22", "2026-10-23", "2026-10-24"]

    assert scoreboard_store.read("ncaaf", "2026-10-19") is not None
    assert scoreboard_store.read("ncaaf", "2026-10-19")["games"] == []


def test_a_day_already_read_is_not_asked_again(db):
    scoreboard_store.save("ncaaf", "2026-10-22",
                          [{"game_id": "x", "date": "2026-10-22T19:00Z", "state": "post"}])

    with mock.patch.object(ingest.espn, "football_schedule_weeks", return_value=PHASES), \
         mock.patch.object(ingest.espn, "games", side_effect=placeholder_games) as games:
        ingest.backfill_ncaaf_schedule(today=TODAY, limit=100, verbose=False)

    assert "2026-10-22" not in asked(games)
    assert "2026-10-19" in asked(games)


def test_a_failed_day_is_not_stored_so_the_next_run_asks_again(db):
    def flaky(league, day):
        if day == "2026-10-19":
            raise ConnectionError("espn down")
        return placeholder_games(league, day)

    with mock.patch.object(ingest.espn, "football_schedule_weeks", return_value=PHASES), \
         mock.patch.object(ingest.espn, "games", side_effect=flaky):
        failures = ingest.backfill_ncaaf_schedule(today=TODAY, limit=2, verbose=False)

    assert [day for day, _ in failures] == ["2026-10-19"]
    assert scoreboard_store.read("ncaaf", "2026-10-19") is None
    assert scoreboard_store.read("ncaaf", "2026-10-20") is not None

    with mock.patch.object(ingest.espn, "football_schedule_weeks", return_value=PHASES), \
         mock.patch.object(ingest.espn, "games", side_effect=placeholder_games) as games:
        assert ingest.backfill_ncaaf_schedule(today=TODAY, limit=1, verbose=False) == []

    assert asked(games) == ["2026-10-19"]
    assert scoreboard_store.read("ncaaf", "2026-10-19") is not None
