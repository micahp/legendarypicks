"""Shadow comparison: the MLS roster job and the MLS snapshot, fed the same squads, nothing applied to prod.

Usage: python mls_snapshot_shadow.py PROD_DB SQUADS_JSON PRIOR_FIXTURE WORK_DIR REPORT_JSON

PROD_DB is opened read-only and never written. Every write happens on a copy in WORK_DIR:
- The scope copy holds the identity tables and the MLS game logs. Nothing else is copied.
- The legacy path is the roster job's own `_write` and `publish_identities`, run on a copy, in the job's order.
- The snapshot path is `mls_snapshot.build` (no write) on a copy. Publishing is tested separately, on its own copy.

Both paths start from the same database state and the same squads. The squads are fetched once and read from
SQUADS_JSON. Scenarios apply one deliberate change to those squads (a signing, a departure, a transfer, a new
publisher key, one source only, a club drop, an empty publisher) and run both paths on the change.

Writes only to WORK_DIR and REPORT_JSON.
"""
import collections
import copy
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ingest_published_rosters as ipr  # noqa: E402
import mls_snapshot as ms  # noqa: E402
import mls_snapshot_copy_check as cc  # noqa: E402
import published_roster  # noqa: E402

LEAGUE = "mls"
SOURCES = ("fotmob", "mlssoccer")
CAPTURED = "2026-10-28T09:00:00+00:00"
PRIOR_CAPTURED = "2026-10-27T21:13:59+00:00"
SCOPE_TABLES = {
    "players": "",
    "player_source_ids": "",
    "published_roster": "",
    "published_roster_name": "",
    "league_clubs": "",
    "player_game_logs": "WHERE player_id IN (SELECT id FROM players WHERE league='mls')",
    "roster_snapshots": "WHERE league='mls'",
    "roster_memberships": "WHERE snapshot_id IN (SELECT id FROM roster_snapshots WHERE league='mls')",
}
SCENARIOS = ("live_vs_prior", "signing", "departure", "transfer", "new_publisher_key", "one_source_only",
             "source_lag", "club_drop", "club_missing", "mls_empty", "repeat")


# --- copies ----------------------------------------------------------------------

def build_scope(prod_path, dest):
    """Copy the identity scope out of prod with a read-only connection. Refuses to overwrite."""
    if os.path.exists(dest):
        raise SystemExit("refusing to overwrite %s" % dest)
    src = sqlite3.connect("file:%s?mode=ro" % prod_path, uri=True, timeout=120)
    out = sqlite3.connect(dest)
    for table, where in SCOPE_TABLES.items():
        out.execute(src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                                (table,)).fetchone()[0])
        cols = [row[1] for row in src.execute("PRAGMA table_info(%s)" % table)]
        rows = src.execute("SELECT %s FROM %s %s" % (",".join(cols), table, where)).fetchall()
        out.executemany("INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(cols), ",".join("?" * len(cols))),
                        rows)
    marks = ",".join("?" * len(SCOPE_TABLES))
    for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                              "AND tbl_name IN (%s)" % marks, tuple(SCOPE_TABLES)):
        out.execute(sql)
    out.commit()
    out.close()
    src.close()


def snapshot_connection(path):
    """Autocommit, with rows by name, as the copy check and the publisher expect."""
    con = sqlite3.connect(path, isolation_level=None, timeout=120)
    con.row_factory = sqlite3.Row
    return con


def copy_db(src_path, dst_path):
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    src.backup(dst)
    dst.close()
    src.close()


def prod_counts(prod_path):
    con = sqlite3.connect("file:%s?mode=ro" % prod_path, uri=True, timeout=120)
    counts = {}
    for table in ("players", "player_source_ids", "published_roster", "roster_snapshots", "props", "prop_results"):
        counts[table] = con.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    con.close()
    return counts


# --- the two paths -----------------------------------------------------------------

def legacy_run(con, squads, now):
    """The roster job's write and identity steps for MLS, in the job's order. Returns (stats, touched)."""
    published_roster.ensure(con)
    touched = []
    for provider in SOURCES:
        members = squads.get(provider) or []
        if not members:
            continue  # the job leaves the stored roster alone when a publisher publishes nothing
        ipr._write(con, LEAGUE, members, now)
        touched.extend((m["source"], str(m["source_player_key"])) for m in members)
    stats = published_roster.publish_identities(con, LEAGUE, now, touched)
    con.commit()
    return stats, touched


def identity_state(con):
    binds = {(s, str(k)): p for s, k, p in con.execute(
        "SELECT source, source_player_key, player_id FROM player_source_ids WHERE league=?", (LEAGUE,))}
    players = {p: (name, team) for p, name, team in con.execute(
        "SELECT id, name, team FROM players WHERE league=?", (LEAGUE,))}
    observed = {(s, str(k)): (p, code) for s, k, p, code in con.execute(
        "SELECT source, source_player_key, player_id, team_code FROM published_roster WHERE league=?", (LEAGUE,))}
    return binds, players, observed


def snapshot_build(con, squads):
    return ms.build(con, squads, ms.binds_from_db(con), captured_at=CAPTURED)


# --- scenarios -------------------------------------------------------------------------

def bound_people(squads, binds):
    """People the squads hold under both publisher keys, in player_id order. The scenarios move these."""
    memberships, _, _ = ms.resolve(squads, binds)
    return sorted((m for m in memberships if len(m["keys"]) == 2), key=lambda m: m["player_id"])


def _drop(squads, source, key):
    squads[source] = [m for m in squads[source] if str(m["source_player_key"]) != str(key)]


def _find(squads, source, key):
    return next(m for m in squads[source] if str(m["source_player_key"]) == str(key))


def apply(scenario, squads, people):
    """A copy of the live squads with one deliberate change. Each change is made to a real record."""
    s = copy.deepcopy(squads)
    clubs = sorted({m["team"] for m in s["fotmob"]})
    if scenario in ("live_vs_prior", "repeat"):
        return s
    if scenario == "signing":
        template = copy.deepcopy(s["mlssoccer"][0])
        for source, key in (("fotmob", "shadow-sign-1"), ("mlssoccer", "shadow-sign-1")):
            row = dict(template, source=source, source_player_key=key, name="Shadow Signing One",
                       names=["Shadow Signing One"], team=clubs[0])
            s[source].append(row)
    elif scenario == "departure":
        for source in SOURCES:
            _drop(s, source, people[0]["keys"][source])
    elif scenario == "transfer":
        person = people[1]
        for source in SOURCES:
            row = _find(s, source, person["keys"][source])
            row["team"] = clubs[(clubs.index(row["team"]) + 1) % len(clubs)]
    elif scenario == "new_publisher_key":
        row = _find(s, "fotmob", people[2]["keys"]["fotmob"])
        row["source_player_key"] = "shadow-newkey-1"
    elif scenario == "one_source_only":
        _drop(s, "fotmob", people[3]["keys"]["fotmob"])
    elif scenario == "source_lag":
        # FotMob has moved a player to the next club and MLS has not yet: the publishers disagree for one day.
        row = _find(s, "fotmob", people[4]["keys"]["fotmob"])
        row["team"] = clubs[(clubs.index(row["team"]) + 1) % len(clubs)]
    elif scenario == "club_drop":
        counts = collections.Counter(m["team"] for m in s["fotmob"])
        club = counts.most_common(1)[0][0]
        victims = [m["source_player_key"] for m in s["fotmob"] if m["team"] == club][:8]
        for key in victims:
            _drop(s, "fotmob", key)
    elif scenario == "club_missing":
        s["fotmob"] = [m for m in s["fotmob"] if m["team"] != clubs[0]]
    elif scenario == "mls_empty":
        s["mlssoccer"] = []
    else:
        raise ValueError(scenario)
    return s


def summarize_legacy(con, squads, touched, stats, pre, post):
    binds_pre, players_pre, _ = pre
    binds_post, players_post, observed = post
    team_of = {(src, str(m["source_player_key"])): m["team"] for src in SOURCES for m in squads.get(src) or []}
    people = collections.defaultdict(lambda: {"keys": {}, "teams": set()})
    unresolved = []
    for source, key in touched:
        pid = observed.get((source, key), (None, None))[0]
        if pid is None:
            unresolved.append({"source": source, "source_player_key": key, "team": team_of.get((source, key))})
            continue
        people[pid]["keys"][source] = key
        people[pid]["teams"].add(team_of[(source, key)])
    touched_set = set(touched)
    stale_bound = collections.defaultdict(list)
    for (source, key), (pid, _) in observed.items():
        if pid is not None and (source, key) not in touched_set:
            stale_bound[pid].append("%s:%s" % (source, key))
    return {
        "stats": {k: v for k, v in stats.items() if k != "failure_examples"},
        "refusals": stats.get("failure_examples", []),
        "touched_rows": len(touched),
        "resolved_rows": len(touched) - len(unresolved),
        "unresolved_rows": unresolved,
        "binds_added": sorted([src, key, pid] for (src, key), pid in binds_post.items()
                              if (src, key) not in binds_pre),
        "binds_changed": sorted([src, key, binds_pre[(src, key)], pid] for (src, key), pid in binds_post.items()
                                if (src, key) in binds_pre and binds_pre[(src, key)] != pid),
        "players_inserted": sorted(set(players_post) - set(players_pre)),
        "players_team_changed": sorted(p for p in set(players_pre) & set(players_post)
                                       if players_pre[p][1] != players_post[p][1]),
        "stale_bound_persons": sorted(str(pid) for pid in set(stale_bound) - set(people)),
        "people": {str(pid): {"keys": v["keys"], "teams": sorted(v["teams"])} for pid, v in people.items()},
    }


def summarize_snapshot(result):
    if result.status != "publish":
        return {"status": "refused", "reasons": result.reasons, "conflicts": result.conflicts}
    return {
        "status": "publish", "coverage": result.coverage,
        "memberships": len(result.memberships),
        "blockers": result.blockers, "carried": result.carried, "departures": result.departures,
        "single_source_departures": result.single_source_departures,
        "bind_changed": result.bind_changed, "transfers": result.transfers, "rekeys": result.rekeys,
        "membership_by_person": {str(m["player_id"]): {"team": m["team"], "keys": m["keys"],
                                                       "status": m.get("roster_status")}
                                 for m in result.memberships},
    }


def compare(legacy, snapshot):
    if snapshot["status"] != "publish":
        return {"comparable": False}
    legacy_people = legacy["people"]
    snap_people = snapshot["membership_by_person"]
    lp, sp = set(legacy_people), set(snap_people)
    carried = {pid for pid, m in snap_people.items() if m["status"] == "carried"}
    club_disagree = sorted(pid for pid in lp & sp
                           if legacy_people[pid]["teams"] != [snap_people[pid]["team"]])
    return {
        "comparable": True,
        "legacy_only": sorted(lp - sp),
        "snapshot_only_fresh": sorted((sp - lp) - carried),
        "snapshot_only_carried": sorted((sp - lp) & carried),
        "club_disagreements": club_disagree,
        "legacy_bound_departed_not_in_snapshot": sorted(set(legacy["stale_bound_persons"]) - sp),
    }


def historical(prod, pids, scope):
    """Game logs in the scope copy, and props and prop results in prod, for the people whose status changed."""
    pids = sorted({int(p) for p in pids})
    if not pids:
        return {"people": 0, "game_logs": 0, "props": 0, "prop_results": 0}
    marks = ",".join("?" * len(pids))
    logs = scope.execute("SELECT COUNT(*) FROM player_game_logs WHERE player_id IN (%s)" % marks, pids).fetchone()[0]
    props = prod.execute("SELECT COUNT(*) FROM props WHERE player_id IN (%s)" % marks, pids).fetchone()[0]
    results = prod.execute(
        "SELECT COUNT(*) FROM prop_results WHERE prop_id IN (SELECT id FROM props WHERE player_id IN (%s))" % marks,
        pids).fetchone()[0]
    return {"people": len(pids), "game_logs": logs, "props": props, "prop_results": results}


def run_case(name, base, squads, work, prod_ro, scope_ro):
    """Both paths on copies of the same base state, with the same squads. Returns one report entry."""
    leg_path = os.path.join(work, "legacy_%s.db" % name)
    snap_path = os.path.join(work, "snapshot_%s.db" % name)
    copy_db(base, leg_path)
    leg = sqlite3.connect(leg_path, timeout=120)
    pre = identity_state(leg)
    stats, touched = legacy_run(leg, squads, CAPTURED)
    post = identity_state(leg)
    legacy = summarize_legacy(leg, squads, touched, stats, pre, post)
    leg.close()
    os.remove(leg_path)

    copy_db(base, snap_path)
    snap = snapshot_connection(snap_path)
    result = snapshot_build(snap, squads)
    snapshot = summarize_snapshot(result)
    snap.close()
    os.remove(snap_path)

    cmp_ = compare(legacy, snapshot)
    changed = set()
    if snapshot["status"] == "publish":
        changed |= {int(x["player_id"]) for x in snapshot["departures"] + snapshot["single_source_departures"]
                    + snapshot["transfers"] + snapshot["rekeys"] + snapshot["bind_changed"]}
        changed |= {int(p) for p in cmp_["legacy_only"] + cmp_["snapshot_only_fresh"] + cmp_["club_disagreements"]
                    + cmp_["legacy_bound_departed_not_in_snapshot"]}
    hist = historical(prod_ro, changed, scope_ro)
    return {"scenario": name, "legacy": legacy, "snapshot": snapshot, "comparison": cmp_,
            "historical_for_changed_people": hist}


def main(prod_path, squads_path, prior_path, work, report_path):
    os.makedirs(work, exist_ok=True)
    before = prod_counts(prod_path)
    live = json.load(open(squads_path))["squads"]
    prior = json.load(open(prior_path))["squads"]

    scope = os.path.join(work, "scope.db")
    build_scope(prod_path, scope)
    scope_ro = sqlite3.connect("file:%s?mode=ro" % scope, uri=True)
    prod_ro = sqlite3.connect("file:%s?mode=ro" % prod_path, uri=True, timeout=120)

    binds = ms.binds_from_db(scope_ro)
    people = bound_people(live, binds)

    # Base states. Each is the scope plus one published snapshot. Publishing writes roster_snapshots only,
    # never binds or roster rows, so the identity state both paths read is the scope's.
    base_prior = os.path.join(work, "base_prior.db")  # prior verified snapshot = the 2026-10-27 squads
    base_live = os.path.join(work, "base_live.db")    # prior verified snapshot = today's squads
    cold_path = os.path.join(work, "cold.db")          # no prior, as prod has today
    for path, squads, captured in ((base_prior, prior, PRIOR_CAPTURED), (base_live, live, CAPTURED)):
        copy_db(scope, path)
        con = snapshot_connection(path)
        result, outcome, _ = cc.run(con, squads, ms.binds_from_db(con), captured)
        con.close()
        if outcome != "published":
            raise SystemExit("base %s did not publish: %s %s" % (path, outcome, result.reasons))
    copy_db(scope, cold_path)
    cold_con = snapshot_connection(cold_path)
    cold = summarize_snapshot(snapshot_build(cold_con, live))
    cold_con.close()
    os.remove(cold_path)

    cases = []
    for name in SCENARIOS:
        if name == "repeat":
            continue
        if name == "live_vs_prior":
            cases.append(run_case(name, base_prior, live, work, prod_ro, scope_ro))
        else:
            squads = apply(name, live, people)
            cases.append(run_case(name, base_live, squads, work, prod_ro, scope_ro))
        print("  %-20s legacy %s | snapshot %s" % (
            name, cases[-1]["legacy"]["stats"], cases[-1]["snapshot"].get("coverage", cases[-1]["snapshot"]["status"])),
            flush=True)

    repeat = repeat_check(base_live, live, work)
    flap = flap_check(base_live, apply("club_drop", live, people), live, work)
    after = prod_counts(prod_path)
    report = {"captured": CAPTURED, "prior_captured": PRIOR_CAPTURED, "squad_counts": {
                  s: len(live[s]) for s in SOURCES}, "prod_before": before, "prod_after": after,
              "prod_unchanged_counts": before == after, "bound_people_for_scenarios": len(people),
              "cold_first_run": cold, "repeat": repeat, "flap_then_recover": flap, "cases": cases}
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    prod_ro.close()
    scope_ro.close()
    print("prod counts before:", before)
    print("prod counts after: ", after)
    return report


def repeat_check(base, live, work):
    """Same squads twice on each path. Legacy must add nothing the second time; the snapshot must say unchanged."""
    path = os.path.join(work, "repeat_legacy.db")
    copy_db(base, path)
    con = sqlite3.connect(path, timeout=120)
    first_pre = identity_state(con)
    legacy_run(con, live, CAPTURED)
    first_post = identity_state(con)
    second_stats, _ = legacy_run(con, live, CAPTURED)
    second_post = identity_state(con)
    con.close()
    os.remove(path)
    path = os.path.join(work, "repeat_snapshot.db")
    copy_db(base, path)
    con = snapshot_connection(path)
    first, first_outcome, _ = cc.run(con, live, ms.binds_from_db(con), CAPTURED)
    second, second_outcome, _ = cc.run(con, live, ms.binds_from_db(con), "2026-10-28T10:00:00+00:00")
    con.close()
    os.remove(path)
    return {"legacy_second_run_binds_changed": second_post[0] != first_post[0],
            "legacy_second_run_players_inserted": len(set(second_post[1]) - set(first_post[1])),
            "legacy_second_run_stats": {k: v for k, v in second_stats.items() if k != "failure_examples"},
            "snapshot_first_outcome": first_outcome, "snapshot_second_outcome": second_outcome,
            "snapshot_first_coverage": first.coverage, "snapshot_second_coverage": second.coverage}


def flap_check(base, degraded, live, work):
    """A degraded run, then a healthy one, on the same state. The degraded run must change nothing."""
    path = os.path.join(work, "flap_snapshot.db")
    copy_db(base, path)
    con = snapshot_connection(path)
    before = ms.prior_state(con)["checksum"]
    first = ms.build(con, degraded, ms.binds_from_db(con), captured_at=CAPTURED)
    after_degraded = ms.prior_state(con)["checksum"]
    second, outcome, _ = cc.run(con, live, ms.binds_from_db(con), "2026-10-28T11:00:00+00:00")
    con.close()
    os.remove(path)
    return {"degraded_status": first.status, "degraded_reasons": first.reasons,
            "published_checksum_unchanged_by_degraded_run": before == after_degraded,
            "healthy_outcome": outcome, "healthy_coverage": second.coverage}


if __name__ == "__main__":
    main(*sys.argv[1:6])
