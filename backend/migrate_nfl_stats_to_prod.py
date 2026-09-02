#!/usr/bin/env python3
"""Merge the NFL per-game stat keys from the dev DB into the prod DB.

Why this exists and why migrate_logs_to_prod.py could not do it: that script is a
one-shot for an EMPTY prod table -- it plain-INSERTs rows. Prod already holds all
10,717 NFL rows, so the inserts would collide on
UNIQUE(league, source_player_key, season, game_no). What prod is missing is not
rows, it is KEYS INSIDE the stats JSON of rows it already has.

Snap counts (off_snaps/off_pct/st_*) and Next Gen receiving (separation, cushion,
adot, air_yds_share, yac_above_exp) are merged into existing rows by their own
ingest scripts. Those ingests ran against dev and never against prod, so the v0.6.7
usage card -- which is built on snap share and WOPR -- would render as dashes in
prod. HTTP 200 would not have caught it.

Safety:
  - backs prod up first, and refuses to run unless EVERY prod row's stats blob is a
    subset of its dev counterpart with identical values on shared keys. A key-count
    superset check is NOT enough: totals can match while an individual row loses a
    key or has a value silently rewritten. This checks row by row.
  - the only row data it writes is player_game_logs.stats for league='nfl'. It also
    creates two indexes on player_game_logs (see below) -- that is a schema add, not
    a data change, but it is not nothing, so it is stated here rather than buried.
    It never touches props, prop_results or prop_games, which are live and ahead in
    prod, and it verifies their row counts are unchanged before reporting OK.
  - the data change is one transaction; the index builds run after it commits, so
    they cannot extend the write lock held over the data. Re-running is a no-op.
  - the backup is a SQLite ONLINE backup, not a file copy -- picks.db is WAL-mode
    with live writers, where a raw copy can be torn.

Run: python3 migrate_nfl_stats_to_prod.py [--dry-run]   (from backend/)
"""
import sqlite3, datetime, sys, os, json
from collections import Counter

DRY = "--dry-run" in sys.argv
PROD = "data/picks.db"
DEV = "data/picks.dev.db"
for p in (PROD, DEV):
    if not os.path.exists(p):
        sys.exit(f"missing {p}")


def nfl_key_counts(con, schema="main"):
    c = Counter()
    for (s,) in con.execute(f"SELECT stats FROM {schema}.player_game_logs WHERE league='nfl'"):
        c.update(json.loads(s).keys())
    return c


# ── preflight: dev must not be able to erase anything prod has ────────────
chk = sqlite3.connect(f"file:{PROD}?mode=ro", uri=True)
chk.execute(f"ATTACH 'file:{DEV}?mode=ro' AS dev")
prod_keys = nfl_key_counts(chk, "main")
dev_keys = nfl_key_counts(chk, "dev")

# The join must be 1:1 before anything is compared -- a duplicate natural key on
# either side would fan the UPDATE out and could attach one player's line to
# another's row.
for schema in ("main", "dev"):
    dups = chk.execute(f"""SELECT COUNT(*) FROM (
        SELECT 1 FROM {schema}.player_game_logs WHERE league='nfl'
        GROUP BY source_player_key, season, game_no HAVING COUNT(*) > 1)""").fetchone()[0]
    if dups:
        chk.close()
        sys.exit(f"ABORT: {schema} has {dups} duplicate NFL natural keys; join is not 1:1")

# Row-by-row, not just in aggregate: a prod key missing from its dev counterpart,
# or a shared key whose value differs, means the wholesale blob replacement would
# destroy or rewrite prod data.
lost, changed = [], []
for ps, ds in chk.execute("""
        SELECT p.stats, d.stats FROM main.player_game_logs p
        JOIN dev.player_game_logs d ON d.league=p.league
         AND d.source_player_key=p.source_player_key
         AND d.season=p.season AND d.game_no=p.game_no
        WHERE p.league='nfl'"""):
    P, D = json.loads(ps), json.loads(ds)
    for k, v in P.items():
        if k not in D:
            lost.append(k)
        elif D[k] != v:
            changed.append((k, v, D[k]))
if lost or changed:
    chk.close()
    sys.exit(f"ABORT: not purely additive -- {len(lost)} keys would be dropped "
             f"{sorted(set(lost))[:5]}, {len(changed)} values rewritten {changed[:5]}")
print("preflight: purely additive (0 keys dropped, 0 values rewritten)")

prod_rows = chk.execute("SELECT COUNT(*) FROM player_game_logs WHERE league='nfl'").fetchone()[0]
matched = chk.execute("""
    SELECT COUNT(*) FROM main.player_game_logs p
    JOIN dev.player_game_logs d
      ON d.league=p.league AND d.source_player_key=p.source_player_key
     AND d.season=p.season AND d.game_no=p.game_no
    WHERE p.league='nfl'""").fetchone()[0]
props_before = {t: chk.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("props", "prop_results", "prop_games")}
chk.close()

print(f"prod NFL rows: {prod_rows}   matched to a dev row: {matched}")
print(f"dev adds keys: {sorted(set(dev_keys) - set(k for k, n in prod_keys.items() if n))}")
if matched < prod_rows:
    print(f"note: {prod_rows - matched} prod rows have no dev counterpart; they are left untouched")
if DRY:
    print("dry run -- nothing written")
    sys.exit(0)

# ── backup ────────────────────────────────────────────────────────────────
# NOT shutil.copy. picks.db has live same-DB writers: mlb-capture ~every 5min,
# props-prod every 30min, history-prod 4x daily, NFL ADP/transactions daily.
# Copying the file mid-transaction gives a backup that looks fine and is torn
# exactly when it is needed, and this is true in BOTH journal modes for different
# reasons: under `delete` the main file needs its rollback journal to be consistent
# and the copy does not include it, and under `wal` the committed pages may still
# be sitting in the -wal sidecar that the copy also does not include. The online
# backup API takes a transactionally consistent snapshot instead, and it is
# integrity-checked below before any write happens. Same guardrail
# migrate_ufc_rankings_to_prod.py already follows.
#
# (Prod moved from `delete` to `wal` on 2026-08-19 to stop readers and writers
# blocking each other; this comment used to name prod as the delete-mode one.)
ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
bak = f"{PROD}.bak-premigrate-nflstats-{ts}"
src = sqlite3.connect(PROD)
src.execute("PRAGMA busy_timeout=60000")
dst = sqlite3.connect(bak)
with dst:
    src.backup(dst)
dst_check = dst.execute("PRAGMA integrity_check").fetchone()[0]
bak_rows = dst.execute("SELECT COUNT(*) FROM player_game_logs WHERE league='nfl'").fetchone()[0]
dst.close(); src.close()
if dst_check != "ok" or bak_rows != prod_rows:
    sys.exit(f"ABORT: backup is not usable (integrity={dst_check}, nfl_rows={bak_rows} "
             f"vs {prod_rows}); prod untouched")
print(f"backed up prod -> {bak}  (online backup, integrity=ok, {bak_rows} NFL rows)")

# The dev rows are read into memory rather than ATTACHed to the write connection.
# ATTACHing dev read-only and then opening a write transaction fails outright --
# BEGIN IMMEDIATE acquires write locks on EVERY attached database, including the
# read-only one ("attempt to write a readonly database"). Reading first also keeps
# the write transaction as short as possible, which is what matters against timers
# that fire every few minutes. 10,717 rows of JSON is a few MB.
ro = sqlite3.connect(f"file:{DEV}?mode=ro", uri=True)
dev_stats = {(k, s, g): st for k, s, g, st in ro.execute(
    "SELECT source_player_key, season, game_no, stats FROM player_game_logs WHERE league='nfl'")}
ro.close()

con = sqlite3.connect(PROD)
# Wait for a concurrent writer rather than failing or half-applying. Every prod
# writer is a short transaction, so 60s is far more than it can need.
con.execute("PRAGMA busy_timeout=60000")
pending = []
for rid, spk, season, game_no, cur_stats in con.execute(
        "SELECT rowid, source_player_key, season, game_no, stats FROM player_game_logs "
        "WHERE league='nfl'"):
    new_stats = dev_stats.get((spk, season, game_no))
    if new_stats is not None and new_stats != cur_stats:
        pending.append((new_stats, rid))

in_txn = False
try:
    con.execute("BEGIN IMMEDIATE")
    in_txn = True
    con.executemany("UPDATE player_game_logs SET stats=? WHERE rowid=?", pending)
    print(f"updated {len(pending)} rows")
    con.execute("COMMIT")
    in_txn = False
except Exception:
    # Guard the rollback: if BEGIN itself failed there is no transaction to roll
    # back, and an unguarded ROLLBACK raises over the top of the real error.
    if in_txn:
        try:
            con.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
    print(f"prod unchanged (rolled back). Backup at {bak}", file=sys.stderr)
    raise

# ── indexes, AFTER the data commit and outside its transaction ────────────
# Deliberately not folded into the UPDATE transaction: building an index scans
# the whole table, and doing that while holding the write lock taken for the
# data change would extend that lock for the build's duration, against writers
# that fire every few minutes. Separate statements mean the data change commits
# and releases first, and an index that fails to build costs only performance --
# the migration itself is already durable.
for name, ddl in (
    ("idx_pgl_team_game",
     "CREATE INDEX IF NOT EXISTS idx_pgl_team_game ON player_game_logs(league, game_id, team)"),
    ("idx_pgl_team_season_game",
     "CREATE INDEX IF NOT EXISTS idx_pgl_team_season_game ON player_game_logs(league, season, game_no, team)"),
):
    try:
        con.execute(ddl)
        print(f"index {name}: ok")
    except sqlite3.OperationalError as e:
        print(f"index {name}: SKIPPED ({e}) -- data is committed; "
              f"re-run this script to retry, the usage endpoint is just slower until then",
              file=sys.stderr)

# ── verify ────────────────────────────────────────────────────────────────
after = nfl_key_counts(con, "main")
bad = [k for k in ("off_pct", "off_snaps", "air_yds_share", "separation", "adot") if not after[k]]
props_after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in ("props", "prop_results", "prop_games")}
integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
con.close()

print(f"off_pct={after['off_pct']} off_snaps={after['off_snaps']} "
      f"air_yds_share={after['air_yds_share']} separation={after['separation']} adot={after['adot']}")
print(f"props tables unchanged: {props_before == props_after}  ({props_before})")
print(f"integrity_check: {integrity}")
if bad or props_before != props_after or integrity != "ok":
    sys.exit(f"VERIFY FAILED (empty={bad}); restore {bak}")
print("OK")
