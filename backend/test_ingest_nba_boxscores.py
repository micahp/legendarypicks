"""nba.com player box scores: a box is stored only when its points add up to the final score."""
import sqlite3

import pytest

import ingest_nba_boxscores as boxes


def _player(person_id, points, minutes="12:00", comment=None):
    return {"personId": person_id, "firstName": "First", "familyName": f"Player{person_id}", "position": "G",
            "comment": comment,
            "statistics": {"points": points, "minutes": minutes, "reboundsTotal": 1, "assists": 2, "steals": 0,
                           "blocks": 0, "turnovers": 1, "fieldGoalsMade": 3, "fieldGoalsAttempted": 6,
                           "threePointersMade": 1, "threePointersAttempted": 2, "freeThrowsMade": 0,
                           "freeThrowsAttempted": 0, "plusMinusPoints": 2}}


def _game(home_points, away_points):
    return {
        "homeTeam": {"score": home_points, "players": [
            _player(1, home_points), _player(2, 0, "", "Inactive - Injury/Illness")]},
        "awayTeam": {"score": away_points, "players": [_player(3, away_points)]},
    }


def test_every_listed_player_is_a_row_and_an_inactive_player_is_marked_not_played():
    rows = boxes.rows_for_game("G1", 2027, _game(10, 7), "POR", "PHX")
    assert len(rows) == 3
    inactive = rows[1]
    assert inactive["played"] == 0 and inactive["minutes"] is None
    assert inactive["comment"] == "Inactive - Injury/Illness"
    away = rows[2]
    assert (away["team"], away["opponent"], away["home_away"], away["points"]) == ("PHX", "POR", "away", 7)


def test_a_box_whose_points_do_not_add_up_to_the_final_is_refused():
    game = _game(10, 7)
    game["awayTeam"]["score"] = 8
    with pytest.raises(boxes.BoxScoreError, match="PHX players total 7 points, the final is 8"):
        boxes.rows_for_game("G1", 2027, game, "POR", "PHX")


def test_storing_a_game_twice_leaves_one_row_per_player():
    connection = sqlite3.connect(":memory:")
    connection.execute(boxes.SCHEMA)
    rows = boxes.rows_for_game("G1", 2027, _game(10, 7), "POR", "PHX")
    boxes.store_game(connection, "G1", rows)
    boxes.store_game(connection, "G1", rows)
    assert connection.execute(f"SELECT COUNT(*) FROM {boxes.TABLE}").fetchone()[0] == 3


def test_dry_run_writes_nothing_and_a_missing_page_is_reported(tmp_path):
    path = tmp_path / "picks.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE nba_schedule (game_id TEXT, season INTEGER, season_type TEXT, status INTEGER, "
                       "game_date TEXT, home_team TEXT, away_team TEXT)")
    connection.executemany("INSERT INTO nba_schedule VALUES (?,2027,'REG',3,?,?,?)",
                           [("G1", "2026-10-21", "POR", "PHX"), ("G2", "2026-10-22", "NY", "BOS")])
    connection.commit()
    connection.close()
    pages = {"G1": _game(10, 7), "G2": None}

    result = boxes.refresh(str(path), 2027, apply=False, fetch_game=pages.get, log=lambda *a: None)
    assert result["failures"] == ["G2: nba.com has no game page"]
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT 1 FROM sqlite_master WHERE name=?", (boxes.TABLE,)).fetchone() is None
    connection.close()

    result = boxes.refresh(str(path), 2027, apply=True, fetch_game=pages.get, log=lambda *a: None)
    connection = sqlite3.connect(path)
    assert connection.execute(f"SELECT COUNT(*) FROM {boxes.TABLE}").fetchone()[0] == 3
    connection.close()
    assert len(result["failures"]) == 1
