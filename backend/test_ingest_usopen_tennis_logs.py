import json
import os
import sqlite3
import tempfile
from unittest import mock

import ingest_usopen_tennis_logs as ingest
from routers import props


def match_fixture():
    return {"match_id": "1101", "eventCode": "MS", "roundName": "Round 1",
            "winner": "1", "epoch": 1788310526000,
            "team1": {"firstNameA": "A", "lastNameA": "One", "idA": "atpa",
                      "totalSetsWon": 1},
            "team2": {"firstNameA": "B", "lastNameA": "Two", "idA": "atpb",
                      "totalSetsWon": 0},
            "scores": {"sets": [[{"score": 1}, {"score": 0}]]}}


def point(**values):
    row = {"PointID": "010101", "PointWinner": "1", "GameWinner": "0", "SetWinner": "0",
           "MatchWinner": "0", "Ace": "0", "DoubleFault": "0",
           "BreakPointWon": "0"}
    row.update(values)
    return row


def test_point_codes_are_player_coded_not_boolean():
    points = [point(PointID="010101", Ace="1"),
              point(PointID="010102", PointWinner="2", DoubleFault="1", BreakPointWon="2"),
              point(PointID="010103", GameWinner="1", SetWinner="1", MatchWinner="1")]
    rows = ingest.aggregate_match(match_fixture(), points)
    assert rows[0]["stats"] == {"aces": 1, "double_faults": 1, "games_won": 1,
                                "breakpoints_won": 0, "points_won": 2,
                                "sets_won": 1}
    assert rows[1]["stats"]["breakpoints_won"] == 1


def test_reconciliation_rejects_missing_game_winner():
    points = [point(SetWinner="1", MatchWinner="1")]
    try:
        ingest.aggregate_match(match_fixture(), points)
    except RuntimeError as exc:
        assert "game reconciliation" in str(exc)
    else:
        raise AssertionError("bad source population was accepted")


def test_identity_ambiguity_fails_closed():
    rows = [{"league": "atp", "name": "A One"}]
    got = list(ingest.resolve_rows(rows, {("atp", "a one"): [1, 2]}))
    assert got[0]["player_id"] is None


def test_publish_is_idempotent_and_provider_separated():
    con = sqlite3.connect(":memory:")
    row = {"player_id": 1, "league": "atp", "season": 2026,
           "game_no": "usopen-1", "game_id": "1", "game_date": "2026-09-01",
           "opponent": "B Two", "stats": {"aces": 4},
           "source_player_key": "atpa", "game_type": "Round 1"}
    ingest.publish(con, [row]); ingest.publish(con, [row])
    stored = con.execute(f"SELECT source,stats FROM {ingest.TABLE}").fetchall()
    assert len(stored) == 1 and stored[0][0] == "usopen.org"
    assert json.loads(stored[0][1])["aces"] == 4


def test_props_history_reads_official_tennis_provider_directly():
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = handle.name
    handle.close()
    try:
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE players(id INTEGER PRIMARY KEY,name TEXT,team TEXT,league TEXT)")
        con.execute("INSERT INTO players VALUES(1,'A One',NULL,'atp')")
        row = {"player_id": 1, "league": "atp", "season": 2026,
               "game_no": "usopen-1", "game_id": "1", "game_date": "2026-09-01",
               "opponent": "B Two", "stats": {"aces": 4},
               "source_player_key": "atpa", "game_type": "Round 1"}
        ingest.publish(con, [row]); con.commit(); con.close()

        def connection():
            db = sqlite3.connect(path); db.row_factory = sqlite3.Row; return db
        with mock.patch.object(props, "_db", side_effect=connection):
            result = props.prop_history(player_id=1, market="aces", line=3.5,
                                        side="over", league="atp")
        assert [game["value"] for game in result["games"]] == [4]
    finally:
        os.unlink(path)
