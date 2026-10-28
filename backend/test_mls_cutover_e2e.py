"""MLS cutover end-to-end: the actual roster job, on an isolated migrated copy of the identity database.

The publishers' HTTP responses are replaced by fixture squads. Everything else is the production code path:
ingest() writes the observations, the cycle settles identities and publishes the membership snapshot, and the
ingest resolver answers props lookups. The database is a copy of the production identity scope, with the production
schema, and never the live file.

Set LP_MLS_E2E_DB to a migrated copy to run the same gate on that copy instead of the fixture-built database.
"""
import json
import os
import shutil
import sqlite3

import pytest

import _core
import ingest_published_rosters as ipr
import mls_resolution
import published_roster
import roster_membership as rm
import test_mls_cutover_acceptance as acc

HERE = os.path.dirname(os.path.abspath(__file__))
CUTOVER = os.path.join(HERE, "fixtures", "mls_cutover_2026-10-28.json")
PROTECTED = ("players", "player_source_ids", "player_game_logs", "props", "prop_results",
             "settlement_attempts", "team_game_results", "published_roster")


def _fixture_database(path):
    fx = json.load(open(CUTOVER))
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(acc.SCHEMA)
    rm.create_roster_schema(con)
    published_roster.ensure(con)
    acc.mls_identity.ensure_schema(con) if acc.mls_identity else None
    con.execute("CREATE TABLE IF NOT EXISTS league_clubs(league TEXT, name TEXT, code TEXT, source TEXT, "
                "updated_at TEXT)")
    for pid, name, team in fx["players"]:
        con.execute("INSERT INTO players(id,name,team,league,active,updated_at) VALUES(?,?,?,?,1,?)",
                    (pid, name, team, "mls", acc.D1))
        con.execute("INSERT INTO player_game_logs(player_id,league,season,game_no,game_id,game_date,team,opponent,"
                    "stats,source,source_player_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, "mls", 2026, 1, "g%d" % pid, "2026-03-01", team, "Opp", "{}", "fixture", str(pid)))
        con.execute("INSERT INTO props(id,game_id,player_id,market,line,side,source,captured_at,odds) "
                    "VALUES(?,?,?,?,?,?,?,?,?)", (pid, "g%d" % pid, pid, "goals", 0.5, "over", "book", acc.D1, 100))
        con.execute("INSERT INTO prop_results(prop_id,actual_value,hit,settled_at) VALUES(?,?,?,?)",
                    (pid, 1, 1, acc.D1))
        con.execute("INSERT INTO settlement_attempts(prop_id,game_id,attempted_at,stage,terminal,reason,actual_value,"
                    "hit) VALUES(?,?,?,?,?,?,?,?)", (pid, "g%d" % pid, acc.D1, "final", 1, "ok", 1, 1))
        con.execute("INSERT INTO team_game_results(team,game_id,points) VALUES(?,?,?)", (team, "g%d" % pid, 1))
    for source, key, pid, league in fx["binds"]:
        con.execute("INSERT OR IGNORE INTO player_source_ids(source,league,source_player_key,player_id,first_seen,"
                    "last_seen) VALUES(?,?,?,?,?,?)", (source, league, str(key), pid, acc.D1, acc.D1))
    con.commit()
    return con, fx


def _database(tmp_path):
    source = os.environ.get("LP_MLS_E2E_DB")
    path = str(tmp_path / "picks.e2e.db")
    if source:
        shutil.copy(source, path)  # a migrated copy of the identity scope; never the live file
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        return con, json.load(open(CUTOVER))
    return _fixture_database(path)


def _protected_checksums(con):
    return {t: acc._checksum(con, t) for t in PROTECTED}


@pytest.fixture
def job(tmp_path, monkeypatch):
    if acc.mls_roster is None:
        pytest.fail("mls_roster is not implemented")
    con, fx = _database(tmp_path)
    path = con.execute("PRAGMA database_list").fetchone()[2]
    con.close()

    def fotmob_squad(con, league):
        return [dict(m) for m in fx["squads"]["fotmob"]]

    def mls_squad(con, league):
        return [dict(m) for m in fx["squads"]["mlssoccer"]]

    monkeypatch.setattr(ipr, "DB", path)
    monkeypatch.setattr(ipr, "_PROVIDERS", {"mls": (fotmob_squad, mls_squad)})
    monkeypatch.setenv(mls_resolution.CUTOVER_ENV, "1")

    def legacy_called(*args, **kwargs):
        raise AssertionError("the legacy identity step must not run when the cutover is on")

    monkeypatch.setattr(published_roster, "publish_identities", legacy_called)
    return {"path": path, "fx": fx}


def _open(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def test_end_to_end_roster_job(job, tmp_path, monkeypatch):
    path, fx = job["path"], job["fx"]
    con = _open(path)
    baseline = {"players": acc._count(con, "players"), "binds": acc._count(con, "player_source_ids"),
                "snapshots": acc._count(con, "roster_snapshots"), "memberships": acc._count(con, "roster_memberships")}
    protected_before = _protected_checksums(con)
    con.close()

    # 1. The first run through the real job.
    result = ipr.ingest(["mls"], dry_run=False, mls_cutover=True, mls_lookup=None)
    con = _open(path)
    first = {"players": acc._count(con, "players"), "binds": acc._count(con, "player_source_ids"),
             "snapshots": acc._count(con, "roster_snapshots"), "memberships": acc._count(con, "roster_memberships")}
    assert first["snapshots"] == baseline["snapshots"] + 1
    assert first["players"] == baseline["players"], "every fixture key is already bound: nothing is created"
    assert first["binds"] == baseline["binds"]
    published = con.execute("SELECT player_count, source_payload FROM roster_snapshots WHERE league='mls' "
                            "AND status='published'").fetchone()
    assert published["player_count"] == len({m["player_id"] for m in json.loads(published["source_payload"])
                                             ["memberships"]})
    assert json.loads(published["source_payload"])["coverage"]["status"] == "verified"

    # 2. The same squads again: the job publishes nothing new.
    ipr.ingest(["mls"], dry_run=False, mls_cutover=True, mls_lookup=None)
    con = _open(path)
    assert acc._count(con, "roster_snapshots") == first["snapshots"]
    assert acc._count(con, "players") == first["players"]

    # 3. Current lookups: the 16 people the legacy path still resolves are not in the squads.
    stale = fx["stale_departed"]
    still = []
    for pid in stale:
        name, team = con.execute("SELECT name, team FROM players WHERE id=?", (pid,)).fetchone()
        if _core._resolve_player_for_ingest(con, name, team, "mls")[0] is not None:
            still.append(pid)
    assert still == [], "departed people must not resolve as current"

    # Every current member resolves to themselves through the props resolver, at the club they are on now.
    current = mls_resolution.members_as_of(con)
    assert len(current) == 1040, "the contract population"
    unresolved = [pid for pid in current
                  if _core._resolve_player_for_ingest(con, *acc._name_team(con, pid), "mls")[0] != pid]
    assert unresolved == [], "current members that did not resolve to themselves: %s" % unresolved
    sample = sorted(current)[0]

    # 4. Historical lookup fails closed where no snapshot covers the date.
    assert _core._resolve_player_for_ingest(con, *acc._name_team(con, sample), "mls",
                                            as_of=acc.dt.date(2026, 1, 1))[0] is None

    # 5. Protected history is unchanged by the whole cutover. published_roster is excluded: the job writes its
    # observations there on purpose, and it is not history.
    after = _protected_checksums(con)
    for table in PROTECTED:
        if table != "published_roster":
            assert after[table] == protected_before[table], "%s changed during the cutover" % table
    con.close()
    assert result["identity"].get("mls_cutover_published", 0) == 1, "the first run publishes exactly one snapshot"


def test_legacy_path_untouched_when_cutover_off(job, monkeypatch):
    calls = []
    monkeypatch.setattr(published_roster, "publish_identities",
                        lambda con, league, now, touched: calls.append(league) or
                        {"components": 0, "failure_examples": []})
    monkeypatch.delenv(mls_resolution.CUTOVER_ENV, raising=False)
    ipr.ingest(["mls"], dry_run=False, mls_cutover=False)
    assert calls == ["mls"], "the default job still runs the legacy identity step"
