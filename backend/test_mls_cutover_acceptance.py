"""MLS cutover acceptance: the contract for replacing the legacy MLS roster path.

Real SQLite schemas, the real snapshot publication path, and the real ingest resolver. The external date-of-birth
lookups are fakes, because they are HTTP. The identity logic under test is not faked.
"""
import copy
import datetime as dt
import json
import os
import sqlite3

import pytest

import _core
import published_roster
import roster_membership as rm

try:
    import mls_identity
    import mls_resolution
    import mls_roster
    import mls_snapshot as ms
except ImportError:  # the implementation is written after these tests: each test then fails on its own call
    mls_identity = mls_resolution = mls_roster = None
    import mls_snapshot as ms

HERE = os.path.dirname(os.path.abspath(__file__))
REGRESSION = os.path.join(HERE, "fixtures", "mls_regression_2026-10-27.json")
CUTOVER = os.path.join(HERE, "fixtures", "mls_cutover_2026-10-28.json")

CLUBS = ["Club%02d" % i for i in range(1, 31)]
PER_CLUB = 22
D1 = "2026-10-27T21:13:59+00:00"
D2 = "2026-10-28T09:00:00+00:00"
D3 = "2026-10-29T09:00:00+00:00"
D4 = "2026-10-30T09:00:00+00:00"
D5 = "2026-10-31T09:00:00+00:00"
PROTECTED = ("player_game_logs", "props", "prop_results", "settlement_attempts", "team_game_results")

SCHEMA = """
CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, position TEXT,
    position_group TEXT, active INT, updated_at TEXT);
CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY, source TEXT, league TEXT, source_player_key TEXT,
    player_id INT, first_seen TEXT, last_seen TEXT, UNIQUE(source, league, source_player_key));
CREATE TABLE name_alias(id INTEGER PRIMARY KEY, alias_norm TEXT, player_id INT);
CREATE TABLE player_game_logs(id INTEGER PRIMARY KEY, player_id INT, league TEXT, season INT, game_no INT,
    game_id TEXT, game_date TEXT, team TEXT, opponent TEXT, stats TEXT, source TEXT, source_player_key TEXT);
CREATE TABLE props(id INTEGER PRIMARY KEY, game_id TEXT, player_id INT, market TEXT, line REAL, side TEXT,
    source TEXT, captured_at TEXT, odds INT);
CREATE TABLE prop_results(prop_id INT PRIMARY KEY, actual_value REAL, hit INT, settled_at TEXT);
CREATE TABLE settlement_attempts(id INTEGER PRIMARY KEY, prop_id INT, game_id TEXT, attempted_at TEXT,
    stage TEXT, terminal INT, reason TEXT, actual_value REAL, hit INT);
CREATE TABLE team_game_results(id INTEGER PRIMARY KEY, team TEXT, game_id TEXT, points INT);
"""


def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    rm.create_roster_schema(con)
    published_roster.ensure(con)
    if mls_identity is not None:
        mls_identity.ensure_schema(con)
    con.commit()
    return con


def _name_team(con, pid):
    return con.execute("SELECT name, team FROM players WHERE id=?", (pid,)).fetchone()


def dob_of(pid):
    return (dt.date(1980, 1, 1) + dt.timedelta(days=37 * pid)).isoformat()


def _count(con, table):
    return con.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


def _checksum(con, table):
    import hashlib
    digest = hashlib.sha256()
    for row in con.execute("SELECT * FROM %s ORDER BY rowid" % table):
        digest.update(repr(tuple(row)).encode("utf-8"))
    return digest.hexdigest()


class World:
    """30 clubs of 22 people, each with an mlssoccer key and a fotmob key, plus one MLS-only person.

    Every person has one game log, one prop, one prop result, one settlement attempt, and one team game result, so
    the protected-table checks have rows to protect.
    """

    def __init__(self):
        self.con = _db()
        self.squads = {"mlssoccer": [], "fotmob": []}
        self.dobs = {}  # (source, key) -> dates the independent lookup reports
        pid = 0
        for club in CLUBS:
            for i in range(PER_CLUB):
                pid += 1
                self._person(pid, "Player %s %02d" % (club, i), club, i, both=True)
        self._person(901, "Solo Holder", "Club03", 99, both=False)
        self.con.commit()

    def _person(self, pid, name, club, i, both):
        self.con.execute("INSERT INTO players(id,name,team,league,position,position_group,active,updated_at) "
                         "VALUES(?,?,?,?,?,?,1,?)", (pid, name, club, "mls", "M", "midfield", D1))
        keys = [("mlssoccer", "m%d" % pid)] + ([("fotmob", "f%d" % pid)] if both else [])
        for source, key in keys:
            self.squads[source].append({"source": source, "source_player_key": key, "name": name,
                                        "names": [name], "team": club, "position": "M",
                                        "position_group": "midfield", "jersey": str(i)})
            self._bind(source, key, pid)
            self.dobs[(source, key)] = [dob_of(pid)]
        self.con.execute("INSERT INTO player_game_logs(player_id,league,season,game_no,game_id,game_date,team,"
                         "opponent,stats,source,source_player_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (pid, "mls", 2026, 1, "g%d" % pid, "2026-03-01", club, "Opp", "{}", "fixture", str(pid)))
        self.con.execute("INSERT INTO props(id,game_id,player_id,market,line,side,source,captured_at,odds) "
                         "VALUES(?,?,?,?,?,?,?,?,?)", (pid, "g%d" % pid, pid, "goals", 0.5, "over", "book", D1, 100))
        self.con.execute("INSERT INTO prop_results(prop_id,actual_value,hit,settled_at) VALUES(?,?,?,?)",
                         (pid, 1, 1, D1))
        self.con.execute("INSERT INTO settlement_attempts(prop_id,game_id,attempted_at,stage,terminal,reason,"
                         "actual_value,hit) VALUES(?,?,?,?,?,?,?,?)", (pid, "g%d" % pid, D1, "final", 1, "ok", 1, 1))
        self.con.execute("INSERT INTO team_game_results(team,game_id,points) VALUES(?,?,?)",
                         (club, "g%d" % pid, 1))

    def _bind(self, source, key, pid):
        self.con.execute("INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,"
                         "last_seen) VALUES(?,'mls',?,?,?,?)", (source, key, pid, D1, D1))

    # --- the publisher side -------------------------------------------------------------

    def lookup(self, source, key):
        return self.dobs.get((source, key))

    def add_pair(self, mkey, fkey, name, club, dob):
        self.squads["mlssoccer"].append({"source": "mlssoccer", "source_player_key": mkey, "name": name,
                                         "names": [name], "team": club, "position": "M",
                                         "position_group": "midfield", "jersey": "0"})
        self.squads["fotmob"].append({"source": "fotmob", "source_player_key": fkey, "name": name,
                                      "names": [name], "team": club, "position": "M",
                                      "position_group": "midfield", "jersey": "0"})
        self.dobs[("mlssoccer", mkey)] = [dob]
        self.dobs[("fotmob", fkey)] = [dob]

    def add_single(self, mkey, name, club, dob):
        self.squads["mlssoccer"].append({"source": "mlssoccer", "source_player_key": mkey, "name": name,
                                         "names": [name], "team": club, "position": "M",
                                         "position_group": "midfield", "jersey": "0"})
        self.dobs[("mlssoccer", mkey)] = [dob]

    def move(self, pid, club):
        for source, key in (("mlssoccer", "m%d" % pid), ("fotmob", "f%d" % pid)):
            for row in self.squads[source]:
                if row["source_player_key"] == key:
                    row["team"] = club

    def set_club(self, source, key, club):
        for row in self.squads[source]:
            if str(row["source_player_key"]) == key:
                row["team"] = club

    def drop(self, source, key):
        self.squads[source] = [r for r in self.squads[source] if str(r["source_player_key"]) != key]

    def drop_person(self, pid):
        self.drop("mlssoccer", "m%d" % pid)
        self.drop("fotmob", "f%d" % pid)

    def replace_key(self, source, old, new, dob):
        for row in self.squads[source]:
            if str(row["source_player_key"]) == old:
                row["source_player_key"] = new
        self.dobs[(source, new)] = [dob]

    def rebind(self, source, old, new, pid):
        """Publisher reuses a number: the old key is gone and a different publisher key takes the same digits."""
        self.drop(source, old)
        self.con.execute("DELETE FROM player_source_ids WHERE source=? AND league='mls' AND source_player_key=?",
                         (source, old))
        self.squads[source].append({"source": source, "source_player_key": new,
                                    "name": self.name_of(pid), "names": [self.name_of(pid)],
                                    "team": self.team_of(pid), "position": "M", "position_group": "midfield",
                                    "jersey": "0"})
        self._bind(source, new, pid)
        self.dobs[(source, new)] = [dob_of(pid)]

    # --- our side ------------------------------------------------------------------------

    def cycle(self, when, lookup=True):
        return mls_roster.run_cycle(self.con, self.squads, captured_at=when,
                                    lookup=self.lookup if lookup else None)

    def name_of(self, pid):
        return self.con.execute("SELECT name FROM players WHERE id=?", (pid,)).fetchone()[0]

    def team_of(self, pid):
        return self.con.execute("SELECT team FROM players WHERE id=?", (pid,)).fetchone()[0]

    def binds(self):
        return {(s, k): p for s, k, p in self.con.execute(
            "SELECT source, source_player_key, player_id FROM player_source_ids WHERE league='mls'")}

    def bind_of(self, source, key):
        row = self.con.execute("SELECT player_id FROM player_source_ids WHERE source=? AND league='mls' "
                               "AND source_player_key=?", (source, key)).fetchone()
        return row[0] if row else None

    def current_snapshot(self):
        return self.con.execute("SELECT id, captured_at, source_checksum FROM roster_snapshots "
                                "WHERE league='mls' AND status='published'").fetchone()

    def members(self):
        snap = self.current_snapshot()
        return {r[0]: {"team": r[1], "status": r[2], "keys": r[3]} for r in self.con.execute(
            "SELECT player_id, team, roster_status, source_player_key FROM roster_memberships WHERE snapshot_id=?",
            (snap[0],))}

    def current_teams(self):
        return {pid: m["team"] for pid, m in self.members().items()}

    def queue(self):
        return [dict(r) for r in self.con.execute(
            "SELECT source, source_player_key, reason, player_id FROM identity_onboarding_queue "
            "WHERE status='open'")]

    def fingerprint(self):
        snap = self.con.execute("SELECT id, source_checksum FROM roster_snapshots WHERE league='mls' "
                                "AND status='published'").fetchone()
        return {"published": tuple(snap), "snapshots": _count(self.con, "roster_snapshots"),
                "memberships": _count(self.con, "roster_memberships"),
                "players": _count(self.con, "players"), "binds": _count(self.con, "player_source_ids")}


@pytest.fixture
def cutover(monkeypatch):
    """Turn the membership gate on for one test. Production leaves it off until the gates pass."""
    if mls_resolution is None:
        pytest.fail("mls_resolution is not implemented")
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, "1")
    return mls_resolution


# --- identity and onboarding -----------------------------------------------------------

def test_existing_population():
    fx = json.load(open(REGRESSION))
    con = _db()
    binds = {(s, str(k)): pid for s, k, pid in fx["binds"]}
    seen = {}
    for source in ("mlssoccer", "fotmob"):
        for m in fx["squads"][source]:
            pid = binds[(source, str(m["source_player_key"]))]
            seen.setdefault(pid, (m["name"], m["team"]))
    for pid, (name, team) in seen.items():
        con.execute("INSERT INTO players(id,name,team,league,active) VALUES(?,?,?,?,1)", (pid, name, team, "mls"))
    for (s, k), pid in binds.items():  # the fixture lists some keys twice (MLS and Leagues Cup); each is one bind
        con.execute("INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
                    "VALUES(?,'mls',?,?,?,?)", (s, k, pid, D1, D1))
    con.commit()
    players_before = _count(con, "players")
    binds_before = {(s, k): p for s, k, p in con.execute("SELECT source, source_player_key, player_id "
                                                          "FROM player_source_ids")}

    cycle = mls_roster.run_cycle(con, fx["squads"], captured_at=D1)

    assert cycle.status == "publish"
    assert len({m["player_id"] for m in cycle.result.memberships}) == 1040
    assert not cycle.result.blockers
    assert _count(con, "players") == players_before, "no player may be created for the existing population"
    assert {(s, k): p for s, k, p in con.execute("SELECT source, source_player_key, player_id "
                                                 "FROM player_source_ids")} == binds_before


def test_new_signing():
    w = World()
    w.cycle(D1)
    w.add_pair("m9001", "f9001", "New Signer", "Club01", dob="2001-05-09")
    players_before = _count(w.con, "players")

    first = w.cycle(D2)

    assert first.status == "publish" and first.outcome == "published"
    assert len(first.onboarded) == 1
    assert _count(w.con, "players") == players_before + 1
    pid = w.bind_of("mlssoccer", "m9001")
    assert pid is not None and pid == w.bind_of("fotmob", "f9001")
    assert w.current_teams()[pid] == "Club01"

    again = w.cycle(D3)
    assert again.outcome == "unchanged"
    assert again.onboarded == []
    assert _count(w.con, "players") == players_before + 1

    # The same shape, but the two publishers disagree on the date of birth: nothing is created, and it is queued.
    w.add_pair("m9002", "f9002", "Disputed Birth", "Club02", dob="2002-02-02")
    w.dobs[("fotmob", "f9002")] = ["2003-03-03"]
    before_disputed = _count(w.con, "players")
    disputed = w.cycle(D4)
    assert _count(w.con, "players") == before_disputed, "uncorroborated dates of birth never create a person"
    assert w.bind_of("mlssoccer", "m9002") is None and w.bind_of("fotmob", "f9002") is None
    assert disputed.result.coverage == "partial"
    assert any(q["source_player_key"] == "m9002" and q["reason"] == "dob_not_corroborated" for q in w.queue())


def test_single_source_new_signing():
    w = World()
    w.cycle(D1)
    teams_before = w.current_teams()
    w.add_single("m9101", "Solo Newcomer", "Club04", dob="2000-01-01")
    players_before = _count(w.con, "players")

    cycle = w.cycle(D2)

    assert cycle.status == "publish"
    assert cycle.result.coverage == "partial", "an unverified new player must never be labelled verified"
    assert "m9101" in [b["source_player_key"] for b in cycle.result.blockers]
    assert _count(w.con, "players") == players_before
    assert any(q["source_player_key"] == "m9101" and q["reason"] == "single_source_unverified" for q in w.queue())
    teams_now = w.current_teams()
    for pid, team in teams_before.items():
        assert teams_now[pid] == team, "existing teams stay current"


def test_namesake():
    w = World()
    w.cycle(D1)
    binds_before = w.binds()
    players_before = _count(w.con, "players")
    w.add_pair("m9201", "f9201", "Player Club01 00", "Club01", dob="1994-07-07")

    cycle = w.cycle(D2)

    assert _count(w.con, "players") == players_before, "a namesake is never merged or created on name and club"
    after = w.binds()
    assert all(after[k] == v for k, v in binds_before.items()), "the existing person keeps every binding"
    assert w.bind_of("mlssoccer", "m9201") is None and w.bind_of("fotmob", "f9201") is None
    reasons = {q["source_player_key"]: q["reason"] for q in w.queue()}
    assert reasons.get("m9201") == "namesake_exists" and reasons.get("f9201") == "namesake_exists"
    assert cycle.result.coverage == "partial"


def test_rekey():
    w = World()
    w.cycle(D1)
    players_before = _count(w.con, "players")

    # A: the publisher replaces the FotMob ID of person 6. The date of birth does not corroborate the new ID.
    w.replace_key("fotmob", "f6", "f6x", dob="1999-09-09")
    unverified = w.cycle(D2)
    assert _count(w.con, "players") == players_before, "a rekey never creates a second person"
    assert w.bind_of("fotmob", "f6x") is None, "an unverified rekey is never bound"
    assert w.bind_of("mlssoccer", "m6") == 6, "the other publisher's binding is untouched"
    assert 6 in w.current_teams(), "person 6 stays current through the other publisher"
    assert unverified.result.coverage == "partial"
    assert [s["player_id"] for s in unverified.result.source_lost] == [6]
    assert any(q["reason"] == "rekey_unverified" and q["player_id"] == 6 for q in w.queue())

    # B: the same ID is later corroborated by the date of birth, so the rekey is bound to the same person.
    w.dobs[("fotmob", "f6x")] = [dob_of(6)]
    verified = w.cycle(D3)
    assert w.bind_of("fotmob", "f6x") == 6
    assert _count(w.con, "players") == players_before
    assert 6 in [r["player_id"] for r in verified.result.rekeys]
    assert verified.result.coverage == "verified"


def test_source_id_collision():
    w = World()
    w.cycle(D1)
    w.rebind("mlssoccer", "m2", "77", pid=2)   # MLS key 77 belongs to person 2
    w.rebind("fotmob", "f3", "77", pid=3)      # FotMob key 77 belongs to person 3, a different person
    cycle = w.cycle(D2)
    members = {m["player_id"]: m for m in cycle.result.memberships}
    assert members[2]["keys"]["mlssoccer"] == "77"
    assert members[3]["keys"]["fotmob"] == "77"

    w.drop("fotmob", "f2")  # person 2 leaves FotMob; key 77 must not carry anyone across
    later = w.cycle(D3)
    members = {m["player_id"]: m for m in later.result.memberships}
    assert members[2]["keys"] == {"mlssoccer": "77"}
    assert members[3]["keys"] == {"fotmob": "77", "mlssoccer": "m3"}
    assert not any(c["source_player_key"] == "77" and c["source"] == "mlssoccer" for c in later.result.carried), \
        "a key from one publisher never carries a person through another publisher's key"


# --- roster membership -------------------------------------------------------------------

def test_departure():
    w = World()
    w.cycle(D1)
    binds_before = w.binds()
    players_before = _count(w.con, "players")
    logs_before = _checksum(w.con, "player_game_logs")

    w.drop_person(5)
    cycle = w.cycle(D2)

    assert 5 in [d["player_id"] for d in cycle.result.departures]
    assert 5 not in w.current_teams()
    assert _count(w.con, "players") == players_before
    assert w.binds() == binds_before, "a departed person keeps the permanent identity"
    assert _checksum(w.con, "player_game_logs") == logs_before
    history = mls_resolution.members_as_of(w.con, dt.date(2026, 10, 27))
    assert history[5]["team"] == "Club01", "the historical membership is retained"


def test_transfer():
    w = World()
    w.cycle(D1)
    w.move(1, "Club02")

    cycle = w.cycle(D2)

    assert 1 in [t["player_id"] for t in cycle.result.transfers]
    assert w.current_teams()[1] == "Club02"
    assert mls_resolution.members_as_of(w.con, dt.date(2026, 10, 27))[1]["team"] == "Club01"
    log = w.con.execute("SELECT team FROM player_game_logs WHERE player_id=1").fetchone()[0]
    assert log == "Club01", "a historical game keeps the club it was played for"
    assert w.bind_of("mlssoccer", "m1") == 1 and w.bind_of("fotmob", "f1") == 1, "same canonical person"
    assert cycle.result.coverage == "verified"


def test_single_source_disappearance():
    w = World()
    w.cycle(D1)
    w.drop("fotmob", "f9")  # FotMob drops person 9. MLS still lists him.

    cycle = w.cycle(D2)

    assert 9 in w.current_teams(), "a person still listed by one publisher is retained"
    assert [s["player_id"] for s in cycle.result.source_lost] == [9]
    assert 9 not in [d["player_id"] for d in cycle.result.departures]
    assert cycle.result.coverage == "partial"
    assert 901 not in [s["player_id"] for s in cycle.result.source_lost], \
        "a person who was only ever listed by MLS is not a missing-source case"


def test_publisher_disagreement():
    w = World()
    w.cycle(D1)
    club = w.team_of(4)
    w.set_club("fotmob", "f4", "Club30")   # FotMob says Club30, MLS still says the old club
    w.move(7, "Club08")                    # a real transfer for someone else

    cycle = w.cycle(D2)

    members = w.members()
    assert members[4]["status"] == "held" and members[4]["team"] == club
    assert 4 in [h["player_id"] for h in cycle.result.held]
    assert members[7]["team"] == "Club08", "other clubs keep updating"
    assert len({m["team"] for m in members.values()}) == 30
    assert cycle.result.coverage == "partial"


def test_conflict_recovery():
    w = World()
    w.cycle(D1)
    club = w.team_of(4)
    w.set_club("fotmob", "f4", "Club30")
    w.cycle(D2)

    w.set_club("fotmob", "f4", club)  # the publishers agree again
    cycle = w.cycle(D3)

    assert w.members()[4]["status"] == "active"
    assert not cycle.result.held
    assert cycle.result.coverage == "verified"


def test_incomplete_fetch():
    w = World()
    w.cycle(D1)
    before = w.fingerprint()
    saved = copy.deepcopy(w.squads)

    w.squads["fotmob"] = [r for r in w.squads["fotmob"] if r["team"] != "Club10"]   # a club is missing
    assert w.cycle(D2).status == "refused"
    assert w.fingerprint() == before
    w.squads = copy.deepcopy(saved)

    victims = [r["source_player_key"] for r in w.squads["fotmob"] if r["team"] == "Club11"][:8]
    w.squads["fotmob"] = [r for r in w.squads["fotmob"] if r["source_player_key"] not in victims]
    assert w.cycle(D2).status == "refused"   # eight players gone from one club
    assert w.fingerprint() == before
    w.squads = copy.deepcopy(saved)

    w.squads["mlssoccer"] = []                                                      # an empty publisher
    assert w.cycle(D2).status == "refused"
    assert w.fingerprint() == before


def test_degraded_recovery():
    w = World()
    w.cycle(D1)
    saved = copy.deepcopy(w.squads)
    w.squads["mlssoccer"] = []
    assert w.cycle(D2).status == "refused"

    w.squads = copy.deepcopy(saved)
    cycle = w.cycle(D3)

    assert cycle.outcome in ("published", "unchanged")
    assert cycle.result.coverage == "verified"
    assert _count(w.con, "roster_snapshots") >= 1
    assert w.con.execute("SELECT COUNT(*) FROM roster_snapshots WHERE league='mls' AND status='published'") \
        .fetchone()[0] == 1


# --- current and historical resolution ---------------------------------------------------

def test_stale_lookup(cutover, monkeypatch):
    fx = json.load(open(CUTOVER))
    con = _db()
    for pid, name, team in fx["players"]:
        con.execute("INSERT INTO players(id,name,team,league,active) VALUES(?,?,?,?,1)", (pid, name, team, "mls"))
    for s, k, pid, lg in fx["binds"]:
        con.execute("INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
                    "VALUES(?,?,?,?,?,?)", (s, lg, str(k), pid, D1, D1))
    con.commit()
    cycle = mls_roster.run_cycle(con, fx["squads"], captured_at=D2)
    assert cycle.status == "publish"
    stale = fx["stale_departed"]
    assert len(stale) == 16

    # Control: with the gate off, the legacy resolver still returns these people. This is the defect.
    monkeypatch.delenv(cutover.CUTOVER_ENV, raising=False)
    still_resolved = [pid for pid in stale
                      if _core._resolve_player_for_ingest(con, *_name_team(con, pid), "mls")[0] == pid]
    assert len(still_resolved) == 16
    monkeypatch.setenv(cutover.CUTOVER_ENV, "1")
    for pid in stale:
        assert _core._resolve_player_for_ingest(con, *_name_team(con, pid), "mls")[0] is None, \
            "a player who is not in the current squads must not resolve (pid %s)" % pid


def test_all_resolver_paths(cutover, monkeypatch):
    w = World()
    w.cycle(D1)
    w.drop_person(5)
    w.cycle(D2)
    name, team = w.name_of(5), "Club01"
    w.con.execute("INSERT INTO name_alias(alias_norm, player_id) VALUES(?,?)", ("five alias name", 5))
    w.con.execute("INSERT INTO published_roster(league, source, source_player_key, name, name_folded, team, "
                  "position, position_group, team_code, updated_at, player_id) "
                  "VALUES('mls','fotmob','f5','Five Roster Name',?,?, 'M','midfield','CLB1',?,5)",
                  (published_roster.fold("Five Roster Name"), team, D1))
    w.con.commit()
    probes = {"exact name": name, "normalized name": name.upper() + ".", "alias": "Five Alias Name",
              "published roster": "Five Roster Name"}
    monkeypatch.delenv(cutover.CUTOVER_ENV, raising=False)
    for path, probe in probes.items():
        assert _core._resolve_player_for_ingest(w.con, probe, team, "mls")[0] == 5, \
            "control: the legacy %s path resolves person 5" % path
    monkeypatch.setenv(cutover.CUTOVER_ENV, "1")
    for path, probe in probes.items():
        assert _core._resolve_player_for_ingest(w.con, probe, team, "mls")[0] is None, \
            "the %s path must respect current membership" % path
    assert _core._resolve_player_for_ingest(w.con, w.name_of(6), w.team_of(6), "mls")[0] == 6


def test_historical_resolution(cutover):
    w = World()
    w.cycle(D1)
    w.drop_person(5)
    w.move(1, "Club02")
    w.cycle(D2)
    old = dt.date(2026, 10, 27)

    assert _core._resolve_player_for_ingest(w.con, w.name_of(5), "Club01", "mls", as_of=old)[0] == 5
    assert _core._resolve_player_for_ingest(w.con, w.name_of(1), "Club01", "mls", as_of=old)[0] == 1
    assert mls_resolution.members_as_of(w.con, old)[1]["team"] == "Club01", "history keeps the old club"
    assert _core._resolve_player_for_ingest(w.con, w.name_of(5), "Club01", "mls")[0] is None
    assert _core._resolve_player_for_ingest(w.con, w.name_of(1), "Club02", "mls")[0] == 1
    assert _core._resolve_player_for_ingest(w.con, w.name_of(1), "Club01", "mls",
                                            as_of=dt.date(2026, 1, 1))[0] is None, \
        "no snapshot covers that date: fail closed, never invent a club"
    assert mls_resolution.members_as_of(w.con, dt.date(2026, 1, 1)) is None


def test_current_team_source(cutover):
    w = World()
    w.cycle(D1)
    w.move(1, "Club02")
    w.cycle(D2)
    w.con.execute("UPDATE players SET team='Club99' WHERE id=1")
    w.con.execute("UPDATE published_roster SET team='Club99' WHERE player_id=1")
    assert mls_resolution.current_team(w.con, 1) == "Club02"
    assert _core._resolve_player_for_ingest(w.con, w.name_of(1), "Club02", "mls")[0] == 1


def test_ligamx_lcup(cutover):
    w = World()
    w.cycle(D1)
    players_before = _count(w.con, "players")
    w.con.execute("INSERT INTO players(id,name,team,league,active) VALUES(5001,'Liga Player','Club Mx','ligamx',1)")
    w.con.execute("INSERT INTO published_roster(league, source, source_player_key, name, name_folded, team, "
                  "position, position_group, team_code, updated_at, player_id) "
                  "VALUES('ligamx','fotmob','mx1','Liga Player',?,'Club Mx','M','midfield','MX1',?,5001)",
                  (published_roster.fold("Liga Player"), D1))
    w.con.execute("INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
                  "VALUES('fotmob','lcup','lc6',6,?,?)", (D1, D1))
    w.con.execute("INSERT INTO published_roster(league, source, source_player_key, name, name_folded, team, "
                  "position, position_group, team_code, updated_at, player_id) "
                  "VALUES('lcup','fotmob','lc6',?,?,'Club01','M','midfield','CLB1',?,6)",
                  (w.name_of(6), published_roster.fold(w.name_of(6)), D1))
    w.con.commit()

    assert _core._resolve_player_for_ingest(w.con, "Liga Player", "Club Mx", "ligamx")[0] == 5001
    assert _core._resolve_player_for_ingest(w.con, w.name_of(6), "Club01", "lcup")[0] == 6
    assert _count(w.con, "players") == players_before + 1, "Leagues Cup creates no competition-specific person"

    w.drop_person(6)
    w.cycle(D2)
    assert _core._resolve_player_for_ingest(w.con, w.name_of(6), "Club01", "lcup")[0] is None


# --- integrity and reliability -------------------------------------------------------------

def test_idempotence():
    w = World()
    w.cycle(D1)
    again = w.cycle(D2)
    assert again.outcome == "unchanged"
    assert _count(w.con, "roster_snapshots") == 1
    assert w.current_snapshot()[1] == D2, "the verification time is refreshed"


def test_transition_idempotence():
    w = World()
    w.cycle(D1)
    snapshots = _count(w.con, "roster_snapshots")

    def settle(when, day_a, day_b):
        first = w.cycle(when)
        assert first.outcome == "published"
        for day in (day_a, day_b):
            assert w.cycle(day).outcome == "unchanged"
        return _count(w.con, "roster_snapshots")

    w.move(1, "Club02")
    snapshots = settle(D2, D3, D4)
    w.drop_person(5)
    snapshots = settle(D5, "2026-11-01T09:00:00+00:00", "2026-11-02T09:00:00+00:00")
    w.replace_key("fotmob", "f6", "f6x", dob=dob_of(6))
    snapshots = settle("2026-11-03T09:00:00+00:00", "2026-11-04T09:00:00+00:00", "2026-11-05T09:00:00+00:00")
    club30 = w.team_of(30)
    w.set_club("fotmob", "f30", "Club05")
    snapshots = settle("2026-11-06T09:00:00+00:00", "2026-11-07T09:00:00+00:00", "2026-11-08T09:00:00+00:00")
    w.set_club("fotmob", "f30", club30)
    snapshots = settle("2026-11-09T09:00:00+00:00", "2026-11-10T09:00:00+00:00", "2026-11-11T09:00:00+00:00")
    assert snapshots == 6, "one membership set per population change, none for repeats"


def test_atomicity():
    w = World()
    w.cycle(D1)
    before = w.fingerprint()
    w.move(1, "Club02")
    w.add_pair("m9301", "f9301", "Late Signer", "Club02", dob=dob_of(9301))
    real = rm.publish_roster_snapshot

    def interrupted(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("publication interrupted after the membership rows were written")

    mp = pytest.MonkeyPatch()
    mp.setattr(rm, "publish_roster_snapshot", interrupted)
    try:
        with pytest.raises(RuntimeError):
            w.cycle(D2)
    finally:
        mp.undo()
    assert w.fingerprint() == before, "the last valid snapshot stays and nothing from the failed cycle is kept"


def test_data_integrity():
    w = World()
    w.cycle(D1)
    tables = ("players", "player_source_ids") + PROTECTED
    before = {t: _checksum(w.con, t) for t in tables}

    w.move(1, "Club02")
    w.drop_person(5)
    w.cycle(D2)
    after_snapshot_only = {t: _checksum(w.con, t) for t in tables}
    assert after_snapshot_only == before, "a snapshot-only operation changes no identity or history row"

    players_before = _count(w.con, "players")
    binds_before = _count(w.con, "player_source_ids")
    w.add_pair("m9401", "f9401", "Newbie", "Club03", dob=dob_of(9401))
    w.cycle(D3)
    assert _count(w.con, "players") == players_before + 1
    assert _count(w.con, "player_source_ids") == binds_before + 2
    for table in PROTECTED:
        assert _checksum(w.con, table) == after_snapshot_only[table], "onboarding never changes %s" % table


def test_health_reporting():
    w = World()
    w.cycle(D1)
    w.set_club("fotmob", "f4", "Club05")
    w.add_single("m9501", "Unbound Newcomer", "Club06", dob=dob_of(9501))
    w.drop("fotmob", "f9")
    cycle = w.cycle(D2)

    health = ms.health(w.con)
    assert cycle.result.coverage == "partial"
    assert health["coverage"] == "partial"
    assert health["blockers"] >= 1
    assert health["held"] == 1
    assert health["source_lost"] == 1
    assert health["verified_at"] == D2

    clean = World()
    clean.cycle(D1)
    assert ms.health(clean.con)["coverage"] == "verified"
