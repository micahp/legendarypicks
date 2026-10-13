#!/usr/bin/env python3
"""Remove props whose player_id points at a `players` row that no longer exists.

78 props on both databases reference 15 ids that were deleted from `players`:
27827, 28187, 28188, 28194, 28195, 28209, 28220, 28223, 28227, 28228, 28231,
28233, 28235, 28279, 28293. All are Bovada MLB props from a single day,
2026-06-15, on prop_games 2..8, markets strikeouts / hits_allowed / outs. None
is settled.

They are unrecoverable, verified before deletion rather than assumed: absent
from `players` on both databases, from all 70 .bak files under backend/data,
and from all 58 other picks*.db on this box including every worktree; no merge,
shadow, remap or audit table exists in the schema to say what they became; no
raw Bovada payload for that date is retained; and `props` stores player_id
only, never a name. The id is OURS -- an autoincrement pointer -- so unlike a
publisher id it cannot be re-fetched.

They are also what blocks `PRAGMA foreign_keys=ON`. `prop_results.prop_id` and
`props.player_id` are both DECLARED foreign keys already; SQLite defaults
enforcement off, so the declarations have never fired.

Scoped by construction: the delete selects rows via a LEFT JOIN that is NULL on
`players`, so a prop whose player exists can never match. It reports the counts
it will remove, backs up first, and aborts if the delta is not exactly what it
announced.

  python3 scripts_drop_orphan_props.py --db data/picks.dev.db --check
  python3 scripts_drop_orphan_props.py --db data/picks.dev.db --apply
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timezone

FIND = """SELECT p.id FROM props p
          LEFT JOIN players pl ON pl.id = p.player_id
          WHERE p.player_id IS NOT NULL AND pl.id IS NULL"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    ids = [r[0] for r in con.execute(FIND)]
    total_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    total_results = con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0]
    settled = con.execute(
        f"SELECT COUNT(*) FROM prop_results WHERE prop_id IN ({FIND})").fetchone()[0]
    dead_players = [r[0] for r in con.execute(
        """SELECT DISTINCT p.player_id FROM props p LEFT JOIN players pl ON pl.id=p.player_id
           WHERE p.player_id IS NOT NULL AND pl.id IS NULL ORDER BY 1""")]
    print(f"{args.db}")
    print(f"  props table        : {total_props}")
    print(f"  prop_results table : {total_results}")
    print(f"  orphaned props     : {len(ids)}")
    print(f"  ...of which settled: {settled}")
    print(f"  dead player ids    : {len(dead_players)} {dead_players}")
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    print(f"  fk violations now  : {len(fk)}")

    if args.check:
        print("  check only -- nothing written")
        return 0
    if not ids:
        print("  nothing to remove")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{args.db}.pre-drop-orphan-props-{stamp}.bak"
    con.execute("VACUUM INTO ?", (backup,))
    ok = sqlite3.connect(backup).execute("PRAGMA quick_check").fetchone()[0]
    print(f"  backup: {backup} (quick_check={ok})")
    if ok != "ok":
        raise SystemExit("backup failed quick_check; nothing removed")

    con.execute("BEGIN IMMEDIATE")
    dropped_results = con.execute(
        f"DELETE FROM prop_results WHERE prop_id IN ({FIND})").rowcount
    dropped_props = con.execute(f"DELETE FROM props WHERE id IN ({FIND})").rowcount
    con.commit()

    after_props = con.execute("SELECT COUNT(*) FROM props").fetchone()[0]
    after_results = con.execute("SELECT COUNT(*) FROM prop_results").fetchone()[0]
    left = len([r[0] for r in con.execute(FIND)])
    fk_after = con.execute("PRAGMA foreign_key_check").fetchall()
    print(f"  removed {dropped_props} props and {dropped_results} prop_results")
    print(f"  props {total_props} -> {after_props} (delta {total_props - after_props},"
          f" expected {len(ids)})")
    print(f"  prop_results {total_results} -> {after_results}"
          f" (delta {total_results - after_results}, expected {settled})")
    print(f"  orphans remaining  : {left}")
    print(f"  fk violations now  : {len(fk_after)}")
    if total_props - after_props != len(ids) or total_results - after_results != settled:
        raise SystemExit("REMOVED MORE THAN EXPECTED -- restore from the backup above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
