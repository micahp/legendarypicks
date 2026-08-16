"""A row's mlbam_id is repaired only when the BOX SCORE says so.

Three MLB player rows carried a different same-named man's id (measured
2026-08-11): `Joe Mack` held 118086, who debuted in 1945; `Jacob Wilson` held
607111, inactive; `Luis Castillo` held 699127, an A-ball outfielder. Between
them 5,436 props settle to `hit=NULL` forever, because MLB settlement keys the
box score by mlbam_id and theirs never appears in one.

The test that matters is the CONTROL. `Jared Jones` sits in the same
name-collision list, looks identical to the eye, and his id is already correct —
so any rule based on resemblance (same name, same team, same position, one row
has more props) would have corrupted him. The only admissible evidence is
whether the id appears in the box score of a game the row's own props were
written for.
"""
import sqlite3

import pytest

import repair_mlb_wrong_mlbam_ids as R


def _box(ids):
    """A published box score containing exactly these mlbam_ids."""
    half = len(ids) // 2 or len(ids)
    return {"teams": {"home": {"players": {"ID%d" % i: {} for i in ids[:half]}},
                      "away": {"players": {"ID%d" % i: {} for i in ids[half:]}}}}


def _con(player_id=12):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE prop_games (id INTEGER PRIMARY KEY, date TEXT, home TEXT, away TEXT)")
    con.execute("CREATE TABLE props (id INTEGER PRIMARY KEY, player_id INTEGER, game_id INTEGER)")
    con.execute("INSERT INTO prop_games VALUES (1,'2026-06-15','Miami Marlins','Philadelphia Phillies')")
    con.execute("INSERT INTO props VALUES (1, ?, 1)", (player_id,))
    return con


@pytest.fixture
def stub(monkeypatch):
    """Pin the publisher so the test cannot depend on the network."""
    def use(ids):
        monkeypatch.setattr(R, "_fetch_mlb_gamepk", lambda d, h, a: 823452)
        monkeypatch.setattr(R, "_fetch_mlb_boxscore", lambda pk: _box(ids))
    return use


def test_box_score_ids_are_parsed_from_the_ID_prefixed_keys():
    assert R.boxscore_mlbam_ids(_box([691788, 592450])) == {691788, 592450}


def test_a_row_whose_id_is_absent_and_whose_sibling_is_present_is_repaired(stub):
    """Joe Mack: 118086 (1945 Braves) absent, 691788 (Marlins C) present."""
    stub([691788, 592450])
    row = {"id": 12, "name": "Joe Mack", "mlbam_id": 118086}
    sibs = [{"id": 26757, "name": "joe mack", "mlbam_id": 691788}]
    assert R.verdict(_con(), row, sibs, 3) == ("repair", 691788)


def test_a_row_whose_own_id_appears_is_LEFT_ALONE(stub):
    """The control. Jared Jones is in the same collision list and is correct;
    a resemblance-based rule would have rewritten him."""
    stub([683003, 592450])
    row = {"id": 91, "name": "Jared Jones", "mlbam_id": 683003}
    sibs = [{"id": 27809, "name": "Jared Jones", "mlbam_id": 702262}]
    assert R.verdict(_con(91), row, sibs, 3) == ("ok", 683003)


def test_two_siblings_both_present_is_ambiguous_and_refused(stub):
    stub([691788, 702262])
    row = {"id": 12, "name": "Joe Mack", "mlbam_id": 118086}
    sibs = [{"id": 1, "name": "joe mack", "mlbam_id": 691788},
            {"id": 2, "name": "joe mack", "mlbam_id": 702262}]
    d, _ = R.verdict(_con(), row, sibs, 3)
    assert d == "unproven"


def test_nobody_present_is_unproven_not_a_guess(stub):
    """Absence of the current id is NOT by itself evidence for the sibling."""
    stub([111111, 222222])
    row = {"id": 12, "name": "Joe Mack", "mlbam_id": 118086}
    sibs = [{"id": 1, "name": "joe mack", "mlbam_id": 691788}]
    d, _ = R.verdict(_con(), row, sibs, 3)
    assert d == "unproven"


def test_an_unreadable_box_score_is_unproven_not_a_repair(monkeypatch):
    """Evidence unavailable must never render as a decision."""
    monkeypatch.setattr(R, "_fetch_mlb_gamepk", lambda d, h, a: 1)
    monkeypatch.setattr(R, "_fetch_mlb_boxscore", lambda pk: None)
    row = {"id": 12, "name": "Joe Mack", "mlbam_id": 118086}
    sibs = [{"id": 1, "name": "joe mack", "mlbam_id": 691788}]
    d, why = R.verdict(_con(), row, sibs, 3)
    assert d == "unproven" and "box score" in why


def test_a_row_with_no_props_is_never_repaired(stub):
    """No props means no game to check, so there is no evidence either way."""
    stub([691788])
    con = _con()
    con.execute("DELETE FROM props")
    row = {"id": 12, "name": "Joe Mack", "mlbam_id": 118086}
    d, _ = R.verdict(con, row, [{"id": 1, "name": "j", "mlbam_id": 691788}], 3)
    assert d == "unproven"
