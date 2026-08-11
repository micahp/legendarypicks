"""A game is final when the publisher says `completed`, not when `state == "post"`.

Found 2026-08-11 while closing out the finality gate end-to-end. The first live
probe of the repaired `game_result` returned:

    {"state": "post", "scores": {"ATL": 0.0, "SF": 0.0},
     "home": "ATL", "away": "SF", "home_score": 0.0, "winner": "ATL"}

for ESPN event 401815805 — a game that was **POSTPONED**. ESPN files a postponed
game as `status.type.state == "post"` with `completed: false`, `description:
"Postponed"`, and a score of `"0"` on both sides rather than null.

So the gate in `settlement.settle_game` (`result["state"] != "post"`) admitted it,
`winner` was handed out by `max(scores)` on a 0–0 tie, and a game that was never
played would have been stamped `final_home=0, final_away=0` and had every prop on
it graded against zeros. Failing OPEN, in the direction of wrong grades.

This is the same shape as the bug it was found inside: reading an ambiguous field
(`state`, which covers final/postponed/canceled/suspended alike) when the exact
one — `completed` — is published on the same object. The codebase already learned
this once; see `espn_client.games` (line ~212), `ingest_nba_logs`, and
`backfill_team_parity`, all of which filter on `completed`. `game_result` and the
settlement gate never got the memo.
"""
import sqlite3

import pytest

import espn_client
import settlement


def _summary(state="post", completed=True, description="Final",
             home_score="5", away_score="3"):
    return {"header": {"competitions": [{
        "status": {"type": {"state": state, "completed": completed,
                            "description": description, "shortDetail": description},
                   "period": 9, "displayClock": "0:00"},
        "competitors": [
            {"homeAway": "home", "score": home_score, "team": {"abbreviation": "ATL"}},
            {"homeAway": "away", "score": away_score, "team": {"abbreviation": "SF"}},
        ]}]}}


_POSTPONED = _summary(state="post", completed=False, description="Postponed",
                      home_score="0", away_score="0")


@pytest.fixture
def espn(monkeypatch):
    def use(doc):
        monkeypatch.setattr(espn_client, "summary", lambda lg, gid: doc)
    return use


# ── game_result reports the publisher's own answer ──────────────────────────────

def test_a_final_game_is_completed(espn):
    espn(_summary())
    assert espn_client.game_result("mlb", "1")["completed"] is True


def test_a_postponed_game_is_not_completed_even_though_state_is_post(espn):
    espn(_POSTPONED)
    r = espn_client.game_result("mlb", "401815805")
    assert r["state"] == "post", "ESPN really does file it under post"
    assert r["completed"] is False, "and publishes the distinction right here"


def test_a_postponed_game_has_no_winner(espn):
    """0–0 with `max(scores)` handed the win to whichever key sorted first."""
    espn(_POSTPONED)
    assert espn_client.game_result("mlb", "401815805")["winner"] is None


def test_a_real_tie_has_no_winner(espn):
    """`max()` on equal values returns the first key. A tie is not a win."""
    espn(_summary(home_score="2", away_score="2"))
    r = espn_client.game_result("mlb", "1")
    assert r["completed"] is True
    assert r["winner"] is None


def test_a_completed_game_still_names_the_winner(espn):
    espn(_summary(home_score="5", away_score="3"))
    assert espn_client.game_result("mlb", "1")["winner"] == "ATL"


def test_soccer_reports_completed_too(monkeypatch):
    doc = {"header": {"competitions": [{
        "status": {"type": {"state": "post", "completed": True, "shortDetail": "FT"},
                   "period": 2, "displayClock": "90'"},
        "competitors": [
            {"homeAway": "home", "score": "1", "winner": False, "team": {"abbreviation": "LAFC"}},
            {"homeAway": "away", "score": "2", "winner": True, "team": {"abbreviation": "SEA"}},
        ]}]}}
    monkeypatch.setattr(espn_client, "summary", lambda lg, gid: doc)
    assert espn_client.game_result("mls", "1")["completed"] is True


def test_a_publisher_that_omits_completed_is_not_treated_as_final(espn):
    """Absent is not True. Fail closed — an unsettled prop is recoverable, a
    wrongly-graded one is not."""
    doc = _summary()
    del doc["header"]["competitions"][0]["status"]["type"]["completed"]
    espn(doc)
    assert espn_client.game_result("mlb", "1")["completed"] is False


# ── the settlement gate refuses anything not completed ──────────────────────────

def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE prop_games (id INTEGER PRIMARY KEY, league TEXT, espn_event_id TEXT,
            home TEXT, away TEXT, date TEXT, final_home REAL, final_away REAL,
            start_time TEXT);
        CREATE TABLE props (id INTEGER PRIMARY KEY, game_id INTEGER, market TEXT, line REAL,
            side TEXT, player_id INTEGER);
        CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, team TEXT, espn_id TEXT);
        CREATE TABLE prop_results (prop_id INTEGER PRIMARY KEY, hit INTEGER, actual REAL);
    """)
    con.execute("INSERT INTO prop_games (id, league, espn_event_id, home, away, date,"
                " final_home, final_away) VALUES (1, 'mlb', '401815805', 'Atlanta Braves',"
                " 'San Francisco Giants', '2026-06-18', NULL, NULL)")
    con.commit()
    return con


def test_settlement_refuses_a_postponed_game(espn):
    espn(_POSTPONED)
    con = _db()
    out = settlement.settle_game(con, 1)
    row = con.execute("SELECT final_home, final_away FROM prop_games WHERE id=1").fetchone()
    assert row["final_home"] is None and row["final_away"] is None, \
        "a game that was never played must not be stamped 0-0"
    assert out["settled"] == 0
    assert "not final" in out["msg"]


def test_settlement_records_the_final_of_a_completed_game(espn):
    espn(_summary(home_score="5", away_score="3"))
    con = _db()
    settlement.settle_game(con, 1)
    row = con.execute("SELECT final_home, final_away FROM prop_games WHERE id=1").fetchone()
    assert (row["final_home"], row["final_away"]) == (5, 3), \
        "the end-to-end write the gate exists to perform"
