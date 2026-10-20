"""Shadow forecasts: the replay rule, the forecast formulas, and the write behaviour (frozen, idempotent, no replace)."""
import datetime as dt
import json
import math
import sqlite3

import pytest

import tennis_shadow as shadow

LOCKED_AT = dt.datetime(2026, 10, 20, 4, 30, tzinfo=dt.timezone.utc)
START = dt.datetime(2026, 10, 20, 5, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def con(tmp_path):
    connection = sqlite3.connect(tmp_path / "shadow.db")
    connection.row_factory = sqlite3.Row
    connection.executescript("""
      CREATE TABLE tennis_atp_matches(
        tourney_id TEXT, tourney_date INTEGER, surface TEXT, winner_id INTEGER, loser_id INTEGER,
        match_num INTEGER, tourney_level TEXT, best_of INTEGER, score TEXT
      );
      CREATE TABLE tennis_model_locks(
        league TEXT NOT NULL, game_date TEXT NOT NULL, game_id TEXT NOT NULL,
        start_time TEXT NOT NULL, locked_at TEXT NOT NULL, projection TEXT NOT NULL,
        model_version TEXT, PRIMARY KEY(league, game_id)
      );
    """)
    shadow.ensure_table(connection)
    yield connection
    connection.close()


def _match(tournament="315", home="1", away="2", game_id="g1"):
    return {
        "gameId": game_id, "startTime": START.isoformat(), "home": "Home Player", "away": "Away Player",
        "tournamentId": tournament,
        "identity": {"home": {"sackmann_player_id": home}, "away": {"sackmann_player_id": away}},
    }


def _history(con, rows):
    con.executemany(
        "INSERT INTO tennis_atp_matches VALUES(?,?,?,?,?,?,?,?,?)",
        [("T", date, surface, winner, loser, n, "M", 3, "6-4 6-4") for n, (date, surface, winner, loser) in enumerate(rows)],
    )


def test_same_date_rows_do_not_inform_each_other(con):
    _history(con, [(20000101, "Hard", 1, 2), (20000101, "Hard", 3, 4)])
    global_r, surface_r = shadow.ratings_before(con, "atp", 20000102)
    # Both matches on the date are rated from 1500 and each moves by K/2 for the winner.
    assert global_r["1"] == pytest.approx(1516.0)
    assert global_r["2"] == pytest.approx(1484.0)
    assert global_r["3"] == pytest.approx(1516.0)
    assert surface_r[("1", "Hard")] == pytest.approx(1516.0)


def test_ratings_only_use_matches_before_the_cutoff(con):
    _history(con, [(20000101, "Hard", 1, 2), (20000105, "Hard", 1, 2)])
    global_r, _ = shadow.ratings_before(con, "atp", 20000105)
    assert global_r["1"] == pytest.approx(1516.0)  # the 20000105 match is not yet known on 20000105


def test_rows_without_surface_move_nothing(con):
    con.execute("INSERT INTO tennis_atp_matches VALUES('T', 20000101, NULL, 1, 2, 1, 'M', 3, '6-4 6-4')")
    global_r, surface_r = shadow.ratings_before(con, "atp", 20000102)
    assert global_r == {} or all(v == 1500.0 for v in global_r.values())
    assert surface_r == {}


def test_forecast_formulas_match_the_rolling_definitions(con):
    global_r = {"1": 1516.0, "2": 1484.0}
    surface_r = {("1", "Hard"): 1530.0, ("2", "Hard"): 1470.0}
    out = shadow.forecasts(global_r, surface_r, "1", "2", "Hard")
    m1 = 1.0 / (1.0 + 10 ** ((1484.0 - 1516.0) / 400.0))
    scale = math.log(10.0) / 400.0
    p_g = 1.0 / (1.0 + math.exp(-(32.0 * scale)))
    p_s = 1.0 / (1.0 + math.exp(-(60.0 * scale)))
    m2 = 1.0 / (1.0 + math.exp(-(0.5 * (math.log(p_g / (1 - p_g)) + math.log(p_s / (1 - p_s))))))
    assert out[shadow.M1_VERSION] == pytest.approx(m1, abs=1e-12)
    assert out[shadow.M2_VERSION] == pytest.approx(m2, abs=1e-12)


def test_unmapped_surface_falls_back_to_global_elo(con):
    global_r = {"1": 1516.0, "2": 1484.0}
    out = shadow.forecasts(global_r, {}, "1", "2", None)
    assert out[shadow.M2_VERSION] == pytest.approx(out[shadow.M1_VERSION], abs=1e-9)


def test_write_gives_two_distinct_frozen_rows_and_is_idempotent(con):
    _history(con, [(20000101, "Hard", 1, 2)])
    replays = {}
    assert shadow.write_shadow_locks(con, "atp", _match(), START, LOCKED_AT, replays) == 2
    assert shadow.write_shadow_locks(con, "atp", _match(), START, LOCKED_AT, replays) == 0
    rows = con.execute("SELECT model_version, status, locked_at, projection FROM tennis_shadow_locks ORDER BY model_version").fetchall()
    assert [row["model_version"] for row in rows] == sorted(shadow.VERSIONS)
    assert {row["status"] for row in rows} == {"locked"}
    assert {row["locked_at"] for row in rows} == {LOCKED_AT.isoformat()}
    projection = json.loads(rows[0]["projection"])
    assert projection["surfaceSource"] == "event_id"
    assert projection["cutoffDate"] == "2026-10-20"


def test_existing_row_is_never_replaced(con):
    con.execute(
        "INSERT INTO tennis_shadow_locks VALUES('atp','g1',?,?,?,?,'locked',?)",
        (shadow.M2_VERSION, "2026-10-20", START.isoformat(), LOCKED_AT.isoformat(), json.dumps({"probability": 0.9})),
    )
    shadow.write_shadow_locks(con, "atp", _match(), START, LOCKED_AT, {})
    kept = con.execute("SELECT projection FROM tennis_shadow_locks WHERE model_version=?", (shadow.M2_VERSION,)).fetchone()
    assert json.loads(kept[0]) == {"probability": 0.9}


def test_unresolved_identity_writes_missing_rows_not_forecasts(con):
    match = _match(home=None)
    assert shadow.write_shadow_locks(con, "atp", match, START, LOCKED_AT, {}) == 2
    rows = con.execute("SELECT status, projection FROM tennis_shadow_locks").fetchall()
    assert {row["status"] for row in rows} == {"missing"}
    assert all(json.loads(row["projection"])["reason"] == "identity_unresolved" for row in rows)


def test_unmapped_event_is_recorded_as_unmapped(con):
    _history(con, [(20000101, "Hard", 1, 2)])
    shadow.write_shadow_locks(con, "atp", _match(tournament="999"), START, LOCKED_AT, {})
    projection = json.loads(con.execute(
        "SELECT projection FROM tennis_shadow_locks WHERE model_version=?", (shadow.M2_VERSION,)).fetchone()[0])
    assert projection["surfaceSource"] == "unmapped"
    assert projection["surface"] is None


def test_surface_resolves_by_major_name_when_the_event_id_is_unknown(con):
    _history(con, [(20000101, "Hard", 1, 2)])
    match = dict(_match(tournament="1"), event="Roland Garros")
    shadow.write_shadow_locks(con, "atp", match, START, LOCKED_AT, {})
    projection = json.loads(con.execute(
        "SELECT projection FROM tennis_shadow_locks WHERE model_version=?", (shadow.M2_VERSION,)).fetchone()[0])
    assert projection["surface"] == "Clay"
    assert projection["surfaceSource"] == "major_name"


def test_served_lock_table_is_not_touched(con):
    con.execute("INSERT INTO tennis_model_locks VALUES('atp','2026-10-20','g1',?,?,'{}','tennis-global-surface-elo-blend-v2')",
                (START.isoformat(), LOCKED_AT.isoformat()))
    before = con.execute("SELECT * FROM tennis_model_locks ORDER BY game_id").fetchall()
    _history(con, [(20000101, "Hard", 1, 2)])
    shadow.write_shadow_locks(con, "atp", _match(), START, LOCKED_AT, {})
    assert con.execute("SELECT * FROM tennis_model_locks ORDER BY game_id").fetchall() == before
