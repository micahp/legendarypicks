"""Tennis grades require publisher finality and keep the exact result snapshot."""
import datetime as dt
import hashlib
import json
import sqlite3

import pytest

import grade_tennis_model as grader


def _game(*, completed=True, status="Final", home_winner=True, away_winner=False):
    return {
        "completed": completed,
        "status": status,
        "home": {
            "name": "Home Player", "score": "2", "winner": home_winner,
            "sets": [6, 4, 6],
        },
        "away": {
            "name": "Away Player", "score": "1", "winner": away_winner,
            "sets": [4, 6, 3],
        },
    }


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE scoreboard_snapshots(
        league TEXT, game_date TEXT, game_id TEXT, payload TEXT, state TEXT,
        start_time TEXT, fetched_at TEXT, source TEXT,
        PRIMARY KEY(league,game_date,game_id)
      );
      CREATE TABLE tennis_model_locks(
        league TEXT, game_id TEXT, start_time TEXT, projection TEXT,
        PRIMARY KEY(league,game_id)
      );
      -- Exercise the additive migration used by the existing dev schema.
      CREATE TABLE tennis_model_grades(
        league TEXT NOT NULL, game_id TEXT NOT NULL, winner TEXT NOT NULL,
        total_games_error REAL, graded_at TEXT NOT NULL, result_source TEXT,
        result_game_date TEXT, result_fetched_at TEXT, result_payload_sha256 TEXT,
        PRIMARY KEY(league,game_id)
      );
      CREATE TRIGGER tennis_model_grades_immutable_update
      BEFORE UPDATE ON tennis_model_grades BEGIN
        SELECT RAISE(ABORT, 'tennis model grades are immutable');
      END;
      CREATE TRIGGER tennis_model_grades_immutable_delete
      BEFORE DELETE ON tennis_model_grades BEGIN
        SELECT RAISE(ABORT, 'tennis model grades are immutable');
      END;
      INSERT INTO tennis_model_locks VALUES
        ('atp','match-1','2026-10-16T10:00:00+00:00',
         '{"projectedWinner":"Home Player","totalGames":28}');
    """)
    return con


def _snapshot(con, game, *, game_date="2026-10-16", fetched_at="2026-10-16T15:00:00+00:00",
              state="post"):
    payload = json.dumps(game, sort_keys=True)
    con.execute(
        "INSERT INTO scoreboard_snapshots VALUES(?,?,?,?,?,?,?,?)",
        ("atp", game_date, "match-1", payload, state, "2026-10-16T10:00:00+00:00",
         fetched_at, "espn"),
    )
    return payload


def test_publisher_completed_bit_gates_a_post_state_score():
    con = _db()
    _snapshot(con, _game(completed=False))

    report = grader.grade_final_matches(con, dt.datetime(2026, 10, 16, 20, tzinfo=dt.timezone.utc))

    assert report["graded"] == 0
    assert report["missing_result"] == 1
    assert con.execute("SELECT COUNT(*) FROM tennis_model_grades").fetchone()[0] == 0


def test_latest_snapshot_controls_finality_and_cannot_rewrite_a_grade():
    con = _db()
    original_payload = _snapshot(con, _game())

    first = grader.grade_final_matches(con, dt.datetime(2026, 10, 16, 20, tzinfo=dt.timezone.utc))
    grade, = con.execute("SELECT * FROM tennis_model_grades").fetchall()
    expected_hash = hashlib.sha256(original_payload.encode("utf-8")).hexdigest()
    assert first["graded"] == 1
    assert (grade["result_source"], grade["result_game_date"], grade["result_fetched_at"],
            grade["result_payload_sha256"]) == (
                "espn", "2026-10-16", "2026-10-16T15:00:00+00:00", expected_hash,
            )

    revised_payload = json.dumps(_game(home_winner=False, away_winner=True), sort_keys=True)
    con.execute(
        "UPDATE scoreboard_snapshots SET payload=?,fetched_at=? WHERE league='atp' AND game_id='match-1'",
        (revised_payload, "2026-10-16T16:00:00+00:00"),
    )
    second = grader.grade_final_matches(con, dt.datetime(2026, 10, 16, 21, tzinfo=dt.timezone.utc))
    saved, = con.execute("SELECT * FROM tennis_model_grades").fetchall()
    assert second["graded"] == 0
    assert saved["winner"] == "correct"
    assert saved["result_payload_sha256"] == expected_hash
    with pytest.raises(sqlite3.IntegrityError, match="grades are immutable"):
        con.execute("UPDATE tennis_model_grades SET winner='incorrect'")
    with pytest.raises(sqlite3.IntegrityError, match="grades are immutable"):
        con.execute("DELETE FROM tennis_model_grades")


def test_newer_nonfinal_snapshot_prevents_grading_an_older_final():
    con = _db()
    _snapshot(con, _game())
    _snapshot(con, _game(completed=False), game_date="2026-10-17",
              fetched_at="2026-10-17T08:00:00+00:00", state="in")

    report = grader.grade_final_matches(con, dt.datetime(2026, 10, 17, 9, tzinfo=dt.timezone.utc))

    assert report["graded"] == 0
    assert con.execute("SELECT COUNT(*) FROM tennis_model_grades").fetchone()[0] == 0


def test_retirement_uses_official_winner_and_does_not_grade_partial_total():
    con = _db()
    payload = _snapshot(con, _game(status="Retired", home_winner=False, away_winner=True))

    report = grader.grade_final_matches(con, dt.datetime(2026, 10, 16, 20, tzinfo=dt.timezone.utc))

    grade, = con.execute("SELECT winner,total_games_error,result_payload_sha256 "
                         "FROM tennis_model_grades").fetchall()
    assert report["graded"] == 1
    assert grade["winner"] == "incorrect"
    assert grade["total_games_error"] is None
    assert grade["result_payload_sha256"] == hashlib.sha256(payload.encode()).hexdigest()
