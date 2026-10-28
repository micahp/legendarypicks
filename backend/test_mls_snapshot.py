"""MLS snapshot: completeness, identity lookup, transitions, publication, and failure paths.

Every test builds its own temporary database. Nothing touches the network or production.
"""
import json
import sqlite3

import pytest

import mls_snapshot as ms
import roster_membership as rm

CLUBS = ["Club%02d" % i for i in range(1, 31)]
PER_CLUB = 22
T1 = "2026-10-27T21:13:59+00:00"
T2 = "2026-10-28T21:13:59+00:00"


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
    """30 clubs of 22 people. Each person has an mlssoccer key and a fotmob key, both bound."""
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
                con.execute("INSERT INTO player_source_ids(source,league,source_player_key,player_id,"
                            "first_seen,last_seen) VALUES(?,'mls',?,?,'now','now')", (source, key, pid))
                binds[(source, key)] = pid
    con.commit()
    return con, squads, binds


def _publish(con, squads, binds, captured_at=T1):
    result = ms.build(con, squads, binds, captured_at=captured_at)
    outcome, snapshot_id = ms.publish(con, result, captured_at) if result.status == "publish" else ("refused", None)
    con.commit()
    return result, outcome, snapshot_id


def _published_count(con):
    return con.execute("SELECT COUNT(*) FROM roster_snapshots WHERE status='published'").fetchone()[0]


def _fingerprint(con):
    return {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            for t in ("players", "player_source_ids")}


# --- completeness ----------------------------------------------------------------

def test_complete_squads_publish_one_verified_membership_per_person():
    con, squads, binds = _world()
    result, outcome, snapshot_id = _publish(con, squads, binds)
    assert outcome == "published"
    assert result.coverage == "verified"
    assert len(result.memberships) == 30 * PER_CLUB
    assert len({m["player_id"] for m in result.memberships}) == len(result.memberships)
    assert con.execute("SELECT COUNT(*) FROM roster_memberships WHERE snapshot_id=?",
                       (snapshot_id,)).fetchone()[0] == 30 * PER_CLUB


def test_a_missing_club_refuses_and_the_current_snapshot_stays():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    before = _published_count(con), con.execute(
        "SELECT source_checksum FROM roster_snapshots WHERE status='published'").fetchone()[0]
    squads["fotmob"] = [m for m in squads["fotmob"] if m["team"] != "Club07"]
    result, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    assert result.status == "refused" and outcome == "refused"
    assert any("Club07" in r or "clubs" in r for r in result.reasons)
    after = _published_count(con), con.execute(
        "SELECT source_checksum FROM roster_snapshots WHERE status='published'").fetchone()[0]
    assert after == before


def test_eight_players_leaving_one_club_refuses_but_a_transfer_publishes():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    leavers = [m for m in squads["mlssoccer"] if m["team"] == "Club03"][:8]
    for m in leavers:
        squads["mlssoccer"].remove(m)
    result, _, _ = _publish(con, squads, binds, captured_at=T2)
    assert result.status == "refused"

    con2, squads2, binds2 = _world()
    _publish(con2, squads2, binds2)
    key = "m1"
    squads2["mlssoccer"] = [dict(m, team="Club02") if m["source_player_key"] == key else m
                            for m in squads2["mlssoccer"]]
    squads2["fotmob"] = [dict(m, team="Club02") if m["source_player_key"] == "f1" else m
                         for m in squads2["fotmob"]]
    result2, outcome2, _ = _publish(con2, squads2, binds2, captured_at=T2)
    assert result2.status == "publish", result2.reasons
    assert [t["player_id"] for t in result2.transfers] == [1]
    assert result2.coverage == "verified"


# --- identity -------------------------------------------------------------------

def test_a_namesake_without_a_bind_is_a_blocker_and_is_never_bound():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    before = _fingerprint(con)
    squads["mlssoccer"].append({"source_player_key": "m9999", "name": "Player Club05 00",
                                "team": "Club09", "position": "M", "jersey": "99"})
    result, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    # A blocker is not a membership, so the population is unchanged. The stored events and coverage still record it.
    assert outcome == "unchanged"
    assert result.coverage == "partial"
    assert [b["source_player_key"] for b in result.blockers] == ["m9999"]
    stored = json.loads(con.execute(
        "SELECT source_payload FROM roster_snapshots WHERE status='published'").fetchone()[0])
    assert stored["coverage"]["status"] == "partial"
    assert [b["source_player_key"] for b in stored["blockers"]] == ["m9999"]
    assert _fingerprint(con) == before, "no player or bind created for the namesake"


def test_a_rekey_links_only_through_an_explicit_bind():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    squads["mlssoccer"][0] = dict(squads["mlssoccer"][0], source_player_key="m-new")  # player 1's new key
    del binds[("mlssoccer", "m1")]
    unbound = ms.build(con, squads, binds, captured_at=T2)
    assert unbound.coverage == "partial"
    assert [b["source_player_key"] for b in unbound.blockers] == ["m-new"]
    assert [m for m in unbound.memberships if m["player_id"] == 1]  # still present through fotmob f1

    binds[("mlssoccer", "m-new")] = 1  # an explicit, reviewed mapping
    linked = ms.build(con, squads, binds, captured_at=T2)
    assert linked.coverage == "verified"
    assert linked.rekeys == [{"player_id": 1, "source": "mlssoccer", "from": "m1", "to": "m-new"}]


# A dispute holds the one disputed person at the club of the last verified snapshot. It never refuses the league, and
# it is never silently resolved. (These three tests replaced the earlier whole-league refusals, per the cutover contract.)

def test_two_keys_from_one_source_for_one_person_hold_that_person_not_the_league():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    binds[("mlssoccer", "m-extra")] = 1
    squads["mlssoccer"].append({"source_player_key": "m-extra", "name": "Player Club01 00",
                                "team": "Club01", "position": "M", "jersey": "0"})
    result, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    assert result.status == "publish" and outcome == "published"
    assert result.coverage == "partial"
    assert any(c["player_id"] == 1 and c["held"] for c in result.conflicts)
    held = {m["player_id"]: m for m in result.memberships}[1]
    assert held["roster_status"] == "held" and held["team"] == "Club01"
    assert len(result.memberships) == 30 * 22, "every other person is still updated"


def test_sources_that_disagree_on_a_club_hold_only_that_person():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    squads["fotmob"] = [dict(m, team="Club30") if m["source_player_key"] == "f1" else m for m in squads["fotmob"]]
    result, outcome, _ = _publish(con, squads, binds, captured_at=T2)
    assert result.status == "publish" and outcome == "published"
    assert result.coverage == "partial"
    assert [h["player_id"] for h in result.held] == [1]
    held = {m["player_id"]: m for m in result.memberships}[1]
    assert held["roster_status"] == "held" and held["team"] == "Club01"


def test_a_bind_that_moved_to_another_person_is_held_and_flagged_not_silently_followed():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    binds[("mlssoccer", "m1")] = 2  # m1 now points at person 2, who already has mlssoccer m2
    result = ms.build(con, squads, binds, captured_at=T2)
    assert result.status == "publish"
    assert result.coverage == "partial"
    assert any(c["player_id"] == 2 for c in result.conflicts), "two mlssoccer keys for person 2 are a dispute"
    assert [s["player_id"] for s in result.source_lost] == [1], "person 1 lost the mlssoccer key that moved"


# --- transitions: collisions, departures, carry-forward ----------------------------

def test_carry_forward_is_namespaced_by_source_so_a_numeric_collision_cannot_cross_people():
    con, squads, binds = _world()
    # Person 1 is known as fotmob 777. Person 2 is known as mlssoccer 777. The same digits, two people.
    squads["fotmob"] = [dict(m, source_player_key="777") if m["source_player_key"] == "f1" else m for m in squads["fotmob"]]
    squads["mlssoccer"] = [dict(m, source_player_key="777") if m["source_player_key"] == "m2" else m for m in squads["mlssoccer"]]
    del binds[("fotmob", "f1")], binds[("mlssoccer", "m2")]
    binds[("fotmob", "777")] = 1
    binds[("mlssoccer", "777")] = 2
    _publish(con, squads, binds)

    # Person 1 leaves the mlssoccer squad, and fotmob 777 is unbound this run. Only fotmob 777 can say who
    # person 1 was, so it must carry person 1, not person 2.
    squads["mlssoccer"] = [m for m in squads["mlssoccer"] if m["source_player_key"] != "m1"]
    del binds[("mlssoccer", "m1")], binds[("fotmob", "777")]
    result = ms.build(con, squads, binds, captured_at=T2)
    assert [c["source"] for c in result.carried] == ["fotmob"]
    carried_people = {m["player_id"] for m in result.memberships if m["roster_status"] == "carried"}
    assert carried_people == {1}, "fotmob 777 must carry person 1, not person 2"
    assert result.coverage == "partial"


def test_a_person_who_leaves_both_sources_is_a_confirmed_departure():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    squads["mlssoccer"] = [m for m in squads["mlssoccer"] if m["source_player_key"] != "m5"]
    squads["fotmob"] = [m for m in squads["fotmob"] if m["source_player_key"] != "f5"]
    result = ms.build(con, squads, binds, captured_at=T2)
    assert [d["player_id"] for d in result.departures] == [5]
    assert result.coverage == "verified"


def test_a_person_seen_by_one_source_only_who_disappears_is_flagged_for_review():
    con, squads, binds = _world()
    del binds[("fotmob", "f5")]
    squads["fotmob"] = [m for m in squads["fotmob"] if m["source_player_key"] != "f5"]
    _publish(con, squads, binds)  # person 5 is known only through mlssoccer m5
    squads["mlssoccer"] = [m for m in squads["mlssoccer"] if m["source_player_key"] != "m5"]
    result = ms.build(con, squads, binds, captured_at=T2)
    assert [s["player_id"] for s in result.single_source_departures] == [5]
    assert result.coverage == "partial"


def test_a_known_person_with_no_bound_key_left_is_carried_not_dropped():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    del binds[("mlssoccer", "m5")], binds[("fotmob", "f5")]
    result = ms.build(con, squads, binds, captured_at=T2)
    assert result.coverage == "partial"
    assert not result.blockers
    assert any(m["player_id"] == 5 and m["roster_status"] == "carried" for m in result.memberships)


# --- publication and repeated runs ------------------------------------------------

def test_the_same_population_on_another_day_refreshes_the_timestamp_and_creates_nothing_new():
    con, squads, binds = _world()
    _, first_outcome, first_id = _publish(con, squads, binds, captured_at=T1)
    assert first_outcome == "published"
    _, second_outcome, second_id = _publish(con, squads, binds, captured_at=T2)
    assert second_outcome == "unchanged" and second_id == first_id
    assert _published_count(con) == 1
    assert con.execute("SELECT captured_at FROM roster_snapshots WHERE id=?", (first_id,)).fetchone()[0] == T2
    assert con.execute("SELECT COUNT(*) FROM roster_memberships WHERE snapshot_id=?",
                       (first_id,)).fetchone()[0] == 30 * PER_CLUB


def test_the_fetch_order_of_the_providers_cannot_change_the_checksum():
    con, squads, binds = _world()
    first = ms.build(con, squads, binds, captured_at=T1)
    shuffled = {k: list(reversed(v)) for k, v in squads.items()}
    second = ms.build(con, shuffled, binds, captured_at=T1)
    assert first.checksum == second.checksum


def test_health_reports_what_the_current_snapshot_says_about_itself():
    con, squads, binds = _world()
    _publish(con, squads, binds)
    assert ms.health(con)["coverage"] == "verified"
    squads["mlssoccer"].append({"source_player_key": "m9999", "name": "Nobody", "team": "Club09",
                                "position": "M", "jersey": "9"})
    _publish(con, squads, binds, captured_at=T2)
    h = ms.health(con)
    assert h["coverage"] == "partial" and h["blockers"] == 1


# --- Leagues Cup: the real cross-competition lookup ------------------------------------

def test_leagues_cup_keys_resolve_through_the_database_lookup_to_the_home_mls_person():
    con, squads, binds = _world()
    con.execute("INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
                "VALUES('fotmob','lcup','f1',1,'now','now')")
    con.commit()
    db_binds = ms.binds_from_db(con)
    assert db_binds[("fotmob", "f1")] == 1
    before = _fingerprint(con)
    result, outcome, _ = _publish(con, squads, db_binds)
    assert outcome == "published"
    assert _fingerprint(con) == before, "Leagues Cup adds no player and no bind"
    team = [m["team"] for m in result.memberships if m["player_id"] == 1][0]
    assert team == "Club01", "the membership keeps the MLS club, never a competition"


def test_a_leagues_cup_key_bound_to_a_different_person_is_a_bind_disagreement():
    con, squads, binds = _world()
    con.execute("INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
                "VALUES('fotmob','lcup','f1',2,'now','now')")  # f1 is person 1 in mls, person 2 in lcup
    con.commit()
    with pytest.raises(ValueError, match="bind disagreement"):
        ms.binds_from_db(con)
