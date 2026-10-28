"""Repeated runs after each kind of transition publish nothing new.

A transition is reported on the run that sees it. The next run with the same squads must refresh the stored events
and create no second membership set. Before the population checksum covered only memberships, a transfer was
followed by an identical second snapshot.
"""
import json

from test_mls_snapshot import T1, T2, _publish, _world

T3 = "2026-10-29T21:13:59+00:00"
T4 = "2026-10-30T21:13:59+00:00"


def _snapshots(con):
    return con.execute("SELECT COUNT(*) FROM roster_snapshots WHERE league='mls'").fetchone()[0]


def _stored_events(con):
    payload = json.loads(con.execute(
        "SELECT source_payload FROM roster_snapshots WHERE league='mls' AND status='published'").fetchone()[0])
    return {key: payload[key] for key in ("transfers", "departures", "rekeys", "single_source_departures", "carried")}


def _move(squads, pid, club):
    for source, key in (("mlssoccer", "m%d" % pid), ("fotmob", "f%d" % pid)):
        squads[source] = [dict(m, team=club) if m["source_player_key"] == key else m for m in squads[source]]


def _drop(squads, pid):
    for source, key in (("mlssoccer", "m%d" % pid), ("fotmob", "f%d" % pid)):
        squads[source] = [m for m in squads[source] if m["source_player_key"] != key]


def _repeat_quietly(con, squads, binds, days):
    for day in days:
        _, outcome, _ = _publish(con, squads, binds, captured_at=day)
        assert outcome == "unchanged", "a repeat of the same squads must publish nothing (got %s)" % outcome


def test_a_transfer_is_published_once_and_its_repeats_publish_nothing():
    con, squads, binds = _world()
    _publish(con, squads, binds, captured_at=T1)
    _move(squads, 1, "Club02")

    result, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    assert outcome == "published"
    assert [t["player_id"] for t in result.transfers] == [1]
    assert _snapshots(con) == 2

    _repeat_quietly(con, squads, binds, (T3, T4))
    assert _snapshots(con) == 2
    assert _stored_events(con)["transfers"] == [], "the stored events must describe the latest run"


def test_a_departure_is_published_once_and_its_repeats_publish_nothing():
    con, squads, binds = _world()
    _publish(con, squads, binds, captured_at=T1)
    _drop(squads, 5)
    del binds[("mlssoccer", "m5")], binds[("fotmob", "f5")]

    result, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    assert outcome == "published"
    assert [d["player_id"] for d in result.departures] == [5]

    _repeat_quietly(con, squads, binds, (T3, T4))
    assert _snapshots(con) == 2
    assert _stored_events(con)["departures"] == []


def test_a_rekey_is_published_once_and_its_repeats_publish_nothing():
    con, squads, binds = _world()
    _publish(con, squads, binds, captured_at=T1)
    squads["fotmob"] = [dict(m, source_player_key="f6x") if m["source_player_key"] == "f6" else m
                        for m in squads["fotmob"]]
    del binds[("fotmob", "f6")]
    binds[("fotmob", "f6x")] = 6

    result, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    assert outcome == "published"
    assert [r["player_id"] for r in result.rekeys] == [6]

    _repeat_quietly(con, squads, binds, (T3, T4))
    assert _snapshots(con) == 2
    assert _stored_events(con)["rekeys"] == []


def test_a_key_lost_by_one_source_then_the_person_leaving_is_published_once_and_repeats_quietly():
    con, squads, binds = _world()
    _publish(con, squads, binds, captured_at=T1)
    squads["fotmob"] = [m for m in squads["fotmob"] if m["source_player_key"] != "f7"]
    del binds[("fotmob", "f7")]
    _, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    assert outcome == "published"

    squads["mlssoccer"] = [m for m in squads["mlssoccer"] if m["source_player_key"] != "m7"]
    del binds[("mlssoccer", "m7")]
    result, outcome, _ = _publish(con, squads, binds, captured_at=T3)
    assert outcome == "published"
    assert [s["player_id"] for s in result.single_source_departures] == [7]
    assert result.coverage == "partial"

    _repeat_quietly(con, squads, binds, (T4, "2026-10-31T21:13:59+00:00"))
    assert _snapshots(con) == 3
    assert _stored_events(con)["single_source_departures"] == []


def test_a_carried_person_repeats_quietly_for_as_long_as_the_key_stays_unbound():
    con, squads, binds = _world()
    _publish(con, squads, binds, captured_at=T1)
    del binds[("mlssoccer", "m8")], binds[("fotmob", "f8")]

    result, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    assert outcome == "published"
    assert any(m["player_id"] == 8 and m["roster_status"] == "carried" for m in result.memberships)
    # Both keys are unbound. The person is carried once: the second key adds nothing, because the person is already here.
    assert len(result.carried) == 1

    _repeat_quietly(con, squads, binds, (T3, T4))
    assert _snapshots(con) == 2
    assert len(_stored_events(con)["carried"]) == 1, "the carry is still happening, so it stays reported"
