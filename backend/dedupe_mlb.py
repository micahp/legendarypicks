#!/usr/bin/env python3
"""
dedupe_mlb.py — merge duplicate MLB player rows that split props from game logs.

The Statcast log ingest (ingest_mlb_logs.py) created its OWN player rows (placeholder
lowercase names, no espn_id) for batters and wrote game logs under them, while
roster_sync/props use the canonical rows (proper name + espn_id). Same mlbam_id, two
rows → the prop-chart join finds no logs. Fix: for each mlbam_id with duplicates, pick
the canonical row (has espn_id; else active; else lowest id), REPOINT all references
(player_game_logs, props, player_stats, roster_memberships, roster_snap) to it, and
delete the duplicates. `predictions` is deliberately NOT repointed: it is game-level
(game_id, league, predicted_winner, correct) and has no player_id column at all.

Identity-safe: only merges rows that share the SAME mlbam_id (= provably the same person).

player_stats collisions: `player_stats` carries UNIQUE(player_id, league, season,
stat_type). 188 of the 317 duplicate groups have BOTH rows carrying a player_stats row
for the same key — two partial `source='statcast'` pulls under two different player_ids,
with DIFFERENT numbers. COALESCE-merging them would blend two snapshots into a number
that was never true; one row must win whole. For each colliding key we keep one row:
  1. higher `games` wins (season-to-date counting stats only grow);
  2. if `games` ties or either is NULL, more non-NULL stat columns wins;
  3. if still tied, lower `rowid` wins.
The loser is deleted inside the same transaction as the repoint, before the UPDATE that
would violate the index. If the winner is the duplicate's row, the canonical's row is the
one deleted — the survivor then carries the canonical player_id via the repoint.

Usage:
  python3 dedupe_mlb.py            # dry run
  python3 dedupe_mlb.py --apply    # apply (back up the DB first!)
"""
import sys, os, sqlite3
DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
# Tables whose rows carry a player_id to repoint. `predictions` is deliberately
# absent: it is game-level (game_id, league, predicted_winner, correct) and has no
# player_id column, so there is nothing to repoint and listing it would only print a
# reassuring zero for a table that was never checked.
REF_TABLES = ["player_game_logs", "props", "player_stats",
              "roster_memberships", "roster_snap"]

# player_stats columns that are identity/metadata, not stats — excluded from the
# "more non-NULL stat columns" tie-break.
_META_COLUMNS = {"id", "player_id", "player_name", "name_norm", "league", "team",
                 "stat_type", "season", "source"}
_STAT_COLUMNS = None  # filled lazily from the live schema


def _stat_columns(con):
    global _STAT_COLUMNS
    if _STAT_COLUMNS is None:
        cols = [r[1] for r in con.execute("PRAGMA table_info(player_stats)")]
        _STAT_COLUMNS = [c for c in cols if c not in _META_COLUMNS]
    return _STAT_COLUMNS


def pick_canonical(rows):
    # prefer a row with espn_id, then active, then lowest id
    with_espn = [r for r in rows if r["espn_id"]]
    if len(with_espn) == 1:
        return with_espn[0]
    pool = with_espn or rows
    active = [r for r in pool if r["active"]]
    pool = active or pool
    return min(pool, key=lambda r: r["id"])


def _pick_player_stats_winner(a, b):
    """Keep one whole player_stats row: higher games, else more non-NULL stat columns,
    else lower rowid (== lower `id`, the INTEGER PRIMARY KEY)."""
    if a["games"] is not None and b["games"] is not None and a["games"] != b["games"]:
        return a if a["games"] > b["games"] else b
    na = sum(1 for col in _STAT_COLUMNS if a[col] is not None)
    nb = sum(1 for col in _STAT_COLUMNS if b[col] is not None)
    if na != nb:
        return a if na > nb else b
    return a if a["id"] < b["id"] else b


def resolve_player_stats_collisions(con, canon_id, dup_id):
    """Find (league, season, stat_type) keys where BOTH canon and dup carry a
    player_stats row, and decide which row loses. Read-only: returns the losing rows.

    A colliding key is exactly the case that makes the repoint UPDATE violate
    UNIQUE(player_id, league, season, stat_type), so the loser must be deleted before
    that UPDATE — in the same transaction (the caller commits at the end)."""
    canon_rows = {}
    dup_rows = {}
    for r in con.execute("SELECT * FROM player_stats WHERE player_id=?", (canon_id,)):
        canon_rows[(r["league"], r["season"], r["stat_type"])] = r
    for r in con.execute("SELECT * FROM player_stats WHERE player_id=?", (dup_id,)):
        dup_rows[(r["league"], r["season"], r["stat_type"])] = r
    losers = []
    for key in set(canon_rows) & set(dup_rows):
        winner = _pick_player_stats_winner(canon_rows[key], dup_rows[key])
        losers.append(dup_rows[key] if winner["id"] == canon_rows[key]["id"] else canon_rows[key])
    return losers


def main(apply: bool):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    _stat_columns(con)
    groups = {}
    for r in con.execute("SELECT id, name, espn_id, mlbam_id, active FROM players "
                         "WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0"):
        groups.setdefault(r["mlbam_id"], []).append(r)
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"{'APPLY' if apply else 'DRY RUN'} — {len(dup_groups)} mlbam_ids with duplicate rows")

    repointed = {t: 0 for t in REF_TABLES}
    deleted = 0
    collisions_resolved = collisions_canonical_kept = collisions_duplicate_kept = 0
    examples = 0
    for mlbam, rows in dup_groups.items():
        canon = pick_canonical(rows)
        dups = [r for r in rows if r["id"] != canon["id"]]
        for d in dups:
            # Resolve player_stats key collisions first: the loser rows must be gone
            # before the repoint UPDATE below, or UNIQUE(player_id, league, season,
            # stat_type) raises. Same transaction — committed once at the end.
            losers = resolve_player_stats_collisions(con, canon["id"], d["id"])
            dup_lost = sum(1 for l in losers if l["player_id"] == d["id"])
            collisions_resolved += len(losers)
            # dup_lost collisions deleted the DUP's row -> the CANONICAL row was kept;
            # the rest deleted the canon's row -> the DUPLICATE's row was kept (and is
            # then repointed to the canonical player_id by the UPDATE below).
            collisions_canonical_kept += dup_lost
            collisions_duplicate_kept += len(losers) - dup_lost
            # Count BEFORE deleting the losers: the count is identical in dry-run
            # and apply modes. If it were taken after the DELETE it would already
            # exclude the loser rows and `n -= dup_lost` would subtract them twice.
            counts = {
                t: con.execute(f"SELECT COUNT(*) FROM {t} WHERE player_id=?", (d["id"],)).fetchone()[0]
                for t in REF_TABLES
            }
            if apply:
                for l in losers:
                    con.execute("DELETE FROM player_stats WHERE id=?", (l["id"],))
            for t in REF_TABLES:
                # No try/except here: every REF_TABLE has a player_id column, so
                # nothing legitimate can raise; a missing or misspelled table name
                # must fail loudly instead of printing a repoint count of zero.
                n = counts[t]
                if t == "player_stats":
                    n -= dup_lost  # the dup's own loser rows are deleted, not repointed
                if n and apply:
                    con.execute(f"UPDATE {t} SET player_id=? WHERE player_id=?", (canon["id"], d["id"]))
                repointed[t] += n
            if apply:
                con.execute("DELETE FROM players WHERE id=?", (d["id"],))
            deleted += 1
        if examples < 4:
            print(f"  {canon['name']} (mlbam {mlbam}): keep id={canon['id']} (espn={canon['espn_id']}), "
                  f"merge {[d['id'] for d in dups]}")
            examples += 1
    if apply:
        con.commit()
    print(f"  collisions resolved: {collisions_resolved} "
          f"(canonical kept {collisions_canonical_kept}, duplicate kept {collisions_duplicate_kept})")
    print(f"  rows merged/deleted: {deleted}")
    print(f"  references repointed: {repointed}")
    if apply:
        # A consolidation without a log line is a defect.
        import name_aliases
        from datetime import datetime, timezone
        name_aliases.record_consolidation({
            "ts": datetime.now(timezone.utc).isoformat(),
            "script": "dedupe_mlb.py",
            "db": os.path.basename(DB),
            "direction": "dup->canonical",
            "groups": [
                {
                    "mlbam": str(mlbam),
                    "keep": {"id": pick_canonical(rows)["id"],
                             "name": pick_canonical(rows)["name"]},
                    "merged": [{"id": r["id"], "name": r["name"]}
                               for r in rows if r["id"] != pick_canonical(rows)["id"]],
                }
                for mlbam, rows in dup_groups.items()
            ],
            "deleted": deleted,
            "repointed": repointed,
            "note": f"{len(dup_groups)} mlbam_ids with duplicate rows -> 0",
        })
    con.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
