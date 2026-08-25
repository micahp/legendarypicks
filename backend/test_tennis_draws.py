import json
import sqlite3

import pytest

import espn_client
import ingest_scoreboards
import scoreboard_store
from routers.games.misc import tennis_draws


def _payload():
    return {
        "events": [{
            "id": "us-open-2026",
            "name": "US Open",
            "shortName": "US Open",
            "links": [{"rel": ["bracket"], "href": "https://www.espn.com/tennis/bracket/type/1"}],
            "groupings": [{
                "grouping": {"id": "1", "slug": "mens-singles", "displayName": "Men's Singles"},
                "competitions": [{
                    "id": "m1",
                    "tournamentId": "363",
                    "date": "2026-08-25T15:00Z",
                    "round": {"id": "1", "displayName": "First Round"},
                    "status": {"type": {"state": "pre", "description": "Scheduled"}},
                    "competitors": [{
                        "homeAway": "home",
                        "athlete": {"displayName": "Player One", "shortName": "P. One"},
                    }],
                }, {
                    "id": "m2",
                    "tournamentId": "363",
                    "date": "2026-08-27T15:00Z",
                    "round": {"id": "2", "displayName": "Second Round"},
                    "status": {"type": {"state": "pre", "description": "Scheduled"}},
                    "competitors": [],
                }],
            }, {
                "grouping": {"slug": "mens-doubles", "displayName": "Men's Doubles"},
                "competitions": [{"id": "ignored"}],
            }],
        }, {
            "id": "ordinary",
            "shortName": "Winston-Salem Open",
            "groupings": [],
        }],
    }


def test_draw_parser_keeps_rounds_future_tbd_and_official_link():
    draws = espn_client.tennis_draws_from_payload("atp", _payload())

    assert len(draws) == 1
    draw = draws[0]
    assert draw["tournament_id"] == "363"
    assert draw["match_count"] == 2
    assert draw["bracket_url"].endswith("/type/1")
    assert [match["round"] for match in draw["matches"]] == ["First Round", "Second Round"]
    assert draw["matches"][1]["home"] is None
    assert draw["matches"][1]["away"] is None


def test_draw_parser_fails_loudly_on_incomplete_round():
    payload = _payload()
    del payload["events"][0]["groupings"][0]["competitions"][0]["round"]
    with pytest.raises(ValueError, match="incomplete atp draw match"):
        espn_client.tennis_draws_from_payload("atp", payload)


def test_draw_parser_does_not_relabel_a_mens_bracket_as_wta():
    payload = _payload()
    payload["events"][0]["groupings"][0]["grouping"].update({
        "id": "2", "slug": "womens-singles", "displayName": "Women's Singles",
    })
    draws = espn_client.tennis_draws_from_payload("wta", payload)
    assert draws[0]["bracket_url"] is None


def test_draw_store_round_trip_and_invalid_snapshot_preserves_last_good(tmp_path, monkeypatch):
    db = tmp_path / "draws.db"
    monkeypatch.setenv("LP_DB_PATH", str(db))
    draws = espn_client.tennis_draws_from_payload("atp", _payload())

    assert scoreboard_store.save_tennis_draws("atp", draws) == 2
    stored = scoreboard_store.read_tennis_draws("atp")
    assert stored[0]["match_count"] == 2
    assert stored[0]["source"] == "espn"

    broken = json.loads(json.dumps(draws))
    broken[0]["matches"][1]["game_id"] = "m1"
    with pytest.raises(ValueError, match="invalid atp draw snapshot"):
        scoreboard_store.save_tennis_draws("atp", broken)

    with sqlite3.connect(db) as con:
        assert con.execute("SELECT match_count FROM tennis_draw_snapshots").fetchone()[0] == 2


def test_ingest_validates_draw_before_writing_daily_slate(monkeypatch):
    saved = []
    monkeypatch.setattr(espn_client, "games", lambda league, date: [{"game_id": "m1"}])
    monkeypatch.setattr(espn_client, "scoreboard_raw", lambda league, date: {"events": []})
    monkeypatch.setattr(scoreboard_store, "save", lambda *args, **kwargs: saved.append(args))

    written, error = ingest_scoreboards._refresh("atp", "2026-08-24", verbose=False)

    assert written == 0
    assert error == "ValueError: atp published games without a complete major draw"
    assert saved == []


def test_draw_api_is_db_first_and_keeps_unavailable_reason(monkeypatch):
    monkeypatch.setattr(scoreboard_store, "read_tennis_draws", lambda tour=None: [])
    payload = tennis_draws("all")
    assert payload == {
        "available": False,
        "source": "tennis_draw_snapshots",
        "tours": [],
        "reason": "No verified major draw has been published yet.",
    }
