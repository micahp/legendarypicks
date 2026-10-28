"""The shadow harness changes exactly the records each scenario names, and no others."""
import copy

import pytest

import mls_snapshot_shadow as sh


def _squads():
    fotmob = [
        {"source": "fotmob", "source_player_key": str(k), "name": "Player %d" % k, "team": team,
         "position": "MF", "position_group": "midfield", "names": ["Player %d" % k]}
        for k, team in ((1, "Club A"), (2, "Club A"), (3, "Club B"), (4, "Club B"), (5, "Club C"))
    ]
    mlssoccer = [dict(m, source="mlssoccer", source_player_key="m%s" % m["source_player_key"]) for m in fotmob]
    return {"fotmob": fotmob, "mlssoccer": mlssoccer}


def _people():
    return [{"player_id": i, "keys": {"fotmob": str(i), "mlssoccer": "m%d" % i}} for i in range(1, 6)]


def _keys(squads, source):
    return sorted(str(m["source_player_key"]) for m in squads[source])


def test_the_live_squads_are_not_changed_by_the_repeat_scenario():
    squads = _squads()
    assert sh.apply("repeat", squads, _people()) == squads


def test_departure_removes_the_person_from_both_publishers_and_nobody_else():
    squads = _squads()
    changed = sh.apply("departure", squads, _people())
    assert _keys(changed, "fotmob") == ["2", "3", "4", "5"]
    assert _keys(changed, "mlssoccer") == ["m2", "m3", "m4", "m5"]


def test_transfer_moves_the_person_to_the_next_club_in_both_publishers():
    squads = _squads()
    changed = sh.apply("transfer", squads, _people())
    teams = {m["source_player_key"]: m["team"] for m in changed["fotmob"]}
    assert teams["2"] == "Club B"
    assert {m["source_player_key"]: m["team"] for m in changed["mlssoccer"]}["m2"] == "Club B"
    assert teams["1"] == "Club A"


def test_one_source_only_drops_the_fotmob_row_and_keeps_mls():
    changed = sh.apply("one_source_only", _squads(), _people())
    assert _keys(changed, "fotmob") == ["1", "2", "3", "5"]
    assert _keys(changed, "mlssoccer") == ["m1", "m2", "m3", "m4", "m5"]


def test_source_lag_moves_one_fotmob_row_and_leaves_mls_where_it_was():
    squads = _squads()
    changed = sh.apply("source_lag", squads, _people())
    teams = {m["source_player_key"]: m["team"] for m in changed["fotmob"]}
    # people[4] is player 5, at Club C; the next club after the last one wraps to the first.
    assert teams["5"] == "Club A"
    assert teams["4"] == "Club B"
    assert changed["mlssoccer"] == squads["mlssoccer"]


def test_signing_adds_one_key_per_publisher_at_the_first_club():
    changed = sh.apply("signing", _squads(), _people())
    assert "shadow-sign-1" in _keys(changed, "fotmob")
    assert "shadow-sign-1" in _keys(changed, "mlssoccer")
    assert len(changed["fotmob"]) == 6


def test_club_drop_removes_eight_players_from_the_largest_club():
    squads = _squads()
    squads["fotmob"] += [dict(squads["fotmob"][0], source_player_key=str(100 + i)) for i in range(10)]
    changed = sh.apply("club_drop", squads, _people())
    assert len(changed["fotmob"]) == len(squads["fotmob"]) - 8


def test_apply_never_changes_the_input_squads():
    squads = _squads()
    before = copy.deepcopy(squads)
    sh.apply("departure", squads, _people())
    sh.apply("transfer", squads, _people())
    assert squads == before


def test_the_scope_copy_refuses_to_overwrite_an_existing_file(tmp_path):
    existing = tmp_path / "scope.db"
    existing.write_bytes(b"")
    with pytest.raises(SystemExit):
        sh.build_scope("/nonexistent/picks.db", str(existing))


def test_snapshot_connections_return_rows_by_name(tmp_path):
    con = sh.snapshot_connection(str(tmp_path / "x.db"))
    try:
        row = con.execute("SELECT 1 AS one").fetchone()
        assert row["one"] == 1
    finally:
        con.close()
