import datetime as dt
import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import _core
import core_stories
from routers import game_extras
from story_engine import LEAGUE_TEAM_NAMES
import story_engine_audit
import story_engine_runtime


LEAGUE = "nba"
SEASON = 2027


def test_record_audit_attributes_names_after_score_to_the_correct_team():
    cutoff = "2026-11-03T20:00:00Z"

    def rows(code, outcomes):
        result = []
        for index, outcome in enumerate(outcomes):
            won = outcome == "W"
            result.append({
                "id": f"{code}-{index}", "available_at": "2026-11-02T20:00:00Z",
                "date": f"2026-10-{index + 1:02d}", "for": 110 if won else 100,
                "against": 100 if won else 110,
            })
        return result

    pistons = rows("DET", "WWWWWWL")
    sixers = rows("PHI", "WWWWWWWL")
    facts = {
        "league": "nba", "as_of": cutoff,
        "teams": {"DET": {"evidence": pistons}, "PHI": {"evidence": sixers}},
    }
    selected = [
        {"kind": "record", "team": "DET", "description": "Detroit Pistons record 6-1",
         "evidence_ids": [row["id"] for row in pistons], "evidence": pistons},
        {"kind": "record", "team": "PHI", "description": "Philadelphia 76ers record 7-1",
         "evidence_ids": [row["id"] for row in sixers], "evidence": sixers},
    ]
    story = ("Two of the NBA's top four teams meet in Detroit, where the 6-1 Pistons "
             "host the 7-1 76ers.")

    assert story_engine_audit._record_and_streak_claims_match(story, facts, selected)
    assert story_engine_audit._record_and_streak_facts_recompute(selected, facts, cutoff)
    assert story_engine_audit._selected_rows_linked(selected, facts)
    tampered = [dict(fact, evidence=[dict(row) for row in fact["evidence"]]) for fact in selected]
    tampered[0]["evidence"][0]["for"] += 1
    assert not story_engine_audit._selected_rows_linked(tampered, facts)
    incomplete = [dict(selected[0], evidence=selected[0]["evidence"][:-1],
                       evidence_ids=selected[0]["evidence_ids"][:-1])]
    assert not story_engine_audit._record_and_streak_facts_recompute(incomplete, facts, cutoff)


def test_head_to_head_audit_recomputes_winner_score_and_date():
    away_row = {"id": "g1", "date": "2026-10-30", "available_at": "2026-10-30T20:00:00Z",
                "opponent": "DET", "for": 115, "against": 104}
    home_row = {"id": "g1", "date": "2026-10-30", "available_at": "2026-10-30T20:00:00Z",
                "opponent": "CHI", "for": 104, "against": 115}
    facts = {"away": "CHI", "home": "DET", "teams": {
        "CHI": {"evidence": [away_row]}, "DET": {"evidence": [home_row]},
    }}
    selected = [{"kind": "head_to_head", "evidence": [away_row, home_row]}]
    story = "Chicago has won three straight and already beat Detroit 115-104 on Oct. 30."

    assert story_engine_audit._head_to_head_claims_recompute(story, facts, selected)
    assert not story_engine_audit._head_to_head_claims_recompute(
        story.replace("115-104", "104-115"), facts, selected)
    assert not story_engine_audit._head_to_head_claims_recompute(
        story.replace("Oct. 30", "Oct. 29"), facts, selected)


def _iso(value):
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_db(path: Path):
    now = dt.datetime.now(dt.timezone.utc)
    old = now - dt.timedelta(hours=2)
    before = (now.date() - dt.timedelta(days=1)).isoformat()
    start = _iso(now + dt.timedelta(hours=10))
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE nba_schedule (
            game_id TEXT PRIMARY KEY, espn TEXT, season INTEGER, season_type TEXT,
            game_code TEXT, game_date TEXT, start_utc TEXT, away_team TEXT, home_team TEXT,
            away_score INTEGER, home_score INTEGER, label TEXT, sub_label TEXT,
            status INTEGER, status_text TEXT, source TEXT, ingested_at TEXT
        );
        CREATE TABLE nba_teams(team TEXT, team_name TEXT, season INTEGER);
        CREATE TABLE players(id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE player_game_logs(
            id INTEGER PRIMARY KEY, player_id TEXT, league TEXT, season INTEGER,
            game_id TEXT, game_date TEXT, team TEXT, stats TEXT, ingested_at TEXT, game_type TEXT
        );
        CREATE TABLE props(id INTEGER, game_id INTEGER, player_id TEXT, market TEXT, side TEXT, line REAL);
        CREATE TABLE prop_games(id INTEGER, league TEXT, espn_event_id TEXT);
        CREATE TABLE scoreboard_snapshots(
            league TEXT, game_id TEXT, state TEXT, payload TEXT, fetched_at TEXT, start_time TEXT
        );
    """)
    codes = list(LEAGUE_TEAM_NAMES[LEAGUE])
    con.executemany("INSERT INTO nba_teams(team,team_name,season) VALUES (?,?,?)",
                    [(code, LEAGUE_TEAM_NAMES[LEAGUE][code], SEASON) for code in codes])
    for index in range(0, len(codes), 2):
        away, home = codes[index:index + 2]
        con.execute(
            "INSERT INTO nba_schedule(game_id,espn,season,season_type,game_code,game_date,start_utc,"
            "away_team,home_team,away_score,home_score,source,ingested_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("R%02d" % index, "R%02d" % index, SEASON, "REG", "REG", before,
             None, away, home, 100, 110, "fixture-results", _iso(old)),
        )
    con.execute(
        "INSERT INTO nba_schedule(game_id,espn,season,season_type,game_code,game_date,start_utc,"
        "away_team,home_team,source,ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("2000000001", "2000000001", SEASON, "REG", "REG", now.date().isoformat(),
         start, "ATL", "BOS", "fixture-schedule", _iso(old)),
    )
    con.commit()
    con.close()
    return start


def _client(path, monkeypatch):
    monkeypatch.setattr(_core, "DB", str(path))
    monkeypatch.setenv("LP_DETERMINISTIC_STORY_ENGINE", "1")
    monkeypatch.setattr(_core, "_deepseek_chat", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("pregame deterministic path must not call a model")))
    app = FastAPI()
    app.include_router(game_extras.router)
    return TestClient(app, raise_server_exceptions=False)


def test_story_endpoint_uses_real_collector_audit_grade_and_cache(tmp_path, monkeypatch):
    path = tmp_path / "picks.db"
    _build_db(path)
    client = _client(path, monkeypatch)

    response = client.get("/api/game/nba/2000000001/story")
    assert response.status_code == 200
    result = response.json()
    assert result["story"] and result["generator"] == "deterministic"
    assert result["cached"] is False

    con = sqlite3.connect(path)
    history = con.execute(
        "SELECT story,quality_json,gate_status,score FROM game_story_deterministic_history "
        "WHERE league='nba' AND game_id='2000000001'").fetchone()
    assert history and history[0] == result["story"]
    quality = json.loads(history[1])
    assert set(quality["dimensions"]) == {
        "grounding", "headline", "players", "fan_voice", "freshness", "flow"}
    assert history[2] in {"eligible", "review"}
    assert history[3] is not None
    assert quality["independent_fact_audit_supplied"] is True
    assert quality["dimensions"]["grounding"]["checks"]["failed_checks"] == []
    legacy_table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='game_story'").fetchone()
    assert legacy_table is None or con.execute("SELECT COUNT(*) FROM game_story").fetchone()[0] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM game_story_deterministic_history WHERE game_id='2000000001'").fetchone()[0] == 1
    con.close()

    cached = client.get("/api/game/nba/2000000001/story").json()
    assert cached["story"] == result["story"] and cached["cached"] is True
    con = sqlite3.connect(path)
    assert con.execute(
        "SELECT COUNT(*) FROM game_story_deterministic_history WHERE game_id='2000000001'").fetchone()[0] == 1
    con.close()

    refreshed = client.get("/api/game/nba/2000000001/story?refresh=true").json()
    assert refreshed["story"] == result["story"] and refreshed["cached"] is False
    con = sqlite3.connect(path)
    revisions = con.execute(
        "SELECT generation_id FROM game_story_deterministic_history WHERE game_id='2000000001'"
    ).fetchall()
    assert len(revisions) == 2 and revisions[0][0] != revisions[1][0]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute(
            "UPDATE game_story_deterministic_history SET story='rewritten' WHERE game_id='2000000001'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("DELETE FROM game_story_deterministic_history WHERE game_id='2000000001'")
    con.rollback()
    assert con.execute(
        "SELECT COUNT(*) FROM game_story_deterministic_history WHERE game_id='2000000001'"
    ).fetchone()[0] == 2
    con.close()

    now = dt.datetime.now(dt.timezone.utc)
    con = sqlite3.connect(path)
    con.execute(
        "INSERT INTO nba_schedule(game_id,espn,season,season_type,game_code,game_date,start_utc,"
        "away_team,home_team,source,ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("2000000002", "2000000002", SEASON, "REG", "REG", now.date().isoformat(),
         _iso(now + dt.timedelta(hours=9)), "CHI", "DEN", "new-ingest", _iso(now)),
    )
    con.commit()
    con.close()
    new_game = client.get("/api/game/nba/2000000002/story").json()
    assert new_game["story"] and new_game["generator"] == "deterministic"
    con = sqlite3.connect(path)
    assert con.execute(
        "SELECT COUNT(*) FROM game_story_deterministic_history WHERE game_id='2000000002'").fetchone()[0] == 1
    con.close()


def test_missing_schedule_fails_closed_and_records_failure(tmp_path, monkeypatch):
    path = tmp_path / "picks.db"
    _build_db(path)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE game_story(league TEXT,game_id TEXT,story TEXT,generated_at TEXT)")
    con.execute("INSERT INTO game_story VALUES ('nba','8888888888','Saved legacy preview','2026-11-02 12:00:00')")
    con.commit()
    con.close()
    client = _client(path, monkeypatch)

    fallback = client.get("/api/game/nba/8888888888/story").json()
    assert fallback["story"] == "Saved legacy preview" and fallback["cached"] is True
    response = client.get("/api/game/nba/9999999999/story")
    assert response.status_code == 200
    assert response.json()["story"] is None
    assert response.json()["status"] == "failed"
    con = sqlite3.connect(path)
    failure = con.execute(
        "SELECT failure_type,detail FROM game_story_deterministic_failures "
        "WHERE game_id='9999999999'").fetchone()
    assert failure and failure[0] == "RuntimeError" and "no row" in failure[1]
    con.close()


def test_needs_audit_record_is_saved_but_not_published(tmp_path, monkeypatch):
    path = tmp_path / "picks.db"
    _build_db(path)
    monkeypatch.setattr(story_engine_runtime, "_quality_record", lambda *_: {
        "gate": "needs-audit", "score": 80, "hard_failures": [],
    })
    client = _client(path, monkeypatch)

    response = client.get("/api/game/nba/2000000001/story")
    assert response.status_code == 200
    assert response.json()["story"] is None
    assert response.json()["status"] == "needs-audit"
    con = sqlite3.connect(path)
    assert con.execute(
        "SELECT gate_status FROM game_story_deterministic_history WHERE game_id='2000000001'"
    ).fetchone()[0] == "needs-audit"
    assert con.execute(
        "SELECT COUNT(*) FROM game_story_deterministic WHERE game_id='2000000001'"
    ).fetchone()[0] == 0
    assert con.execute(
        "SELECT failure_type FROM game_story_deterministic_failures WHERE game_id='2000000001'"
    ).fetchone()[0] == "audit_incomplete"
    con.close()


def test_invalid_kickoff_fails_closed_without_model_fallback(tmp_path, monkeypatch):
    path = tmp_path / "picks.db"
    _build_db(path)
    con = sqlite3.connect(path)
    con.execute("UPDATE nba_schedule SET start_utc='invalid-time' WHERE game_id='2000000001'")
    con.commit()
    con.close()
    client = _client(path, monkeypatch)

    response = client.get("/api/game/nba/2000000001/story")
    assert response.status_code == 200
    assert response.json()["story"] is None
    assert response.json()["status"] == "failed"
    con = sqlite3.connect(path)
    failure = con.execute(
        "SELECT failure_type,detail FROM game_story_deterministic_failures WHERE game_id='2000000001'"
    ).fetchone()
    assert failure and failure[0] == "RuntimeError" and "kickoff" in failure[1]
    con.close()


def test_database_error_fails_closed_without_model_fallback(tmp_path, monkeypatch):
    path = tmp_path / "picks.db"
    _build_db(path)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE game_story(league TEXT,game_id TEXT,story TEXT,generated_at TEXT)")
    con.execute("INSERT INTO game_story VALUES ('nba','2000000001','Saved story before DB helper failure','2026-11-02 12:00:00')")
    con.commit()
    con.close()
    client = _client(path, monkeypatch)
    monkeypatch.setattr(_core, "_db", lambda: (_ for _ in ()).throw(
        sqlite3.OperationalError("database unavailable")))

    response = client.get("/api/game/nba/2000000001/story")
    assert response.status_code == 200
    assert response.json()["story"] == "Saved story before DB helper failure"
    assert response.json()["cached"] is True
    assert response.json()["status"] == "failed"
    con = sqlite3.connect(path)
    assert con.execute(
        "SELECT COUNT(*) FROM game_story_deterministic_failures WHERE game_id='2000000001'").fetchone()[0] == 1
    con.close()


def test_refresh_write_error_rolls_back_history_and_keeps_previous_story(tmp_path, monkeypatch):
    path = tmp_path / "picks.db"
    _build_db(path)
    client = _client(path, monkeypatch)
    first = client.get("/api/game/nba/2000000001/story").json()
    assert first["story"]
    con = sqlite3.connect(path)
    con.execute("""CREATE TRIGGER block_story_history BEFORE INSERT ON game_story_deterministic_history
        BEGIN SELECT RAISE(ABORT,'test rollback'); END""")
    con.commit()
    con.close()

    response = client.get("/api/game/nba/2000000001/story?refresh=true")
    assert response.status_code == 200
    assert response.json()["story"] == first["story"]
    assert response.json()["cached"] is True
    assert response.json()["status"] == "failed"
    con = sqlite3.connect(path)
    assert con.execute(
        "SELECT COUNT(*) FROM game_story_deterministic_history WHERE game_id='2000000001'").fetchone()[0] == 1
    assert con.execute(
        "SELECT story FROM game_story_deterministic WHERE game_id='2000000001'").fetchone()[0] == first["story"]
    con.close()


def test_postgame_snapshot_transitions_to_existing_recap_path(tmp_path, monkeypatch):
    path = tmp_path / "picks.db"
    _build_db(path)
    past = _iso(dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1))
    con = sqlite3.connect(path)
    con.execute("UPDATE nba_schedule SET start_utc=? WHERE game_id='2000000001'", (past,))
    con.execute(
        "INSERT INTO scoreboard_snapshots(league,game_id,state,payload,fetched_at,start_time) "
        "VALUES (?,?,?,?,?,?)",
        ("nba", "2000000001", "post", json.dumps({"completed": True}), _iso(
            dt.datetime.now(dt.timezone.utc)), past),
    )
    con.commit()
    con.close()
    client = _client(path, monkeypatch)

    import espn_client
    monkeypatch.setattr(espn_client, "game_result", lambda *_: {
        "state": "post", "home": "BOS", "winner": "BOS", "scores": {"ATL": 100, "BOS": 110},
    })
    monkeypatch.setattr(core_stories, "_game_season_year", lambda *_: SEASON)
    monkeypatch.setattr(core_stories, "_game_season_type", lambda *_: 2)
    monkeypatch.setattr(core_stories, "_finished_scoreboard_records", lambda *_: {
        "ATL": {"record": "0-2", "name": "Atlanta Hawks"},
        "BOS": {"record": "2-0", "name": "Boston Celtics"},
    })
    monkeypatch.setattr(core_stories, "_nba_standings_for_season", lambda *_: {"season": SEASON, "teams": []})
    monkeypatch.setattr(core_stories, "_nba_facts_as_of_now", lambda: None)
    monkeypatch.setattr(core_stories, "_logs_predate_season", lambda *_: True)
    import matchup_context
    monkeypatch.setattr(matchup_context, "context_lines", lambda *a, **k: [])
    monkeypatch.setattr(_core, "_deepseek_chat", lambda *_a, **_k: "Postgame recap.")

    response = client.get("/api/game/nba/2000000001/story")
    assert response.status_code == 200
    assert response.json()["story"] == "Postgame recap."
    con = sqlite3.connect(path)
    assert con.execute(
        "SELECT story FROM game_story WHERE league='nba' AND game_id='2000000001'").fetchone()[0] == "Postgame recap."
    history_table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='game_story_deterministic_history'").fetchone()
    assert history_table is None or con.execute(
        "SELECT COUNT(*) FROM game_story_deterministic_history WHERE game_id='2000000001'").fetchone()[0] == 0
    con.close()


def test_feature_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("LP_DETERMINISTIC_STORY_ENGINE", raising=False)
    assert core_stories._deterministic_story_engine_enabled() is False
