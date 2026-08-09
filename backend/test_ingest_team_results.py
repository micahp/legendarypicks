"""What ingest_team_results must record, against a fabricated ESPN document.

These assert the four things the ingest was silently not doing for 3,305 MLB
rows: the season, the status, the publisher, and both halves of a game.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _event(game_id, date, home, away, home_score, away_score, season=2026,
           season_type="2", completed=True):
    return {
        "id": game_id,
        "date": date,
        "season": {"year": season},
        "seasonType": {"id": season_type},
        "competitions": [{
            "status": {"type": {"completed": completed}},
            "competitors": [
                {"team": {"abbreviation": home}, "homeAway": "home",
                 "score": {"value": home_score}, "winner": home_score > away_score},
                {"team": {"abbreviation": away}, "homeAway": "away",
                 "score": {"value": away_score}, "winner": away_score > home_score},
            ],
        }],
    }


@pytest.fixture
def ingest_against(tmp_path, monkeypatch):
    """Run the ingest against a temp DB and a fake ESPN, return the rows."""
    db = tmp_path / "t.db"

    def run(schedules, league="mlb"):
        monkeypatch.setenv("LP_DB_PATH", str(db))
        import importlib
        import ingest_team_results
        importlib.reload(ingest_team_results)

        teams_doc = {"sports": [{"leagues": [{"teams": [
            {"team": {"abbreviation": ab.upper()}} for ab in schedules
        ]}]}]}

        def fake_get(url, ttl=None):
            if url.endswith("/teams"):
                return teams_doc
            ab = url.rsplit("/teams/", 1)[1].split("/")[0]
            return {"events": schedules[ab]}

        monkeypatch.setattr(ingest_team_results, "_get", fake_get)
        ingest_team_results.ingest(league)

        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM team_game_results ORDER BY game_id, team")]
        con.close()
        return rows

    return run


def test_season_status_and_source_are_recorded(ingest_against):
    """The four columns that were NULL on every MLB row ever written."""
    rows = ingest_against({"nyy": [_event("1", "2026-04-01T23:05Z", "NYY", "BOS", 5, 3)],
                           "bos": []})
    assert rows, "the ingest wrote nothing"
    for row in rows:
        assert row["season"] == 2026
        assert row["status"] == "completed"
        assert row["source"] == "espn_site_api:team_schedule"
        assert row["run_id"] and row["run_id"].startswith("mlb-team-results-")


def test_both_teams_are_written_from_one_schedule(ingest_against):
    """The orphan defect: 401816347 existed for ARI and not for CLE.

    Only NYY's document carries the game. Both rows must still land, because a
    game's completeness cannot be allowed to depend on which team's schedule the
    fetch loop happened to reach before the game ended.
    """
    rows = ingest_against({"nyy": [_event("1", "2026-04-01T23:05Z", "NYY", "BOS", 5, 3)],
                           "bos": []})
    assert sorted(r["team"] for r in rows) == ["BOS", "NYY"]
    nyy = next(r for r in rows if r["team"] == "NYY")
    bos = next(r for r in rows if r["team"] == "BOS")
    assert (nyy["score_for"], nyy["score_against"], nyy["win"]) == (5.0, 3.0, 1)
    assert (bos["score_for"], bos["score_against"], bos["win"]) == (3.0, 5.0, 0)
    assert nyy["opponent"] == "BOS" and bos["opponent"] == "NYY"


def test_a_game_on_both_schedules_is_written_once(ingest_against):
    """Two documents, one game, still exactly two rows."""
    event = _event("1", "2026-04-01T23:05Z", "NYY", "BOS", 5, 3)
    rows = ingest_against({"nyy": [event], "bos": [event]})
    assert len(rows) == 2


def test_spring_training_is_not_a_regular_season_game(ingest_against):
    """seasonType 1 is Spring Training. It must not enter as a result.

    Measured 2026-08-03: ESPN publishes 451 type-1 MLB events for 2026. Nothing
    in the old code excluded them — the endpoint simply did not return any that
    day, which is the publisher's choice and not a filter.
    """
    rows = ingest_against({"nyy": [
        _event("1", "2026-03-01T20:05Z", "NYY", "BOS", 5, 3, season_type="1"),
        _event("2", "2026-04-01T23:05Z", "NYY", "BOS", 4, 2, season_type="2"),
    ], "bos": []})
    assert {r["game_id"] for r in rows} == {"2"}


def test_an_unfinished_game_is_not_a_result(ingest_against):
    rows = ingest_against({"nyy": [
        _event("1", "2026-04-01T23:05Z", "NYY", "BOS", 2, 1, completed=False),
    ], "bos": []})
    assert rows == []


def test_an_unmapped_season_type_is_skipped_not_guessed(ingest_against):
    """Type 4 is Off Season and publishes no events. A row claiming it is a
    defect, and `normalize_game_type` raising is the correct outcome — the
    ingest must drop it rather than fall back to REG."""
    rows = ingest_against({"nyy": [
        _event("1", "2026-12-01T20:05Z", "NYY", "BOS", 5, 3, season_type="4"),
    ], "bos": []})
    assert rows == []


def test_refuses_to_double_a_season_keyed_in_another_vocabulary(ingest_against, tmp_path):
    """A season already holding nflverse-style game ids must not gain ESPN
    event-id rows beside them.

    This is the 285 -> 557 bug, as a regression test. The target season is
    pre-seeded with a foreign-vocabulary row; the ingest must refuse to write
    rather than INSERT OR REPLACE its way past the vocabulary boundary.
    """
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE team_game_results(
        league TEXT NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL,
        game_date TEXT, opponent TEXT, home_away TEXT,
        score_for REAL, score_against REAL, win INTEGER,
        ingested_at TEXT DEFAULT (datetime('now')),
        season INTEGER, status TEXT, source TEXT, run_id TEXT,
        PRIMARY KEY(league, game_id, team))""")
    con.execute(
        "INSERT INTO team_game_results(league, game_id, team, season, status, source)"
        " VALUES ('nfl', '2026_01_BAL_KC', 'BAL', 2026, 'completed', 'nflverse')")
    con.commit()
    con.close()

    rows = ingest_against({"bal": [
        _event("401772718", "2026-09-10T23:05Z", "BAL", "KC", 24, 17, season=2026),
    ], "kc": []}, league="nfl")
    # Nothing landed: the only row is the pre-seeded foreign one.
    assert [r["game_id"] for r in rows] == ["2026_01_BAL_KC"]
