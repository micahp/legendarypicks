"""Roll back the MLS cutover's identity writes and snapshots, on a database you name. Dry run unless --apply.

Usage: python mls_cutover_rollback.py DB --since ISO_TIMESTAMP [--apply --archive PATH]

The cutover writes three kinds of state after its start time (--since):
- players and player_source_ids rows that onboarding created or bound;
- identity_evidence and identity_onboarding_queue rows;
- roster_snapshots and roster_memberships published by the cycle.

Rollback removes what the cycle created, and restores the snapshot the cycle superseded:
1. Refuse if a created player is referenced by props, prop results, settlement attempts, or game logs. Those need a
   person's decision, not a script.
2. Archive (JSON) every cutover-era snapshot and its memberships, then delete them, and mark the newest snapshot that
   predates --since as published again.
3. Delete the bindings the cycle added to people who existed before --since (rekeys), the created players and their
   bindings, and the evidence and queue rows stamped at or after --since.

It never touches a historical game log, prop, settlement, or team game result. It refuses a database named picks.db
(the production name). Use a copy.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys

PROTECTED_REFERENCES = (
    ("props", "player_id"),
    ("player_game_logs", "player_id"),
    ("prop_results", None),
    ("settlement_attempts", None),
)


def _referenced(con, player_ids):
    """Players a protected history table still points at. Those cannot be removed by a script."""
    if not player_ids:
        return set()
    marks = ",".join("?" * len(player_ids))
    hits = set()
    hits |= {r[0] for r in con.execute(
        "SELECT DISTINCT player_id FROM props WHERE player_id IN (%s)" % marks, player_ids)}
    hits |= {r[0] for r in con.execute(
        "SELECT DISTINCT player_id FROM player_game_logs WHERE player_id IN (%s)" % marks, player_ids)}
    hits |= {r[0] for r in con.execute(
        "SELECT DISTINCT p.player_id FROM prop_results r JOIN props p ON p.id = r.prop_id "
        "WHERE p.player_id IN (%s)" % marks, player_ids)}
    hits |= {r[0] for r in con.execute(
        "SELECT DISTINCT p.player_id FROM settlement_attempts s JOIN props p ON p.id = s.prop_id "
        "WHERE p.player_id IN (%s)" % marks, player_ids)}
    return hits


def plan(con, since):
    """Everything the rollback would remove, and what it would keep. Changes nothing."""
    created = [r[0] for r in con.execute(
        "SELECT p.id FROM players p WHERE p.league='mls' AND p.updated_at >= ? AND NOT EXISTS ("
        " SELECT 1 FROM player_source_ids s WHERE s.player_id = p.id AND s.first_seen < ?)"
        " AND EXISTS (SELECT 1 FROM player_source_ids s WHERE s.player_id = p.id AND s.first_seen >= ?)",
        (since, since, since))]
    created_set = set(created)
    rekey_binds = [tuple(r) for r in con.execute(
        "SELECT source, league, source_player_key, player_id FROM player_source_ids WHERE first_seen >= ? "
        "AND league IN ('mls','lcup')", (since,)) if r[3] not in created_set]
    created_binds = [tuple(r) for r in con.execute(
        "SELECT source, league, source_player_key, player_id FROM player_source_ids WHERE first_seen >= ? "
        "AND player_id IN (%s)" % (",".join("?" * len(created)) or "NULL"), [since] + created)] if created else []
    snapshots = [r[0] for r in con.execute(
        "SELECT id FROM roster_snapshots WHERE league='mls' AND captured_at >= ?", (since,))]
    restore = con.execute(
        "SELECT id FROM roster_snapshots WHERE league='mls' AND captured_at < ? ORDER BY captured_at DESC, id DESC "
        "LIMIT 1", (since,)).fetchone()
    referenced = _referenced(con, created)
    return {
        "since": since,
        "created_players": sorted(created),
        "created_bindings": len(created_binds),
        "rekey_bindings": len(rekey_binds),
        "_rekey_binds": rekey_binds,
        "cutover_snapshots": sorted(snapshots),
        "restore_snapshot": restore[0] if restore else None,
        "evidence_rows": con.execute("SELECT COUNT(*) FROM identity_evidence WHERE observed_at >= ?",
                                     (since,)).fetchone()[0],
        "queue_rows": con.execute("SELECT COUNT(*) FROM identity_onboarding_queue WHERE first_seen >= ?",
                                  (since,)).fetchone()[0],
        "refused_referenced_players": sorted(referenced),
        "refused": bool(referenced),
    }


def apply(con, since, archive_path):
    """Archive, then remove. Refuses the whole rollback if any created player is referenced by history."""
    p = plan(con, since)
    rekey_binds = p.pop("_rekey_binds")
    if p["refused"]:
        raise RuntimeError("rollback refused: created players are referenced by props, logs or settlements: %s"
                           % p["refused_referenced_players"])
    archive = {"since": since, "snapshots": [], "memberships": []}
    for sid in p["cutover_snapshots"]:
        row = con.execute("SELECT * FROM roster_snapshots WHERE id=?", (sid,)).fetchone()
        archive["snapshots"].append(dict(row))
        archive["memberships"].extend(dict(r) for r in con.execute(
            "SELECT * FROM roster_memberships WHERE snapshot_id=?", (sid,)))
    with open(archive_path, "w") as fh:
        json.dump(archive, fh, indent=1, default=str)
    con.execute("BEGIN IMMEDIATE")
    try:
        if p["cutover_snapshots"]:
            marks = ",".join("?" * len(p["cutover_snapshots"]))
            con.execute("DELETE FROM roster_memberships WHERE snapshot_id IN (%s)" % marks, p["cutover_snapshots"])
            con.execute("DELETE FROM roster_snapshots WHERE id IN (%s)" % marks, p["cutover_snapshots"])
        if p["restore_snapshot"] is not None:
            con.execute("UPDATE roster_snapshots SET status='published' WHERE id=?", (p["restore_snapshot"],))
        for source, league, key, pid in rekey_binds:  # bindings the cycle added to people who predate it
            con.execute("DELETE FROM player_source_ids WHERE source=? AND league=? AND source_player_key=? "
                        "AND player_id=? AND first_seen >= ?", (source, league, key, pid, since))
        if p["created_players"]:
            marks = ",".join("?" * len(p["created_players"]))
            con.execute("DELETE FROM player_source_ids WHERE player_id IN (%s)" % marks, p["created_players"])
            con.execute("DELETE FROM identity_evidence WHERE player_id IN (%s)" % marks, p["created_players"])
            con.execute("DELETE FROM players WHERE id IN (%s)" % marks, p["created_players"])
        con.execute("DELETE FROM identity_evidence WHERE observed_at >= ?", (since,))
        con.execute("DELETE FROM identity_onboarding_queue WHERE first_seen >= ?", (since,))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return p


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("db")
    ap.add_argument("--since", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--archive")
    args = ap.parse_args(argv)
    if os.path.basename(os.path.realpath(args.db)) == "picks.db":
        raise SystemExit("refusing: picks.db is the production name. Roll back a copy.")
    con = sqlite3.connect(args.db, timeout=120, isolation_level=None)
    con.row_factory = sqlite3.Row
    if not args.apply:
        print(json.dumps(plan(con, args.since), indent=1))
        return 0
    if not args.archive:
        raise SystemExit("--apply needs --archive PATH (the cutover-era snapshots are archived before deletion)")
    done = apply(con, args.since, args.archive)
    print(json.dumps(done, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
