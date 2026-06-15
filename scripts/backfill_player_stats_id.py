#!/usr/bin/env python3
"""One-shot backfill: populate player_stats.player_id via name matching.

Matches by normalized name + league against the players spine.
Handles accent stripping, suffix removal, and period normalization.
Reports before/after counts per league.
"""
import sqlite3, re, unicodedata, os, sys

def _normalize_name(name):
    if not name: return ''
    n = name.lower().strip()
    n = re.sub(r'\b(jr\.?|sr\.?|ii|iii|iv|v)\b', '', n)
    n = re.sub(r'[^\w\s]', '', n)
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('ascii')
    n = re.sub(r'\s+', ' ', n).strip()
    return n

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "data", "picks.db")

def backfill():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # Build name→pid lookup from players table (all leagues)
    print("Building name→player_id lookup from players spine...")
    name_to_pid = {}
    name_team_to_pid = {}
    for r in con.execute("SELECT id, name, league, team FROM players"):
        nname = _normalize_name(r["name"])
        key = (nname, r["league"])
        if key not in name_to_pid:
            name_to_pid[key] = r["id"]
        team_str = (r["team"] or "").strip().upper()
        if team_str:
            name_team_to_pid[(nname, r["league"], team_str)] = r["id"]

    print("  %d (name, league) pairs" % len(name_to_pid))
    print("  %d (name, league, team) pairs" % len(name_team_to_pid))

    # Find rows needing backfill
    rows = con.execute(
        "SELECT id, player_name, name_norm, league, team FROM player_stats WHERE player_id IS NULL OR player_id = 0"
    ).fetchall()
    print("\nRows needing backfill: %d" % len(rows))

    resolved = 0
    unresolved = 0
    batch = []

    for r in rows:
        pid = None
        nname = r["name_norm"] or _normalize_name(r["player_name"])
        league = r["league"]
        team = (r["team"] or "").strip().upper()

        # 1. Team + league match (most specific)
        if team:
            pid = name_team_to_pid.get((nname, league, team))

        # 2. Name + league match
        if pid is None:
            pid = name_to_pid.get((nname, league))

        # 3. Try without suffix stripping (e.g. "Jr." might be part of name in spine)
        if pid is None and r["player_name"]:
            nname_raw = _normalize_name(r["player_name"].replace(".", ""))
            pid = name_to_pid.get((nname_raw, league))
            if pid is None and team:
                pid = name_team_to_pid.get((nname_raw, league, team))

        if pid:
            batch.append((pid, r["id"]))
            resolved += 1
        else:
            unresolved += 1

    # Apply updates
    if batch:
        con.executemany("UPDATE player_stats SET player_id=? WHERE id=?", batch)
        con.commit()
        print("\nBackfill applied: %d resolved, %d unresolved" % (resolved, unresolved))
    else:
        print("\nNo matches found — spine may not cover these players.")

    # After counts
    print("\n--- After backfill ---")
    for lg in ("mlb", "nfl", "nba", "nhl"):
        total = con.execute("SELECT COUNT(*) FROM player_stats WHERE league=?", (lg,)).fetchone()[0]
        with_id = con.execute(
            "SELECT COUNT(*) FROM player_stats WHERE league=? AND player_id IS NOT NULL AND player_id > 0",
            (lg,)
        ).fetchone()[0]
        print("  %s: %d/%d resolved (%.1f%%)" % (lg, with_id, total, with_id/max(total,1)*100))

    con.close()

if __name__ == "__main__":
    backfill()
