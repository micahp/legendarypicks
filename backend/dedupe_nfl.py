#!/usr/bin/env python3
"""
dedupe_nfl.py — remove duplicate NFL player rows, identity-safely.

The players table accumulated id-less STUB rows (no real gsis, no espn_id) that
duplicate a real, fully-identified row of the same name — e.g. "Patrick Mahomes"
id=121 (no ids, no data) shadowing id=14059 (gsis+espn+logs). Name searches hit
the stub and miss the logs.

SAFETY (per the "resolve by ID, never name" rule): we do NOT merge rows that each
carry their own real id — two players named "Mike Adams" with different gsis ids
are different people. We only delete id-less stubs that (a) have a same-name twin
WITH a real id, and (b) have ZERO references in any table. Pure dead orphans.

Usage:
  python3 dedupe_nfl.py            # dry run (default) — prints what it would delete
  python3 dedupe_nfl.py --apply    # delete (back up the DB first!)
"""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sports_service import _normalize_name

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
REF_TABLES = ["player_game_logs", "player_stats", "predictions", "props"]


def has_real_id(r) -> bool:
    return bool(r["nfl_gsis_id"] and str(r["nfl_gsis_id"]).startswith("00-")) or bool(r["espn_id"])


def ref_count(con, pid: int) -> int:
    total = 0
    for t in REF_TABLES:
        try:
            total += con.execute(f"SELECT COUNT(*) FROM {t} WHERE player_id=?", (pid,)).fetchone()[0]
        except sqlite3.OperationalError:
            pass
    return total


def find_targets(con):
    from collections import defaultdict
    rows = con.execute("SELECT id, name, nfl_gsis_id, espn_id FROM players WHERE league='nfl'").fetchall()
    groups = defaultdict(list)
    for r in rows:
        if r["name"]:
            groups[_normalize_name(r["name"])].append(r)
    targets = []
    for v in groups.values():
        if len(v) < 2:
            continue
        if not any(has_real_id(x) for x in v):
            continue  # no canonical twin — these aren't the stub case, leave them
        for x in v:
            if not has_real_id(x) and ref_count(con, x["id"]) == 0:
                targets.append(x)
    return targets


def main(apply: bool):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    targets = find_targets(con)
    print(f"{'APPLY' if apply else 'DRY RUN'} — {len(targets)} id-less ref-less stub rows to delete")
    for t in targets[:8]:
        print(f"  delete id={t['id']} '{t['name']}' (gsis={t['nfl_gsis_id']} espn={t['espn_id']})")
    if len(targets) > 8:
        print(f"  ... +{len(targets) - 8} more")
    if apply and targets:
        con.executemany("DELETE FROM players WHERE id=?", [(t["id"],) for t in targets])
        con.commit()
        remaining = con.execute("SELECT COUNT(*) FROM players WHERE league='nfl'").fetchone()[0]
        print(f"Deleted {len(targets)} stub rows. NFL players now: {remaining}")
    con.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
