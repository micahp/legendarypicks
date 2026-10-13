import sqlite3

from backfill_scoring_plays import backfill
from core_snapshots import _extract_scoring_plays


def _header():
    return {"competitions": [{"competitors": [
        {"homeAway": "home", "team": {"id": "1", "abbreviation": "ARMY"}},
        {"homeAway": "away", "team": {"id": "2", "abbreviation": "NAVY"}},
    ]}]}


def test_ncaaf_reads_the_published_scoring_plays_collection():
    summary = {
        "header": _header(),
        "scoringPlays": [{
            "id": "play-1",
            "text": "Blake Horvath 5 Yd Run", "homeScore": 0, "awayScore": 7,
            "period": {"number": 1}, "clock": {"displayValue": "7:16"},
            "type": {"text": "Rushing Touchdown"},
            "team": {"id": "2", "abbreviation": "NAVY"},
        }],
        "plays": [],
    }
    assert _extract_scoring_plays("ncaaf", "game-1", summary) == [{
        "play_id": "play-1", "period": 1, "period_disp": "", "clock": "7:16",
        "away_score": 7, "home_score": 0, "team_abbrev": "NAVY",
        "scorer_name": "", "play_text": "Blake Horvath 5 Yd Run",
        "play_type": "Rushing Touchdown",
    }]


def test_mls_reads_key_events_and_reconstructs_score_from_published_team_ids():
    summary = {
        "header": _header(),
        "keyEvents": [
            {"id": "goal-1", "scoringPlay": True, "text": "Goal one",
             "period": {"number": 1}, "clock": {"displayValue": "17'"},
             "type": {"text": "Goal"}, "team": {"id": "2"},
             "participants": [{"athlete": {"displayName": "Victor Olatunji"}}]},
            {"id": "goal-2", "scoringPlay": True, "text": "Goal two",
             "period": {"number": 2}, "clock": {"displayValue": "88'"},
             "type": {"text": "Goal - Header"}, "team": {"id": "1"},
             "participants": [{"athlete": {"displayName": "João Klauss"}}]},
        ],
    }
    plays = _extract_scoring_plays("mls", "game-2", summary)
    assert [(p["home_score"], p["away_score"], p["team_abbrev"], p["scorer_name"])
            for p in plays] == [
        (0, 1, "NAVY", "Victor Olatunji"),
        (1, 1, "ARMY", "João Klauss"),
    ]


def test_backfill_is_dry_and_idempotent():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE scoring_plays(
          league TEXT,game_id TEXT,play_id TEXT,captured_at TEXT,period INTEGER,
          period_disp TEXT,clock TEXT,away_score INTEGER,home_score INTEGER,
          team_abbrev TEXT,scorer_name TEXT,play_text TEXT,play_type TEXT
        );
    """)
    summary = {
        "header": _header(),
        "scoringPlays": [{"id": "p1", "scoringPlay": True,
          "homeScore": 3, "awayScore": 0, "team": {"id": "1"}}],
    }
    assert backfill(con, "ncaaf", "g1", summary) == {
        "published": 1, "existing": 0, "new": 1, "written": 0,
    }
    assert backfill(con, "ncaaf", "g1", summary, apply=True)["written"] == 1
    assert backfill(con, "ncaaf", "g1", summary, apply=True) == {
        "published": 1, "existing": 1, "new": 0, "written": 0,
    }
