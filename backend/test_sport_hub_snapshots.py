import sqlite3

import pytest

import espn_client
import scoreboard_store
from routers.games.misc import soccer_competition, tennis_rankings


def _ranking_payload(count=150):
    return {
        "ranks": [{
            "current": rank,
            "previous": rank + (1 if rank % 2 else 0),
            "points": 10000 - rank,
            "athlete": {
                "$ref": f"http://sports.core.api.espn.com/v2/sports/tennis/athletes/{rank}"
            },
        } for rank in range(1, count + 1)]
    }


def _identity_payload(start=1):
    return {
        "rankings": [{
            "name": "ATP",
            "ranks": [{
                "athlete": {
                    "id": str(source_id),
                    "displayName": f"Player {source_id}",
                    "active": True,
                },
            } for source_id in range(start, start + 150)],
        }],
    }


def _ranking_db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,"
        " espn_id TEXT, active INTEGER, updated_at TEXT)"
    )
    con.executemany(
        "INSERT INTO players(id,name,team,league,espn_id,active) VALUES(?,?,NULL,?,?,1)",
        [(rank, f"Player {rank}", "atp", str(rank)) for rank in range(1, 151)],
    )
    con.commit()
    con.close()


def test_tennis_rankings_parser_keeps_ids_and_rejects_the_cap_gap():
    rows = espn_client.tennis_rankings_from_payload("atp", _ranking_payload())
    assert len(rows) == 150
    assert rows[0] == {
        "espn_athlete_id": "1",
        "rank": 1,
        "previous_rank": 2,
        "points": 9999,
    }
    with pytest.raises(ValueError, match="top 150"):
        espn_client.tennis_rankings_from_payload("atp", _ranking_payload(149))

    identities = espn_client.tennis_ranking_identities_from_payload(
        "atp", _identity_payload()
    )
    assert identities[0] == {"espn_id": "1", "name": "Player 1", "active": True}


def test_tennis_ranking_store_is_id_keyed_and_capture_keyed(tmp_path, monkeypatch):
    db = tmp_path / "rankings.db"
    _ranking_db(db)
    monkeypatch.setenv("LP_DB_PATH", str(db))
    rows = espn_client.tennis_rankings_from_payload("atp", _ranking_payload())

    assert scoreboard_store.save_tennis_rankings("atp", rows) == 150
    snapshot = scoreboard_store.read_tennis_rankings("atp", limit=2)[0]
    assert [row["espn_athlete_id"] for row in snapshot["rankings"]] == ["1", "2"]
    assert snapshot["rankings"][0]["player_name"] == "Player 1"

    broken = [dict(row) for row in rows]
    broken[-1]["espn_athlete_id"] = "missing"
    with pytest.raises(ValueError, match="149 of 150 canonical athletes"):
        scoreboard_store.save_tennis_rankings("atp", broken)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM tennis_ranking_snapshots").fetchone()[0] == 150


def test_tennis_spine_refresh_inserts_new_ids_without_name_matching(tmp_path, monkeypatch):
    db = tmp_path / "spine.db"
    _ranking_db(db)
    monkeypatch.setenv("LP_DB_PATH", str(db))
    identities = espn_client.tennis_ranking_identities_from_payload(
        "atp", _identity_payload(start=6)
    )

    assert scoreboard_store.save_tennis_ranking_spine("atp", identities) == {
        "published": 150,
        "inserted": 5,
    }
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM players WHERE league='atp'").fetchone()[0] == 155
        assert con.execute("SELECT COUNT(*) FROM players WHERE league='atp' AND active=1").fetchone()[0] == 150
        assert con.execute("SELECT active FROM players WHERE league='atp' AND espn_id='1'").fetchone()[0] == 0


def _lcup_scoreboard():
    def event(game_id, slug, home, away):
        return {
            "id": game_id,
            "date": "2026-08-26T00:30Z",
            "season": {"year": 2026, "slug": slug},
            "competitions": [{
                "status": {"type": {"state": "pre", "description": "Scheduled"}},
                "competitors": [
                    {"homeAway": "home", "score": "0", "team": {"id": "1", "displayName": home, "abbreviation": "HOM"}},
                    {"homeAway": "away", "score": "0", "team": {"id": "2", "displayName": away, "abbreviation": "AWY"}},
                ],
            }],
        }
    return {
        "leagues": [{"season": {"year": 2026}}],
        "events": [
            event("group", "league-phase", "Ignored", "Ignored Too"),
            event("qf1", "quarterfinals", "Monterrey", "Chicago Fire FC"),
            event("third", "3rd-place-match", "Third Place A", "Third Place B"),
        ],
    }


def _lcup_statistics():
    return {
        "season": {"year": 2026, "name": "Quarterfinals"},
        "stats": [{
            "name": "goalsLeaders",
            "displayName": "Goals",
            "leaders": [{
                "value": 5,
                "displayValue": "Matches: 4, Goals: 5",
                "athlete": {
                    "id": "195681",
                    "displayName": "Angel Correa",
                    "team": {"displayName": "Tigres UANL", "abbreviation": "UANL"},
                },
            }],
        }],
    }


def test_lcup_snapshot_uses_published_rounds_and_leader_ids():
    snapshot = espn_client.lcup_competition_snapshot_from_payload(
        _lcup_scoreboard(), _lcup_statistics()
    )
    assert snapshot["season"] == 2026
    assert [round_row["key"] for round_row in snapshot["rounds"]] == ["quarterfinals", "3rd-place-match"]
    assert snapshot["rounds"][0]["matches"][0]["home"]["score"] is None
    assert snapshot["leader_categories"][0]["leaders"][0] == {
        "rank": 1,
        "espn_athlete_id": "195681",
        "name": "Angel Correa",
        "team": "Tigres UANL",
        "team_abbrev": "UANL",
        "matches": 4,
        "value": 5,
    }


def test_lcup_store_and_both_routes_are_db_first(tmp_path, monkeypatch):
    db = tmp_path / "soccer.db"
    monkeypatch.setenv("LP_DB_PATH", str(db))
    snapshot = espn_client.lcup_competition_snapshot_from_payload(
        _lcup_scoreboard(), _lcup_statistics()
    )
    assert scoreboard_store.save_soccer_competition(snapshot) == {
        "matches": 2,
        "leaders": 1,
        "standings": 0,
    }
    assert soccer_competition("lcup")["rounds"][0]["matches"][0]["game_id"] == "qf1"

    monkeypatch.setattr(scoreboard_store, "read_tennis_rankings", lambda tour, limit: [])
    assert tennis_rankings("all", 50)["reason"].startswith("No verified ATP or WTA")


def test_mls_standings_store_and_route_are_db_first(tmp_path, monkeypatch):
    db = tmp_path / "mls.db"
    monkeypatch.setenv("LP_DB_PATH", str(db))
    snapshot = {
        "league": "mls",
        "season": 2026,
        "available_seasons": [2026, 2025],
        "groups": [{
            "group": "Eastern Conference",
            "rows": [{
                "rank": 1,
                "abbrev": "PHI",
                "name": "Philadelphia Union",
                "played": 25,
                "wins": 15,
                "draws": 5,
                "losses": 5,
                "gf": 44,
                "ga": 25,
                "gd": 19,
                "points": 50,
            }],
        }],
    }

    assert scoreboard_store.save_soccer_competition(snapshot) == {
        "matches": 0,
        "leaders": 0,
        "standings": 1,
    }
    result = soccer_competition("mls")
    assert result["available"] is True
    assert result["groups"][0]["rows"][0]["abbrev"] == "PHI"
