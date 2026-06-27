#!/usr/bin/env python3
"""
dedupe_mlb.py — merge duplicate MLB player rows that split props from game logs.

The Statcast log ingest (ingest_mlb_logs.py) created its OWN player rows (placeholder
lowercase names, no espn_id) for batters and wrote game logs under them, while
roster_sync/props use the canonical rows (proper name + espn_id). Same mlbam_id, two
rows → the prop-chart join finds no logs. Fix: for each mlbam_id with duplicates, pick
the canonical row (has espn_id; else active; else lowest id), REPOINT all references
(player_game_logs, props, player_stats, predictions) to it, and delete the duplicates.

Identity-safe: only merges rows that share the SAME mlbam_id (= provably the same person).

Usage:
  python3 dedupe_mlb.py            # dry run
  python3 dedupe_mlb.py --apply    # apply (back up the DB first!)
"""
import sys, os, sqlite3
DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
REF_TABLES = ["player_game_logs", "props", "player_stats", "predictions"]


def pick_canonical(rows):
    # prefer a row with espn_id, then active, then lowest id
    with_espn = [r for r in rows if r["espn_id"]]
    if len(with_espn) == 1:
        return with_espn[0]
    pool = with_espn or rows
    active = [r for r in pool if r["active"]]
    pool = active or pool
    return min(pool, key=lambda r: r["id"])


def main(apply: bool):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    groups = {}
    for r in con.execute("SELECT id, name, espn_id, mlbam_id, active FROM players "
                         "WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0"):
        groups.setdefault(r["mlbam_id"], []).append(r)
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"{'APPLY' if apply else 'DRY RUN'} — {len(dup_groups)} mlbam_ids with duplicate rows")

    repointed = {t: 0 for t in REF_TABLES}
    deleted = 0
    examples = 0
    for mlbam, rows in dup_groups.items():
        canon = pick_canonical(rows)
        dups = [r for r in rows if r["id"] != canon["id"]]
        for d in dups:
            for t in REF_TABLES:
                try:
                    n = con.execute(f"SELECT COUNT(*) FROM {t} WHERE player_id=?", (d["id"],)).fetchone()[0]
                    if n and apply:
                        con.execute(f"UPDATE {t} SET player_id=? WHERE player_id=?", (canon["id"], d["id"]))
                    repointed[t] += n
                except sqlite3.OperationalError:
                    pass
            if apply:
                con.execute("DELETE FROM players WHERE id=?", (d["id"],))
            deleted += 1
        if examples < 4:
            print(f"  {canon['name']} (mlbam {mlbam}): keep id={canon['id']} (espn={canon['espn_id']}), "
                  f"merge {[d['id'] for d in dups]}")
            examples += 1
    if apply:
        con.commit()
    print(f"  rows merged/deleted: {deleted}")
    print(f"  references repointed: {repointed}")
    con.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
