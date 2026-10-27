"""MLS snapshot: completeness, identity lookup, publication, and what must never change.

Each test builds its own temporary database. Nothing reaches the network or the production database.
"""
import sqlite3

import pytest

import mls_snapshot as ms
import roster_membership as rm

CLUBS = ["Club%02d" % i for i in range(1, 31)]
PER_CLUB = 22
CAPTURED = "2026-10-27T21:13:59+00:00"


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT,
            position TEXT, position_group TEXT, active INT, updated_at TEXT, espn_id TEXT);
        CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT,
            source_player_key TEXT, player_id INT, first_seen TEXT, last_seen TEXT,
            UNIQUE(source, league, source_player_key));
    """)
    rm.create_roster_schema(con)
    return con


def _world():
    """30 clubs of 22 players. Every player appears in both sources, with their own keys, and is bound."""
    con = _db()
    squads = {"mlssoccer": [], "fotmob": []}
    binds = {}
    pid = 0
    for club in CLUBS:
        for i in range(PER_CLUB):
            pid += 1
            name = "Player %s %02d" % (club, i)
            con.execute("INSERT INTO players(id,name,team,league,active) VALUES(?,?,?,?,1)",
                        (pid, name, club, "mls"))
            for source, key in (("mlssoccer", "m%d" % pid), ("fotmob", "f%d" % pid)):
                squads[source].append({"source_player_key": key, "name": name, "team": club,
                                       "position": "M", "jersey": str(i)})
                binds[(source, key)] = pid
    con.commit()
    return con, squads, binds


def _counts(squads):
    return {src: {team: sum(1 for m in members if m["team"] == team) for team in CLUBS}
            for src, members in squads.items()}


def _snapshots(con):
    return [tuple(r) for r in con.execute(
        "SELECT id, status, source_checksum FROM roster_snapshots ORDER BY id")]


def _table_fingerprint(con):
    return {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            for t in ("players", "player_source_ids")}


# --- completeness ------------------------------------------------------------

def test_complete_squads_publish_one_membership_per_person():
    con, squads, binds = _world()
    result = ms.build(squads, binds, captured_at=CAPTURED)
    assert result.status == "publish"
    assert len(result.memberships) == len(CLUBS) * PER_CLUB
    assert len({m["player_id"] for m in result.memberships}) == len(result.memberships)
    assert ms.publish(con, result, CAPTURED) is not None
    assert con.execute("SELECT COUNT(*) FROM roster_memberships").fetchone()[0] == len(result.memberships)


def test_a_missing_club_refuses_and_keeps_the_last_snapshot():
    con, squads, binds = _world()
    first = ms.build(squads, binds, captured_at=CAPTURED)
    ms.publish(con, first, CAPTURED)
    before = _snapshots(con)
    squads["fotmob"] = [m for m in squads["fotmob"] if m["team"] != "Club07"]
    result = ms.build(squads, binds, prior_counts=_counts(squads), captured_at=CAPTURED)
    assert result.status == "refused"
    assert any("Club07" in r or "clubs" in r for r in result.reasons)
    assert ms.publish(con, result, CAPTURED) is None
    assert _snapshots(con) == before, "a refused fetch leaves the current snapshot untouched"


def test_a_club_losing_too_many_players_is_refused_but_a_transfer_is_not():
    con, squads, binds = _world()
    ms.publish(con, ms.build(squads, binds, captured_at=CAPTURED), CAPTURED)
    prior = _counts(squads)
    drop = [m for m in squads["mlssoccer"] if m["team"] == "Club03"][:8]
    for member in drop:
        squads["mlssoccer"].remove(member)
    result = ms.build(squads, binds, prior_counts=prior, captured_at=CAPTURED)
    assert result.status == "refused", "eight players leaving one club is not a transfer"

    con2, squads2, binds2 = _world()
    prior2 = _counts(squads2)
    mover = [m for m in squads2["mlssoccer"] if m["team"] == "Club03"][0]
    squads2["mlssoccer"].remove(mover)
    mover = dict(mover, team="Club04")
    squads2["mlssoccer"].append(mover)
    squads2["fotmob"] = [dict(m, team="Club04") if m["source_player_key"] == "f%s" % binds2[("mlssoccer", mover["source_player_key"])] else m
                         for m in squads2["fotmob"]]
    result2 = ms.build(squads2, binds2, prior_counts=prior2, captured_at=CAPTURED)
    assert result2.status == "publish", result2.reasons


# --- identity -----------------------------------------------------------------

def test_a_namesake_without_a_bind_is_a_blocker_and_is_never_bound():
    con, squads, binds = _world()
    ms.publish(con, ms.build(squads, binds, captured_at=CAPTURED), CAPTURED)
    before = _table_fingerprint(con)
    squads["mlssoccer"].append({"source_player_key": "m9999", "name": "Player Club05 00",
                                "team": "Club09", "position": "M", "jersey": "99"})
    result = ms.build(squads, binds, prior_counts=_counts(squads), captured_at=CAPTURED)
    assert result.status == "publish"
    assert [b["source_player_key"] for b in result.blockers] == ["m9999"]
    assert all(m["player_id"] != 0 for m in result.memberships)
    ms.publish(con, result, CAPTURED)
    assert _table_fingerprint(con) == before, "no player or bind is created for the namesake"


def test_a_rekey_is_only_linked_by_an_explicit_bind():
    con, squads, binds = _world()
    player = 1
    squads["mlssoccer"][0] = dict(squads["mlssoccer"][0], source_player_key="m-new")
    unbound = ms.build(squads, binds, captured_at=CAPTURED)
    assert unbound.status == "publish"
    assert [b["source_player_key"] for b in unbound.blockers] == ["m-new"]
    binds[("mlssoccer", "m-new")] = player  # an explicit, reviewed mapping
    linked = ms.build(squads, binds, captured_at=CAPTURED)
    assert linked.status == "publish" and not linked.blockers
    assert sum(1 for m in linked.memberships if m["player_id"] == player) == 1


def test_two_keys_from_one_source_for_one_person_refuse():
    con, squads, binds = _world()
    binds[("mlssoccer", "m-extra")] = 1
    squads["mlssoccer"].append({"source_player_key": "m-extra", "name": "Player Club01 00",
                                "team": "Club01", "position": "M", "jersey": "0"})
    result = ms.build(squads, binds, captured_at=CAPTURED)
    assert result.status == "refused"
    assert any(c["reason"] == "two keys from mlssoccer" for c in result.blockers)


def test_sources_that_disagree_on_a_club_refuse():
    con, squads, binds = _world()
    fkey = "f1"
    squads["fotmob"] = [dict(m, team="Club30") if m["source_player_key"] == fkey else m for m in squads["fotmob"]]
    result = ms.build(squads, binds, captured_at=CAPTURED)
    assert result.status == "refused"
    assert any(c["reason"] == "sources disagree on club" for c in result.blockers)


# --- publication and history ---------------------------------------------------

def test_repeated_ingestion_of_the_same_population_publishes_nothing_new():
    con, squads, binds = _world()
    assert ms.publish(con, ms.build(squads, binds, captured_at=CAPTURED), CAPTURED) is not None
    again = ms.build(squads, binds, prior_counts=_counts(squads), captured_at=CAPTURED)
    assert ms.publish(con, again, CAPTURED) is None
    assert len([s for s in _snapshots(con) if s[1] == "published"]) == 1


def test_a_transfer_moves_the_membership_and_keeps_the_old_snapshot():
    con, squads, binds = _world()
    first = ms.build(squads, binds, captured_at=CAPTURED)
    old_id = ms.publish(con, first, CAPTURED)
    prior_members = [dict(m) for m in first.memberships]
    prior = _counts(squads)
    player = 1
    for src in ("mlssoccer", "fotmob"):
        key = "m1" if src == "mlssoccer" else "f1"
        squads[src] = [dict(m, team="Club02") if m["source_player_key"] == key else m for m in squads[src]]
    second = ms.build(squads, binds, prior_counts=prior, prior_memberships=prior_members, captured_at="2026-10-28T21:13:00+00:00")
    assert second.status == "publish", second.reasons
    new_id = ms.publish(con, second, "2026-10-28T21:13:00+00:00")
    assert new_id and new_id != old_id
    old_team = con.execute("SELECT team FROM roster_memberships WHERE snapshot_id=? AND player_id=?",
                           (old_id, player)).fetchone()[0]
    new_team = con.execute("SELECT team FROM roster_memberships WHERE snapshot_id=? AND player_id=?",
                           (new_id, player)).fetchone()[0]
    assert (old_team, new_team) == ("Club01", "Club02")
    assert con.execute("SELECT status FROM roster_snapshots WHERE id=?", (old_id,)).fetchone()[0] == "superseded"


def test_a_known_key_that_is_unbound_but_whose_person_is_still_resolved_is_neither_blocker_nor_carry():
    con, squads, binds = _world()
    first = ms.build(squads, binds, captured_at=CAPTURED)
    ms.publish(con, first, CAPTURED)
    del binds[("mlssoccer", "m5")]  # the fotmob key f5 still resolves player 5
    result = ms.build(squads, binds, prior_counts=_counts(squads), prior_memberships=first.memberships,
                      captured_at=CAPTURED)
    assert result.status == "publish"
    assert not result.blockers and not result.carried
    assert sum(1 for m in result.memberships if m["player_id"] == 5) == 1


def test_a_known_person_with_no_bound_key_left_is_carried_not_deactivated():
    con, squads, binds = _world()
    first = ms.build(squads, binds, captured_at=CAPTURED)
    ms.publish(con, first, CAPTURED)
    del binds[("mlssoccer", "m5")]
    del binds[("fotmob", "f5")]
    result = ms.build(squads, binds, prior_counts=_counts(squads), prior_memberships=ms.load_prior(con),
                      captured_at=CAPTURED)
    assert result.status == "publish"
    assert not result.blockers
    assert sorted(c["source_player_key"] for c in result.carried) == ["m5"]
    assert any(m["player_id"] == 5 and m["roster_status"] == "carried" for m in result.memberships)


# --- Leagues Cup ----------------------------------------------------------------

def test_leagues_cup_keys_resolve_to_the_home_player_without_new_identities():
    con, squads, binds = _world()
    binds[("fotmob", "lcup-only-1738398")] = 1  # a Leagues Cup key bound to an MLS player
    before = _table_fingerprint(con)
    result = ms.build(squads, binds, captured_at=CAPTURED)
    assert result.status == "publish"
    ms.publish(con, result, CAPTURED)
    assert _table_fingerprint(con) == before
    assert sum(1 for m in result.memberships if m["player_id"] == 1) == 1
