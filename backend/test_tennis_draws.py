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
                    "status": {"type": {"state": "pre", "completed": False,
                                         "description": "Scheduled"}},
                    "competitors": [{
                        "id": "1001",
                        "homeAway": "home",
                        "curatedRank": {"current": 12},
                        "athlete": {"displayName": "Player One", "shortName": "P. One"},
                    }, {
                        "id": "1002",
                        "homeAway": "away",
                        "athlete": {"displayName": "Player Two", "shortName": "P. Two"},
                    }],
                }, {
                    "id": "m2",
                    "tournamentId": "363",
                    "date": "2026-08-27T15:00Z",
                    "round": {"id": "2", "displayName": "Second Round"},
                    "status": {"type": {"state": "pre", "completed": False,
                                         "description": "Scheduled"}},
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
    assert draw["matches"][0]["home"]["athlete_id"] == "1001"
    assert draw["matches"][0]["home"]["seed"] == 12
    assert draw["matches"][0]["away"]["athlete_id"] == "1002"
    assert draw["matches"][0]["away"]["seed"] is None
    assert draw["matches"][1]["home"] is None
    assert draw["matches"][1]["away"] is None


def test_tennis_scoreboard_preserves_published_finality_and_winner_flags():
    payload = _payload()
    comp = payload["events"][0]["groupings"][0]["competitions"][0]
    comp["status"]["type"] = {
        "state": "post", "completed": True, "description": "Retired",
    }
    comp["competitors"][0]["winner"] = False
    comp["competitors"][1]["winner"] = True

    match = espn_client.tennis_draws_from_payload("atp", payload)[0]["matches"][0]

    assert match["completed"] is True
    assert match["home"]["winner"] is False
    assert match["away"]["winner"] is True


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


def test_a_250_bracket_is_kept_and_an_untracked_event_is_not():
    # Almaty Open is an ATP 250 on the 2026 calendar, so its complete bracket is kept.
    almaty = _payload()
    almaty["events"] = almaty["events"][:1]
    almaty["events"][0]["shortName"] = "Almaty Open"
    assert [d["event_name"] for d in espn_client.tennis_draws_from_payload("atp", almaty)] == ["Almaty Open"]

    # Jiangxi Open is not a 250 on either calendar, so the same shape of bracket is ignored.
    jiangxi = _payload()
    jiangxi["events"] = jiangxi["events"][:1]
    jiangxi["events"][0]["shortName"] = "Jiangxi Open"
    jiangxi["events"][0]["groupings"][0]["grouping"].update({
        "id": "2", "slug": "womens-singles", "displayName": "Women's Singles",
    })
    assert espn_client.tennis_draws_from_payload("wta", jiangxi) == []


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


def _draw(tid, *matches):
    return {"tournament_id": tid, "matches": [{"date": d, "state": s} for d, s in matches]}


def test_two_live_draws_finish_the_one_in_progress_first():
    # ATP 2026-10-06 as ESPN published it: China Open's final still to play,
    # Shanghai's first round under way and its final on 10-18.
    china = _draw("959", ("2026-10-05T08:00Z", "post"), ("2026-10-06T11:00Z", "pre"))
    shanghai = _draw("315", ("2026-10-05T04:05Z", "in"), ("2026-10-18T04:00Z", "pre"))
    assert espn_client.current_tennis_draw([shanghai, china]) == [china]
    china["matches"][-1]["state"] = "post"
    assert espn_client.current_tennis_draw([china, shanghai]) == [shanghai]


def test_every_draw_complete_keeps_the_one_that_finished_last():
    old = _draw("1", ("2026-09-01T00:00Z", "post"))
    new = _draw("2", ("2026-09-08T00:00Z", "post"))
    assert espn_client.current_tennis_draw([new, old]) == [new]
    assert espn_client.current_tennis_draw([old]) == [old]
    assert espn_client.current_tennis_draw([]) == []


# ---------------------------------------------------------------------------
# Multi-tournament storage. One tour can have several complete brackets live at once (500s overlap
# Masters and each other), so the store keys on (league, tournament_id).
# ---------------------------------------------------------------------------

OLD_DRAW_TABLE = """
CREATE TABLE tennis_draw_snapshots(
  league        TEXT PRIMARY KEY,
  tournament_id TEXT NOT NULL,
  event_name    TEXT NOT NULL,
  bracket_url   TEXT,
  payload       TEXT NOT NULL,
  match_count   INTEGER NOT NULL,
  fetched_at    TEXT NOT NULL,
  source        TEXT
);
"""


def _match(game_id, date, state="pre", completed=False, round_name="First Round"):
    return {"game_id": game_id, "date": date, "state": state, "completed": completed,
            "round": round_name, "home": None, "away": None}


def _bracket(league, tournament_id, event_name, *matches):
    return {"league": league, "tournament_id": tournament_id, "event_name": event_name,
            "draw_type": "Singles", "bracket_url": f"https://www.espn.com/tennis/bracket/t/{tournament_id}",
            "match_count": len(matches), "matches": list(matches)}


def _store(tmp_path, monkeypatch):
    db = tmp_path / "draws.db"
    monkeypatch.setenv("LP_DB_PATH", str(db))
    return db


def test_migration_keeps_the_live_rows_and_is_idempotent(tmp_path):
    db = tmp_path / "old.db"
    shanghai = ("atp", "315", "Rolex Shanghai Masters", "https://www.espn.com/tennis/bracket/315",
                '{"matches": []}', 131, "2026-10-18T10:26:11+00:00", "espn")
    wuhan = ("wta", "381", "Dongfeng Voyah Wuhan Open", "https://www.espn.com/tennis/bracket/381",
             '{"matches": []}', 79, "2026-10-18T13:25:10+00:00", "espn")
    with sqlite3.connect(db) as old:
        old.executescript(OLD_DRAW_TABLE)
        old.executemany("INSERT INTO tennis_draw_snapshots VALUES (?,?,?,?,?,?,?,?)", [shanghai, wuhan])

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        scoreboard_store.init(con)
        rows = [tuple(row) for row in con.execute(
            "SELECT league, tournament_id, event_name, bracket_url, payload, match_count, fetched_at, source"
            " FROM tennis_draw_snapshots ORDER BY league")]
        assert rows == [("atp",) + shanghai[1:], ("wta",) + wuhan[1:]]
        assert scoreboard_store._draw_key_columns(con) == ["league", "tournament_id"]

        scoreboard_store.init(con)  # a second run changes nothing
        assert con.execute("SELECT COUNT(*) FROM tennis_draw_snapshots").fetchone()[0] == 2

        con.execute("INSERT INTO tennis_draw_snapshots (league, tournament_id, event_name, payload,"
                    " match_count, fetched_at) VALUES ('wta','963','BNB Ningbo Open','{}',45,'x')")
        con.commit()
        assert con.execute("SELECT COUNT(*) FROM tennis_draw_snapshots WHERE league='wta'").fetchone()[0] == 2
    finally:
        con.close()


def test_two_concurrent_draws_per_tour_persist_and_both_are_served(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    wuhan = _bracket("wta", "381", "Dongfeng Voyah Wuhan Open",
                     _match("w1", "2026-10-17T03:00Z", "post", True), _match("w2", "2026-10-18T03:00Z", "in"))
    ningbo = _bracket("wta", "963", "BNB Ningbo Open",
                      _match("n1", "2026-10-19T03:00Z"), _match("n2", "2026-10-20T03:00Z"))

    assert scoreboard_store.save_tennis_draws("wta", [wuhan, ningbo]) == 4
    stored = scoreboard_store.read_tennis_draws("wta")
    assert sorted(draw["tournament_id"] for draw in stored) == ["381", "963"]

    payload = tennis_draws("wta")
    assert payload["available"] is True
    assert payload["reason"] is None
    assert payload["source"] == "tennis_draw_snapshots"
    assert [draw["tournament_id"] for draw in payload["tours"]] == ["381", "963"]
    assert {"league", "tournament_id", "event_name", "draw_type", "bracket_url", "match_count", "matches"} <= set(
        payload["tours"][0])


def test_a_later_draw_does_not_erase_an_earlier_one(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    scoreboard_store.save_tennis_draws("atp", [_bracket("atp", "315", "Shanghai", _match("s1", "2026-10-18T04:00Z"))])
    scoreboard_store.save_tennis_draws("atp", [_bracket("atp", "10", "Erste Bank Open", _match("e1", "2026-10-27T10:00Z"))])
    assert sorted(draw["tournament_id"] for draw in scoreboard_store.read_tennis_draws("atp")) == ["10", "315"]


def test_one_malformed_draw_rejects_the_whole_response_and_writes_nothing(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    scoreboard_store.save_tennis_draws("wta", [_bracket("wta", "381", "Wuhan", _match("w1", "2026-10-18T03:00Z"))])
    good = _bracket("wta", "963", "Ningbo", _match("n1", "2026-10-19T03:00Z"))
    broken = _bracket("wta", "1000", "Broken", _match("b1", "2026-10-19T03:00Z"))
    broken["matches"][0]["round"] = ""
    with pytest.raises(ValueError, match="invalid wta draw snapshot"):
        scoreboard_store.save_tennis_draws("wta", [good, broken])
    assert [draw["tournament_id"] for draw in scoreboard_store.read_tennis_draws("wta")] == ["381"]


def test_duplicate_tournament_in_one_response_is_rejected(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    first = _bracket("atp", "315", "Shanghai", _match("s1", "2026-10-18T04:00Z"))
    second = _bracket("atp", "315", "Shanghai again", _match("s2", "2026-10-18T05:00Z"))
    with pytest.raises(ValueError, match="duplicate atp draw tournament id 315"):
        scoreboard_store.save_tennis_draws("atp", [first, second])
    assert scoreboard_store.read_tennis_draws("atp") == []


def test_empty_response_never_changes_stored_draws(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    scoreboard_store.save_tennis_draws("atp", [_bracket("atp", "315", "Shanghai", _match("s1", "2026-10-18T04:00Z"))])
    assert scoreboard_store.save_tennis_draws("atp", [], observed_on="2026-10-30") == 0
    assert [draw["tournament_id"] for draw in scoreboard_store.read_tennis_draws("atp")] == ["315"]


def test_a_finished_draw_the_publisher_stops_listing_is_retired(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    finished = _bracket("atp", "100", "Finished 500",
                        _match("f1", "2026-10-10T10:00Z", "post", True), _match("f2", "2026-10-12T15:00Z", "post", True))
    live = _bracket("atp", "315", "Shanghai", _match("s1", "2026-10-18T04:00Z"))
    scoreboard_store.save_tennis_draws("atp", [finished, live])

    scoreboard_store.save_tennis_draws("atp", [live], observed_on="2026-10-13")
    assert [draw["tournament_id"] for draw in scoreboard_store.read_tennis_draws("atp")] == ["315"]


def test_a_draw_with_a_match_still_scheduled_is_kept_even_if_omitted(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    upcoming = _bracket("atp", "10", "Erste Bank Open", _match("e1", "2026-10-27T10:00Z"))
    live = _bracket("atp", "315", "Shanghai", _match("s1", "2026-10-18T04:00Z"))
    scoreboard_store.save_tennis_draws("atp", [upcoming, live])

    scoreboard_store.save_tennis_draws("atp", [live], observed_on="2026-10-19")
    assert sorted(draw["tournament_id"] for draw in scoreboard_store.read_tennis_draws("atp")) == ["10", "315"]


def test_a_suspended_match_keeps_its_draw_open_and_stored(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    suspended = _bracket("atp", "100", "Suspended 500",
                         _match("x1", "2026-10-12T15:00Z", "post", False, "Final"))
    live = _bracket("atp", "315", "Shanghai", _match("s1", "2026-10-18T04:00Z"))
    scoreboard_store.save_tennis_draws("atp", [suspended, live])

    scoreboard_store.save_tennis_draws("atp", [live], observed_on="2026-10-19")
    assert sorted(draw["tournament_id"] for draw in scoreboard_store.read_tennis_draws("atp")) == ["100", "315"]


def test_nothing_is_retired_without_an_observation_date(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch)
    finished = _bracket("atp", "100", "Finished 500", _match("f1", "2026-10-10T10:00Z", "post", True))
    live = _bracket("atp", "315", "Shanghai", _match("s1", "2026-10-18T04:00Z"))
    scoreboard_store.save_tennis_draws("atp", [finished, live])
    scoreboard_store.save_tennis_draws("atp", [live])
    assert sorted(draw["tournament_id"] for draw in scoreboard_store.read_tennis_draws("atp")) == ["100", "315"]


def test_display_order_puts_draws_in_progress_first_then_most_recently_finished():
    finished_old = _bracket("atp", "1", "Old", _match("a", "2026-09-01T00:00Z", "post", True))
    finished_new = _bracket("atp", "2", "New", _match("b", "2026-10-05T00:00Z", "post", True))
    open_soon = _bracket("atp", "3", "Soon", _match("c", "2026-10-06T11:00Z", "post", True), _match("d", "2026-10-07T00:00Z"))
    open_late = _bracket("atp", "4", "Late", _match("e", "2026-10-18T04:00Z", "in"))
    suspended = _bracket("atp", "5", "Suspended", _match("f", "2026-10-08T00:00Z", "post", False))
    ordered = espn_client.order_tennis_draws([finished_old, open_late, finished_new, suspended, open_soon])
    assert [draw["tournament_id"] for draw in ordered] == ["3", "5", "4", "2", "1"]


def test_ingest_stores_every_complete_draw_and_passes_the_observation_date(monkeypatch):
    saved = []
    monkeypatch.setattr(espn_client, "games", lambda league, date: [{"game_id": "m1"}])
    monkeypatch.setattr(scoreboard_store, "save", lambda *args, **kwargs: 1)
    monkeypatch.setattr(scoreboard_store, "save_tennis_draws",
                        lambda league, draws, **kwargs: saved.append((league, [d["tournament_id"] for d in draws], kwargs)) or 0)
    first = _payload()
    second = _payload()
    second["events"][0]["id"] = "shanghai-2026"
    second["events"][0]["shortName"] = "Rolex Shanghai Masters"
    for comp, (tid, gid) in zip(second["events"][0]["groupings"][0]["competitions"], (("315", "s1"), ("315", "s2"))):
        comp["tournamentId"] = tid
        comp["id"] = gid
    combined = {"events": first["events"][:1] + second["events"][:1]}
    monkeypatch.setattr(espn_client, "scoreboard_raw", lambda league, date: combined)

    written, error = ingest_scoreboards._refresh("atp", "2026-08-24", verbose=False)

    assert error is None
    assert saved == [("atp", ["363", "315"], {"source": "espn", "observed_on": "2026-08-24"})]
