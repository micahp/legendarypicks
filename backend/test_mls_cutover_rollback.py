"""Rolling back the MLS cutover restores the pre-cutover identity and snapshot state, and refuses what it must not."""
import json

import pytest

import mls_cutover_rollback as rb
import test_mls_cutover_acceptance as acc


def _state(con):
    return {"players": acc._checksum(con, "players"), "player_source_ids": acc._checksum(con, "player_source_ids"),
            "roster_snapshots": acc._checksum(con, "roster_snapshots"),
            "roster_memberships": acc._checksum(con, "roster_memberships"),
            "published": tuple(con.execute("SELECT id, source_checksum FROM roster_snapshots WHERE league='mls' AND "
                                           "status='published'").fetchone())}


def test_rollback_restores_the_pre_cutover_identity_and_snapshot_state(tmp_path):
    w = acc.World()
    w.cycle(acc.D1)
    before = _state(w.con)
    w.add_pair("m9601", "f9601", "Rollback Signer", "Club01", dob=acc.dob_of(9601))
    cycle = w.cycle(acc.D2)
    assert cycle.onboarded, "the signing must be created by onboarding for this test to mean anything"
    assert _state(w.con) != before

    archive = tmp_path / "cutover-era.json"
    rb.apply(w.con, acc.D2, str(archive))

    assert _state(w.con) == before, "players, bindings, and the published snapshot are exactly as before the cutover"
    archived = json.load(open(archive))
    assert len(archived["snapshots"]) == 1, "the cutover-era snapshot is archived before it is deleted"


def test_rollback_removes_a_rekey_the_cycle_bound_and_keeps_the_original_binding(tmp_path):
    w = acc.World()
    w.cycle(acc.D1)
    w.replace_key("fotmob", "f6", "f6x", dob=acc.dob_of(6))
    cycle = w.cycle(acc.D2)
    assert w.bind_of("fotmob", "f6x") == 6, "the verified rekey is bound by the cycle"
    rb.apply(w.con, acc.D2, str(tmp_path / "a.json"))
    assert w.bind_of("fotmob", "f6x") is None, "the rekey binding the cycle added is removed"
    assert w.bind_of("fotmob", "f6") == 6, "the original binding predates the cutover and stays"


def test_rollback_refuses_when_a_created_player_already_has_props(tmp_path):
    w = acc.World()
    w.cycle(acc.D1)
    w.add_pair("m9602", "f9602", "Has Props", "Club02", dob=acc.dob_of(9602))
    w.cycle(acc.D2)
    pid = w.bind_of("mlssoccer", "m9602")
    w.con.execute("INSERT INTO props(id,game_id,player_id,market,line,side,source,captured_at,odds) "
                  "VALUES(9999,'gx',?,'goals',0.5,'over','book',?,100)", (pid, acc.D2))
    w.con.commit()
    before = _state(w.con)
    with pytest.raises(RuntimeError, match="refused"):
        rb.apply(w.con, acc.D2, str(tmp_path / "b.json"))
    assert _state(w.con) == before, "a refused rollback changes nothing"


def test_a_dry_run_changes_nothing_and_reports_what_would_go(tmp_path):
    w = acc.World()
    w.cycle(acc.D1)
    w.add_pair("m9603", "f9603", "Dry Run", "Club03", dob=acc.dob_of(9603))
    w.cycle(acc.D2)
    before = _state(w.con)
    plan = rb.plan(w.con, acc.D2)
    assert plan["created_players"] and plan["cutover_snapshots"] and not plan["refused"]
    assert _state(w.con) == before
