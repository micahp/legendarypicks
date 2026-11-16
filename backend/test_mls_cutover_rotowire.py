"""RotoWire props for MLS under the cutover: a departed person is never returned, by name or by an old binding.

RotoWire's resolver matched names against players and their stored club, and bound keys by name. Under the cutover
it answers from the membership snapshot and writes no binding from a name match.
"""
import mls_resolution
import ingest_rotowire_props as rw
from test_mls_cutover_acceptance import D1, D2, World, _count


def _row(name, key):
    return {"player_name": name, "source_player_key": key, "position": "M"}


def _capture(monkeypatch):
    queued = []
    monkeypatch.setattr(rw, "queue_unresolved",
                        lambda con, league, row, now, reason: queued.append((row["source_player_key"], reason)))
    return queued


def _bind_rotowire(w, key, pid):
    w.con.execute("INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
                  "VALUES('rotowire','mls',?,?,?,?)", (key, pid, D1, D1))


def test_a_departed_person_is_not_returned_by_name_or_by_an_old_binding(monkeypatch):
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, "1")
    w = World()
    w.cycle(D1)
    name, club = w.name_of(3), w.team_of(3)
    _bind_rotowire(w, "r3", 3)
    w.drop_person(3)
    w.cycle(D2)
    queued = _capture(monkeypatch)
    players_before = _count(w.con, "players")
    binds_before = _count(w.con, "player_source_ids")

    assert rw.resolve_player(w.con, "mls", _row(name, "r3"), D2, club) is None
    assert rw.resolve_player(w.con, "mls", _row(name, "r99"), D2, club) is None
    assert queued == [("r3", "not_in_spine"), ("r99", "not_in_spine")]
    assert _count(w.con, "players") == players_before
    assert _count(w.con, "player_source_ids") == binds_before


def test_a_current_member_resolves_by_name_and_no_binding_is_written(monkeypatch):
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, "1")
    w = World()
    w.cycle(D1)
    name, club = w.name_of(4), w.team_of(4)
    queued = _capture(monkeypatch)
    binds_before = _count(w.con, "player_source_ids")

    assert rw.resolve_player(w.con, "mls", _row(name, "r4"), D2, club) == 4
    assert queued == []
    assert _count(w.con, "player_source_ids") == binds_before, "a name match is never written as a binding"


def test_a_current_member_keeps_an_existing_binding_under_another_spelling(monkeypatch):
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, "1")
    w = World()
    w.cycle(D1)
    _bind_rotowire(w, "r5", 5)
    _capture(monkeypatch)

    assert rw.resolve_player(w.con, "mls", _row("A Different Spelling", "r5"), D2, w.team_of(5)) == 5


def test_with_the_cutover_off_the_name_rule_is_the_legacy_one(monkeypatch):
    """The control: the same departed person resolves by name when the gate is off. The gate is the only change."""
    monkeypatch.delenv(mls_resolution.CUTOVER_ENV, raising=False)
    w = World()
    w.cycle(D1)
    name, club = w.name_of(3), w.team_of(3)
    w.drop_person(3)
    w.cycle(D2)
    _capture(monkeypatch)

    assert rw.resolve_player(w.con, "mls", _row(name, "r3"), D2, club) == 3
