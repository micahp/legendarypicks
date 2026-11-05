"""One MLB person is one `players` row — and a shared NAME is never the evidence.

Measured on picks.dev.db 2026-08-11: 117 duplicate groups over 234 of 2,552 MLB
rows, merged down to 0. Nothing had raised: both rows carried a valid
`mlbam_id`, so settlement graded each correctly and the only symptom was a
player's history arriving split across two ids on every surface that reads by id.

The dangerous half is the REFUSAL. Eight name-groups hold two different
mlbam_ids and are different men:

    Jacob Wilson  805779  Athletics SS, debut 2024      <- carries 3,631 props
    Jacob Wilson  607111  Sugar Land Skeeters, inactive
    José Fermín   665877  Cardinals LF
    José Fermin   820862  Angels P

Merging those fuses two careers, which is strictly worse than the duplication it
would fix. So the refusal is tested as hard as the merge.

Guards `dedupe_mlb.py` (the merge) and `refresh_mlb_player_teams.py` (the
publisher copy), which are deliberately separate jobs.
"""
import sqlite3

import pytest

from dedupe_mlb import pick_canonical
from refresh_mlb_player_teams import TEAM_FIX, plan_changes


# ── the merge key ────────────────────────────────────────────────────────────

def _duplicate_groups(con):
    """The invariant the dedupe exists to establish: no mlbam_id twice."""
    return [r[0] for r in con.execute(
        """SELECT mlbam_id FROM players
           WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0
           GROUP BY mlbam_id HAVING COUNT(*) > 1""")]


def _db(rows):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, team TEXT,
                   league TEXT, mlbam_id INTEGER, position TEXT, espn_id TEXT, active INTEGER)""")
    for r in rows:
        con.execute("""INSERT INTO players(id,name,team,league,mlbam_id,position,espn_id,active)
                       VALUES(?,?,?,?,?,?,?,?)""", r)
    return con


def test_two_rows_sharing_an_mlbam_id_are_one_person():
    con = _db([(1, "Julio Rodríguez", "SEA", "mlb", 677594, "CF", "42403", 1),
               (2, "Julio Rodriguez", "SEA", "mlb", 677594, "CF", None, 1)])
    assert _duplicate_groups(con) == [677594]


def test_different_mlbam_ids_are_never_one_person_however_alike_the_names():
    """`José Fermín` and `José Fermin` normalise identically and are two men."""
    con = _db([(26710, "josé fermín", "STL", "mlb", 665877, "LF", None, 1),
               (28282, "José Fermin", "LAA", "mlb", 820862, "P", None, 1)])
    assert _duplicate_groups(con) == [], "name similarity must never create a merge"


def test_a_null_mlbam_id_is_unknown_identity_not_a_match():
    con = _db([(1, "Jose Ramirez", "CLE", "mlb", 608070, "3B", None, 1),
               (2, "Jose Ramirez", "CLE", "mlb", None, "3B", None, 1)])
    assert _duplicate_groups(con) == []


def test_canonical_row_is_chosen_deterministically():
    """Whatever the rule, it must not depend on row order."""
    a = {"id": 26571, "espn_id": "4683", "active": 1, "mlbam_id": 702616}
    b = {"id": 32176, "espn_id": None, "active": 1, "mlbam_id": 702616}
    assert pick_canonical([a, b])["id"] == pick_canonical([b, a])["id"]


# ── the publisher copy ───────────────────────────────────────────────────────

def test_publisher_team_codes_are_converted_at_the_boundary():
    """statsapi says AZ/CWS; this repo says ARI/CHW. Converted once, at ingest —
    never by a reader (published-first §5: three copies of one alias map is two
    too many)."""
    assert TEAM_FIX["AZ"] == "ARI"
    assert TEAM_FIX["CWS"] == "CHW"


def test_a_minor_league_current_team_never_overwrites_our_team():
    """The publisher answers 'where does this person play', which is not 'which
    MLB club does this row represent'. 26 of 125 checked were in the minors."""
    rows = [{"id": 94, "name": "Jacob Wilson", "team": "ATH", "mlbam_id": 607111}]
    pub = {607111: {"team": None, "team_name": "Sugar Land Skeeters",
                    "pos": "2B", "active": False}}
    changes, minors, inactive, unknown = plan_changes(rows, pub)
    assert changes == []
    assert len(minors) == 1


def test_a_disagreement_with_the_publisher_is_a_change():
    rows = [{"id": 26934, "name": "Marcell Ozuna", "team": "LAD", "mlbam_id": 542303}]
    pub = {542303: {"team": "PIT", "team_name": "Pittsburgh Pirates",
                    "pos": "DH", "active": True}}
    changes, _, _, _ = plan_changes(rows, pub)
    assert len(changes) == 1 and changes[0][1]["team"] == "PIT"


def test_a_player_the_publisher_does_not_return_is_left_alone():
    rows = [{"id": 1, "name": "Nobody", "team": "BAL", "mlbam_id": 999999}]
    changes, minors, inactive, unknown = plan_changes(rows, {})
    assert changes == [] and len(unknown) == 1


def test_an_inactive_publisher_record_never_rewrites_a_live_row():
    """players.id=12 carries mlbam 118086 — a Joe Mack who debuted in 1945.
    statsapi maps his club to the modern Atlanta franchise, so applying it would
    stamp ATL onto a Marlins prospect and make a bad identity look published."""
    rows = [{"id": 12, "name": "Joe Mack", "team": "MIA", "mlbam_id": 118086}]
    pub = {118086: {"team": "ATL", "team_name": "Boston Braves",
                    "pos": "1B", "active": False}}
    changes, minors, inactive, unknown = plan_changes(rows, pub)
    assert changes == [], "a retired player must never rewrite a live row"
    assert len(inactive) == 1
