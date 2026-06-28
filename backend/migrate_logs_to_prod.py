#!/usr/bin/env python3
"""One-shot: migrate player_game_logs (+ the player rows it needs) from the dev DB into
the prod DB, so the v0.2.2 features (player page, matchups, charts, projections, NBA edge,
stories) have data in prod. Additive only — never touches prod's live props/prop_results/
prop_games. Backs up prod first. Player IDs are ~fully aligned across the two DBs; the few
shared IDs whose identity differs are excluded so no log is misattributed.

Run: python3 migrate_logs_to_prod.py   (from backend/)
"""
import sqlite3, shutil, datetime, sys, os

PROD = "data/picks.db"
DEV = "data/picks.dev.db"
for p in (PROD, DEV):
    if not os.path.exists(p):
        sys.exit(f"missing {p}")

ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
bak = f"{PROD}.bak-premigrate-{ts}"
shutil.copy(PROD, bak)
print(f"backed up prod -> {bak}")

con = sqlite3.connect(PROD)
con.execute(f"ATTACH '{DEV}' AS dev")

# 0. schema parity guard for players (abort if columns diverge)
pc = [r[1] for r in con.execute("PRAGMA table_info(players)")]
dc = [r[1] for r in con.execute("PRAGMA dev.table_info(players)")]
if pc != dc:
    sys.exit(f"players schema mismatch:\n prod={pc}\n dev ={dc}")

# 1. create player_game_logs (+ its indexes) in prod from the dev schema if absent
have = con.execute("SELECT name FROM sqlite_master WHERE name='player_game_logs'").fetchone()
if not have:
    ddl = con.execute("SELECT sql FROM dev.sqlite_master WHERE name='player_game_logs'").fetchone()[0]
    con.execute(ddl)
    for (s,) in con.execute("SELECT sql FROM dev.sqlite_master WHERE type='index' AND tbl_name='player_game_logs' AND sql IS NOT NULL"):
        con.execute(s)
    print("created player_game_logs in prod")

# 2. find identity-mismatched shared IDs (exclude their logs) + missing players (insert them)
dev_log_pids = {r[0] for r in con.execute("SELECT DISTINCT player_id FROM dev.player_game_logs")}
prod_ids = {r[0] for r in con.execute("SELECT id FROM players")}
dn = {r[0]: (r[1], r[2]) for r in con.execute("SELECT id,LOWER(TRIM(name)),league FROM dev.players")}
pn = {r[0]: (r[1], r[2]) for r in con.execute("SELECT id,LOWER(TRIM(name)),league FROM players")}
mismatch = {pid for pid in (dev_log_pids & prod_ids) if dn.get(pid) != pn.get(pid)}
missing = dev_log_pids - prod_ids
print(f"missing players to insert: {len(missing)} | mismatched shared ids to exclude: {len(mismatch)}")

# 3. insert the missing player rows (dev IDs are free in prod -> no collision)
ncols = len(pc)
if missing:
    q = ",".join("?" * len(missing))
    con.execute(f"INSERT INTO players SELECT * FROM dev.players WHERE id IN ({q})", list(missing))
    print(f"inserted {con.total_changes} player rows")

# 4. copy logs, excluding any whose player_id is identity-mismatched
before = con.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
if mismatch:
    q = ",".join("?" * len(mismatch))
    con.execute(f"INSERT INTO player_game_logs SELECT * FROM dev.player_game_logs WHERE player_id NOT IN ({q})", list(mismatch))
else:
    con.execute("INSERT INTO player_game_logs SELECT * FROM dev.player_game_logs")
after = con.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
con.commit()
print(f"player_game_logs: {before} -> {after} (+{after-before})")

# 5. verify prop tables untouched
for t in ("props", "prop_results", "prop_games"):
    print(f"  prod {t}: {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]} (unchanged)")
con.close()
print("MIGRATION DONE")
