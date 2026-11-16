# PLAN: ATP tennis data fixes (findings 1, 4, 5, 6, 7, 8), dev DB

Date: 2026-10-13. Status: PLAN ONLY. No code was changed, no DB write was made, nothing was committed.
Owner of decisions: Micah. Executing agents: the task cards in section 7.

Target DB: `/root/legendarypicks/backend/data/picks.dev.db` (dev only).
Never open `backend/data/picks.db` (prod). Read-only opens use `file:<path>?mode=ro` (sqlite3 URI).

---

## 0. Facts verified before writing this plan

Every claim below was measured read-only on 2026-10-13 unless marked otherwise. Expected values in the later sections come from these measurements.

| Claim (from the brief) | Measured | Status |
|---|---|---|
| Matches 988,216; doubles 26,399; rankings 3,420,595; players 66,912; source 176 | 988,216 / 26,399 / 3,420,595 / 66,912 / 176 | Confirmed |
| Finding 1: no ingest audit row | `ingest_runs` has 16,838 rows; 0 rows with provider like tennis/atp/usopen | Confirmed |
| Finding 1: first load failed on text 'R' | `scratch/tennis-scripts/load.log` ends with `ValueError: atp_matches_amateur.csv rec 580 col draw_size: non-integer 'R'`. `load2.log` ends `LOAD DONE 2026-10-13T20:59:49+00:00` | Confirmed |
| Finding 1: script exits if tables exist | `load.py` line 163: `sys.exit("ABORT: tables already exist")` | Confirmed |
| Finding 4: 780 duplicate (date, player) pairs, 580 conflicting | 780 and 580 | Confirmed |
| Finding 4 example 20240101 / 208147 | rows 767/32 pts and 1279/5 pts, both in `atp_rankings_20s.csv` | Confirmed. Both rows come from the same file |
| Finding 5: tourney_id + match_num has 0 duplicates | 0 (singles) | Confirmed for singles only. Doubles, players and rankings not yet measured |
| Finding 6: 1,582 text 'R', 835 NULL | 1,582 text, all 'R', all from `atp_matches_amateur.csv`. 835 NULL, from `atp_matches_1968.csv` | Confirmed. The NULL source is new information |
| Finding 7: futures 523,355 | S 429,781 + '15' 58,502 + '25' 35,072 = 523,355 | Confirmed |
| Finding 7: challenger/qualifier 240,471 | `tourney_level = 'C'` is 208,233 | NOT confirmed. Recount in section 4 |
| Finding 7: amateur 25,001 | No level code 'amateur' exists. The amateur CSV holds 25,001 rows under levels G (20,201) and D (4,800) | Corrected: amateur rows are not a separate level |
| Finding 7: 74% no serve stats | `w_ace IS NULL` 728,535 of 988,216 = 73.7% | Confirmed |
| Finding 8: no overlap of ATP ids and players.id | ATP ids 100001 to 214629. players.id 1 to 66782. Overlap 0 | Confirmed |
| Finding 8: 0 ATP rows in player_source_ids | 0 rows whose source contains atp or tennis | Confirmed for that filter. Recheck with a full GROUP BY (section 4) |
| US Open rows: 'US Open' (16,616, 2019 and earlier) and 'Us Open' (1,322, 2020 to 2025) | Confirmed. 'Us Open' latest tourney_date 20250825. No 2026 rows | Confirmed |
| US Open 139 years at level G | 'US Open' spans back to 18810905. 895 rows dated before 1900 under the name. All 1,575 pre-1900 rows are in the amateur CSV | Corrected: pre-1968 amateur-era rows are mixed into G |
| Backup covers the load | **The backup has NO tennis_atp_* tables** (247 objects, none named tennis_atp%). Backup mtime 15:51 local. Load finished 20:59 UTC (15:59 local) | NEW, critical for rollback. See section 1.3 |
| Clock | `date -u` 22:21 UTC; `uptime` 17:21 local (UTC-5). LOAD DONE timestamp is consistent | Confirmed |
| Box state at check | load average 2.9 to 6.5; available RAM 2.2 GB; free 146 to 214 MB; swap fully used; disk 78 GB free | Heavy queries need the resource gate in section 1.2 |

Level codes present (10): S, C, A, G, M, D, F, O, 15, 25. Counts: S 429,781; C 208,233; A 146,224; G 60,036; M 29,710; D 19,970; F 624; O 64; 15 58,502; 25 35,072. Sum = 988,216.
Meaning of each code is taken from Sackmann's README (`UPSTREAM_README.md` in the scratch folder). It must be read in task T5, not assumed here.

US Open structure, 2024 and 2025 (`tourney_id` 2024-560 and 2025-560, name 'Us Open'), measured: R128 64, R64 32, R32 16, R16 8, QF 4, SF 2, F 1 = **127 main-draw matches per year**. Q1 64, Q2 32, Q3 16 = **112 qualifying matches per year**. Total 239 per year.

---

## 1. Rules and guards for every executing agent

### 1.1 Rules (copied to every task card)
- Dev DB only: `picks.dev.db`. Never `picks.db`.
- No npm, npx or yarn, from a worktree or elsewhere.
- No server start, stop or restart. The dev server is externally managed. Do not kill its PID.
- No `git push`. No `git add -A`; stage named files only. Commit only if the task card says so and only the named files.
- No em dashes (the character U+2014) or en dashes in any written text: reports, commit messages, docs, SQL comments. Use commas, colons or hyphens.
- Reproduce before any fix. A task that changes data first runs its measurement and records the before value.
- Do not call any ESPN host (site.api.espn.com, sports.core.api.espn.com, site.web.api.espn.com, lm-api-reads.fantasy.espn.com). This plan needs none.
- Scratch files go to the agent's scratchpad directory, not the repo, except the file named in the task card.
- Untrusted data: scratch CSVs and the loader are read-only. Never execute the loader. If the repo copy is written (task T5), it is written by hand from the reading, and it is reviewed before it runs.

### 1.2 Resource gate (before any query over tennis_atp_rankings or tennis_atp_matches)
```
uptime
free -h
df -h /root | tail -1
```
- Proceed only if `MemAvailable` (free -h "available") is at least 1.5 GB and load average is below 8.
- Run one heavy query at a time, wrapped in `timeout 300`.
- Any GROUP BY over rankings (3.4M rows) or matches (988k rows) is heavy. Prefer the indexed columns.
- If the gate fails, stop and report. Do not retry in a loop.

### 1.3 Rollback model (READ THIS, the backup does not cover the load)
- The file backup `backend/data/backups-tennis-20261013/picks.dev.db.pre-tennis-atp-20261013.bak` was taken BEFORE the ATP load (no tennis_atp tables inside it). Its only use is to undo the whole load: drop the five tennis_atp tables and the new objects.
- It cannot undo a single fix. The dev DB has changed since then (dev file mtime 17:19 local) by other processes. Restoring the whole file would discard unrelated writes. Do NOT restore the whole file. Also a restore while the dev server holds the file is a server action, which needs Micah.
- Per-fix rollback is table-level, using a snapshot taken in the task itself before any write (section 1.4).

### 1.4 Snapshot before every write (task-level, not whole file)
Each write task first writes its snapshot to a NEW file, never into the dev DB:
```
sqlite3 /root/legendarypicks/backend/data/backups-tennis-20261013/snap-<task>-20261013.db <<'SQL'
ATTACH 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro' AS dev;
CREATE TABLE tennis_atp_matches AS SELECT * FROM dev.tennis_atp_matches;
-- repeat for each table the task touches
SQL
```
(Adjust the list to the tables the task touches. The snapshot file is a separate DB, so the dev schema is not changed. Check free disk first. Rankings is about 150 MB.)
Restore for a table: `ATTACH` the snapshot read-only, then `DROP TABLE main.<t>` and `CREATE TABLE main.<t> AS SELECT * FROM snap.<t>`, then recreate that table's indexes from `.schema` in section 2.

---

## 2. Task graph and model tiers

| Task | Finding(s) | Depends on | Writes | Tier |
|---|---|---|---|---|
| T0 Baseline and guards | all | none | scratch only | Haiku (mechanical) |
| T1 Reproduce and make the loader reproducible | 1 | T0 | repo file (new), scratch repro DB | Sonnet |
| T2 US Open validation baseline (read-only) | 5, 6, 7 accuracy | T0 | scratch only | Opus (mismatch triage) |
| T3 draw_size split | 6 | T1 (loader change) | dev: 2 tables (column add, update) | Sonnet |
| T4 Rankings duplicate policy and quarantine | 4 | T1, T3 (same loader file) | dev: 1 new table, 1 table delete | Opus (policy choice) |
| T5 Unique indexes | 5 | T4 for rankings. Matches, doubles and players can run after T0 | dev: 3 or 4 indexes | Sonnet |
| T6 Tour vs lower-level views | 7 | Micah decisions D4 | dev: 2 views | Sonnet |
| T7 Player crosswalk | 8 | Micah decisions D3 and D1, D2 | dev: 1 new table, or rows in player_source_ids | Opus (name review) |
| T8 Final validation | all | T1 to T7 | none | Haiku (mechanical) |

Order that avoids conflicts: T0 first. Then T1, T2 and T5 (matches, doubles, players) in parallel. Then T3, T4 in sequence (same loader). Then T5 rankings index. Then T6 and T7 after decisions. T8 last.

Rows in the table are independent units. A task that cannot finish in one session stops at a checkpoint and reports the snapshot path.

---

## 3. Findings: measure, fix, verify, roll back

Conventions: `DEV` means `file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro` for reads. Writes are described, never executed in this plan.

### 3.1 Finding 1: not reproducible (loader and CSVs outside repo, no audit row, first run failed)

**Measure (read-only)**
1. `SELECT COUNT(*) FROM ingest_runs WHERE provider LIKE '%tennis%' OR provider LIKE '%atp%' OR provider LIKE '%usopen%';` Expected 0 (observed 0).
2. `SELECT COUNT(*) FROM tennis_atp_source;` Expected 176. Also `SELECT COUNT(*) FROM tennis_atp_source WHERE rows_loaded <> data_records;` Expected 0 (not yet measured).
3. Checksum each scratch file against `tennis_atp_source.sha256`. Run `sha256sum` in the scratch folder `/tmp/claude-0/-root/95e95d67-12cc-44b0-8b87-6ab643c25e63/scratchpad/tennis-sackmann/` and compare with the DB column. Expected: all 176 match (not yet measured). A mismatch means the source changed after load and blocks the reproduction claim.
4. `git -C /root/legendarypicks ls-files | grep -i -E 'tennis_atp|sackmann'` Expected: no output (the only tennis ingest in repo is `backend/ingest_tennis_players.py`, a different source, TennisExplorer).
5. Confirm the two log endings listed in section 0.

**Fix (T1, Sonnet)**
1. Read `load.py`, `fetch.py`, `headers.py`, `backup.py` in the scratch tennis-scripts folder (read only). Do not run them.
2. Write one repo file, named `backend/ingest_tennis_atp_sackmann.py`, by hand, with these behaviours:
   - DB path is an argument. Default is `backend/data/picks.dev.db`. Keep the basename check so a prod path is refused.
   - Reads CSVs from an explicit directory argument. For each file, verifies sha256 against a pinned manifest committed next to the script (`backend/data/tennis_atp_sackmann_manifest.json`, generated once, not by hand). Fails on any mismatch.
   - Handles the draw_size rule from T3 (text values go to `draw_size_text`).
   - Refuses to run when the tables exist, unless `--rebuild` is passed. `--rebuild` first takes the snapshot in section 1.4.
   - Writes exactly one row to `ingest_runs` (columns: provider `tennis_atp_sackmann`, db_path, started_at, finished_at, status, exit_code, detail = JSON with file count, row counts per table, manifest hash). Use the existing `ingest_runs` columns from the schema; do not add columns.
   - Keeps the memory gate (abort below 1.5 GB MemAvailable).
   - Uses `sqlite3` with `timeout=120` and one transaction per table.
3. Write one test file `backend/test_ingest_tennis_atp_sackmann.py` that runs the loader against a small fixture of 3 CSV rows in a temp dir and an empty DB in the scratchpad. It must fail on a text draw_size with the old behaviour and pass with the new one.
4. Commit: stage only the two new files and the manifest, by name. Commit message in plain words, no AI attribution.

**Reproduction (before the fix, T1)**
- Run the current `load.py` against an EMPTY scratch DB (`/tmp/claude-0/.../scratchpad/repro-empty.db`), with the DB path edited in a scratch copy. Expected: fails at amateur rec 580 with the 'R' ValueError, same as `load.log`. This proves the failure without touching dev.
- Run the new loader against the same empty scratch DB. Expected: completes, `tennis_atp_source` 176 rows, one `ingest_runs` row, no abort.
- Compare the scratch repro's row counts with the dev counts (matches 988,216, doubles 26,399, rankings 3,420,595, players 66,912). Expected equal.

**Verify**
- `python3 -m pytest backend/test_ingest_tennis_atp_sackmann.py -q` (from `/root/legendarypicks/backend`, with the repo's python). Expected: passes.
- Repro row counts equal dev counts (above).

**Rollback**
- Repo: delete the two new files (`git rm` is not needed; they are untracked until committed). Revert the commit if committed. No DB rollback, because T1 writes only to scratch.

**Dependency**: T3 and T4 edit the same loader. T1 must land first.

---

### 3.2 Finding 6: draw_size INTEGER holds 1,582 text 'R' values and 835 NULL

**Measure (read-only)**
1. `SELECT typeof(draw_size), COUNT(*) FROM tennis_atp_matches GROUP BY 1;` Expected: integer 985,799; text 1,582; null 835.
2. `SELECT DISTINCT draw_size FROM tennis_atp_matches WHERE typeof(draw_size)='text';` Expected: 'R' only.
3. `SELECT source_file, COUNT(*) FROM tennis_atp_matches WHERE typeof(draw_size)='text' GROUP BY 1;` Expected: atp_matches_amateur.csv 1582.
4. `SELECT source_file, COUNT(*) FROM tennis_atp_matches WHERE draw_size IS NULL GROUP BY 1;` Expected: atp_matches_1968.csv 835 (plus any others, measured now).
5. `SELECT typeof(draw_size), COUNT(*) FROM tennis_atp_matches_doubles GROUP BY 1;` Expected: check for text. Not yet measured.
6. `SELECT source_file, draw_size_text_kept FROM tennis_atp_source WHERE draw_size_text_kept > 0;` Expected: the amateur file, 1582.
7. Meaning of 'R': read it in `UPSTREAM_README.md` (scratch folder). Not assumed here. Record the sentence in the report.

**Fix (T3, Sonnet)**
1. Snapshot `tennis_atp_matches` and `tennis_atp_matches_doubles` (section 1.4).
2. Loader change (in the T1 file): a non-integer draw_size is stored as NULL in `draw_size` and as its text in a new column `draw_size_text TEXT`.
3. Apply to dev (after the snapshot), one transaction:
```
ALTER TABLE tennis_atp_matches ADD COLUMN draw_size_text TEXT;
UPDATE tennis_atp_matches
   SET draw_size_text = draw_size, draw_size = NULL
 WHERE typeof(draw_size) = 'text';
-- same for doubles if step 5 found text values
```
4. Do not change the 835 NULLs. They are missing in the source. Document them in the report.

**Verify (expected results)**
- `SELECT COUNT(*) FROM tennis_atp_matches WHERE typeof(draw_size) = 'text';` returns **0**.
- `SELECT COUNT(*) FROM tennis_atp_matches WHERE draw_size_text IS NOT NULL;` returns **1582**.
- `SELECT COUNT(*) FROM tennis_atp_matches WHERE draw_size IS NULL;` returns **2417** (835 + 1582).
- `SELECT COUNT(*) FROM tennis_atp_matches;` still returns **988,216**.
- Loader repro (T1 scratch DB) shows the same counts.

**Rollback**
- `UPDATE tennis_atp_matches SET draw_size = draw_size_text WHERE draw_size_text IS NOT NULL;` then `ALTER TABLE tennis_atp_matches DROP COLUMN draw_size_text;` (needs SQLite 3.35 or later; check `sqlite3 --version` first). Or restore the two tables from the T3 snapshot.

---

### 3.3 Finding 4: 780 duplicate (ranking_date, player) pairs, 580 conflicting

**Measure (read-only; heavy, run under section 1.2 gate)**
1. Duplicate pairs:
```
SELECT COUNT(*) FROM (SELECT ranking_date, player FROM tennis_atp_rankings GROUP BY 1,2 HAVING COUNT(*) > 1);
```
Expected 780.
2. Conflicting pairs:
```
SELECT COUNT(*) FROM (SELECT ranking_date, player FROM tennis_atp_rankings GROUP BY 1,2
  HAVING COUNT(*) > 1 AND (COUNT(DISTINCT rank) > 1 OR COUNT(DISTINCT points) > 1));
```
Expected 580. Identical duplicates: 200 (780 minus 580).
3. By year, conflicting pairs: same query with `substr(ranking_date,1,4)` grouped. Expected: concentrated 2019 to 2023.
4. Source file of the duplicated rows: join back on (ranking_date, player) and group by source_file. Expected: a small number of files, including `atp_rankings_20s.csv`.
5. Example: `SELECT ranking_date, rank, points, source_file FROM tennis_atp_rankings WHERE ranking_date = 20240101 AND player = 208147;` Expected 767/32 and 1279/5 from `atp_rankings_20s.csv`.
6. Check whether the two rows in the example are a second ranking block in the same file. Read the CSV lines for date 20240101 (read only, grep for 208147).

**Fix (T4, Opus)**
Policy (recommended, Micah to confirm as D6): never choose silently.
1. Identical duplicates (200 pairs): keep one row. Delete the extra copies.
2. Conflicting duplicates (580 pairs): move ALL rows of each conflicting pair to a new quarantine table `tennis_atp_rankings_conflicts` (same columns plus `reason TEXT`). Delete them from `tennis_atp_rankings`. Joins then see no row for those pairs, which is the "missing row is unknown" rule.
3. Do not pick the "right" row by rank order or points order. A rule that looks right can be wrong, and the repo rule is "ambiguous key misses, never guesses".
4. Also add the same policy to the T1 loader, so a re-run produces the same result.

Steps for dev (after a snapshot of `tennis_atp_rankings`, section 1.4, which is about 150 MB):
```
CREATE TABLE tennis_atp_rankings_conflicts AS
  SELECT r.*, 'conflicting_duplicate' AS reason FROM tennis_atp_rankings r
  JOIN (SELECT ranking_date, player FROM tennis_atp_rankings GROUP BY 1,2
        HAVING COUNT(*) > 1 AND (COUNT(DISTINCT rank) > 1 OR COUNT(DISTINCT points) > 1)) d
  USING (ranking_date, player);
DELETE FROM tennis_atp_rankings WHERE rowid IN (
  SELECT r.rowid FROM tennis_atp_rankings r JOIN tennis_atp_rankings_conflicts c
    ON c.ranking_date = r.ranking_date AND c.player = r.player);
-- identical duplicates: keep min(rowid), delete the rest
DELETE FROM tennis_atp_rankings WHERE rowid NOT IN (
  SELECT MIN(rowid) FROM tennis_atp_rankings GROUP BY ranking_date, player);
```
Run as a single transaction, in this order (the identical-duplicate delete runs last, so it only sees the non-conflicting pairs).

**Verify (expected results)**
- `SELECT COUNT(*) FROM (SELECT ranking_date, player FROM tennis_atp_rankings GROUP BY 1,2 HAVING COUNT(*) > 1);` returns **0**.
- `SELECT COUNT(DISTINCT ranking_date || '|' || player) FROM tennis_atp_rankings_conflicts;` returns **580**.
- `SELECT COUNT(*) FROM tennis_atp_rankings_conflicts;` returns the number of ROWS quarantined (about 1,160 if every conflicting pair has exactly 2 rows; measure, do not assume).
- `SELECT COUNT(*) FROM tennis_atp_rankings;` returns 3,420,595 minus (200 identical extra rows) minus (quarantined rows). Report the exact arithmetic.

**Rollback**
- `INSERT INTO tennis_atp_rankings SELECT ranking_date, rank, player, points, source_file, loaded_at FROM tennis_atp_rankings_conflicts;` (the identical extras are restored from the snapshot).
- Or restore `tennis_atp_rankings` from the snapshot and `DROP TABLE tennis_atp_rankings_conflicts`.

**Dependency**: after T3 and T1. Blocks T5's rankings index.

---

### 3.4 Finding 5: no primary keys or unique indexes on the four tables

**Measure (read-only)**
1. Matches: `SELECT COUNT(*) FROM (SELECT tourney_id, match_num FROM tennis_atp_matches GROUP BY 1,2 HAVING COUNT(*) > 1);` Expected 0 (observed 0).
2. Matches NULL keys: `SELECT COUNT(*) FROM tennis_atp_matches WHERE tourney_id IS NULL OR match_num IS NULL;` Expected 0 (not yet measured).
3. Doubles: same two queries on `tennis_atp_matches_doubles`. Expected 0 and 0 (not yet measured).
4. Players: `SELECT COUNT(*) - COUNT(DISTINCT player_id), SUM(player_id IS NULL) FROM tennis_atp_players;` Expected 0 and 0 (not yet measured).
5. Rankings: after T4 only, same as finding 4 check. Expected 0 duplicates.
6. Confirm no unique index exists: `SELECT name, sql FROM sqlite_master WHERE tbl_name LIKE 'tennis_atp%' AND type='index';` Expected: only the non-unique `idx_tennis_atp_*` indexes.

**Fix (T5, Sonnet)**
Use UNIQUE indexes, not a table rebuild. A PRIMARY KEY on these tables needs a full rebuild of 3.4M rows, which is not justified here. Unique indexes give the same guard.
```
CREATE UNIQUE INDEX ux_tennis_atp_matches_tourney_match ON tennis_atp_matches (tourney_id, match_num);
CREATE UNIQUE INDEX ux_tennis_atp_matches_doubles_tourney_match ON tennis_atp_matches_doubles (tourney_id, match_num);
CREATE UNIQUE INDEX ux_tennis_atp_players_player_id ON tennis_atp_players (player_id);
-- only after T4 verify = 0:
CREATE UNIQUE INDEX ux_tennis_atp_rankings_date_player ON tennis_atp_rankings (ranking_date, player);
```
Create each index only if its measure is 0. If a measure is not 0, stop and report. Do not dedupe in this task.
The old non-unique indexes stay (they serve the existing queries).

**Verify**
- `SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ux_tennis_atp%';` returns the 3 or 4 names above.
- Insert test is NOT allowed on dev. Verify the guard in a scratch copy of the schema: create an empty scratch DB with the same CREATE TABLE and index, insert a duplicate, expect `UNIQUE constraint failed`.

**Rollback**: `DROP INDEX ux_tennis_atp_...;` for each created index. Nothing else changes.

**Dependency**: matches, doubles and players can run after T0. Rankings after T4.

---

### 3.5 Finding 7: all levels in one table (tour, futures, challenger, amateur)

**Measure (read-only)**
1. Level counts (confirmed in section 0). Re-run:
`SELECT tourney_level, COUNT(*) FROM tennis_atp_matches GROUP BY 1 ORDER BY 2 DESC;`
Expected exactly as in section 0. Challenger 'C' is 208,233 (the brief's 240,471 is not confirmed).
2. Futures: `SELECT COUNT(*) FROM tennis_atp_matches WHERE tourney_level IN ('S','15','25');` Expected 523,355.
3. Pre-1968 rows: `SELECT COUNT(*) FROM tennis_atp_matches WHERE tourney_date < 19680101;` Expected 1,575 (all in the amateur file, measured). Confirm the file: `SELECT source_file, COUNT(*) FROM tennis_atp_matches WHERE tourney_date < 19680101 GROUP BY 1;`
4. Amateur file levels: `SELECT tourney_level, COUNT(*) FROM tennis_atp_matches WHERE source_file = 'atp_matches_amateur.csv' GROUP BY 1;` Expected G 20,201 and D 4,800.
5. Serve-stat coverage by level: `SELECT tourney_level, COUNT(*), SUM(w_ace IS NULL) FROM tennis_atp_matches GROUP BY 1;` Expected: S 429,781 of 429,781 null. Other levels to be measured.
6. Total serve-null: 728,535 of 988,216 (73.7%).
7. Read `UPSTREAM_README.md` for the level code meanings, and record them in the report. Not assumed.

**Fix (T6, Sonnet, after Micah decides D4)**
Non-destructive. Two views, no row moves, no table drops.
```
CREATE VIEW tennis_atp_tour_matches AS
  SELECT * FROM tennis_atp_matches
  WHERE tourney_level IN ('G','M','A','F','O')            -- adjust per D4 (Davis Cup D, qualifiers)
    AND tourney_date >= 19680101;
CREATE VIEW tennis_atp_lower_matches AS
  SELECT * FROM tennis_atp_matches
  WHERE tourney_level IN ('C','S','15','25');
```
Decision D4 sets the membership. Default in this plan: Davis Cup 'D' is excluded from tour (it is not an ATP tour event); qualifying rounds Q1 to Q3 stay in tour (they are ATP-level entries). Micah confirms.
Amateur-era rows (pre-1968) are excluded from both views and stay in the base table.
Also note the 'O' (Olympics) row count is 64. Its membership is part of D4.

**Verify (expected results)**
- `SELECT (SELECT COUNT(*) FROM tennis_atp_tour_matches) + (SELECT COUNT(*) FROM tennis_atp_lower_matches) + (SELECT COUNT(*) FROM tennis_atp_matches WHERE tourney_date < 19680101 OR tourney_level = 'D') = 988216;` returns **1**. Shows no overlap and no drop.
- Test each view returns no level outside its list.

**Rollback**: `DROP VIEW tennis_atp_tour_matches; DROP VIEW tennis_atp_lower_matches;`

**Note**: the serve-stat gap is a property of the source for lower levels, not a bug. Do not impute serve stats. The views do not change it.

---

### 3.6 Finding 8: no link from ATP ids to LP players

**Measure (read-only)**
1. ID ranges: `SELECT MIN(player_id), MAX(player_id), COUNT(*) FROM tennis_atp_players;` Expected 100001, 214629, 66912 (measured).
2. LP range: `SELECT MIN(id), MAX(id), COUNT(*) FROM players;` Expected 1, 66782, 61354 (measured).
3. Overlap: `SELECT COUNT(*) FROM players p JOIN tennis_atp_players a ON a.player_id = p.id;` Expected 0 (measured).
4. Crosswalk table: `SELECT source, league, COUNT(*) FROM player_source_ids GROUP BY 1,2;` Expected: no atp or tennis row (measure all sources and leagues).
5. The tennis ranking snapshot: `SELECT COUNT(DISTINCT espn_athlete_id), COUNT(DISTINCT player_id) FROM tennis_ranking_snapshots WHERE tour = 'atp';` Expected 161 and up to 161 (not yet measured; the brief says 161). `tennis_ranking_snapshots` has 13,800 rows in total, and its `player_id` already points at `players.id`.
6. Name match: `PRAGMA table_info(players);` to get the name column first. Then join the ATP players to `players` on normalised name (lower case, accents removed, first + last). Expected about 154 of 161 (brief's figure, NOT confirmed here).
7. Per-player review of the 7 unmatched and every name match with more than one candidate. Record the ATP id, the LP id, the publisher's first and last name, the LP name, and the decision.
8. Check the ESPN-linked identity: each name match must also agree on country (IOC vs LP country if the column exists) where available. Record the count that disagrees.

**Fix (T7, Opus, after decisions D1, D2, D3)**
Rule from the repo: resolve, or queue. Never insert a second `players` row for one human, and never link on a display name alone.
1. Create `tennis_atp_player_xwalk`:
```
CREATE TABLE tennis_atp_player_xwalk (
  atp_player_id INTEGER PRIMARY KEY,           -- tennis_atp_players.player_id
  lp_player_id  INTEGER REFERENCES players(id),-- NULL = queued
  method        TEXT NOT NULL,                 -- 'name_exact_reviewed' | 'queued' | 'source_id'
  evidence      TEXT,                          -- short, human-readable
  reviewed_by   TEXT,
  reviewed_at   TEXT
);
```
2. Fill it from the name matches that the per-player review accepts. Unmatched and ambiguous ids get `lp_player_id NULL, method 'queued'`.
3. If decision D3 says ATP ids enter `player_source_ids`, add rows with source `atp`, league `tennis`, `source_player_key` = the ATP id as text, `player_id` = the LP id. Only for reviewed, non-NULL links. Go through `spine_merge.py` rules; do not write a second merge tool.
4. Do NOT create `players` rows for the 66,912 ATP players. That changes every join in the app. Only with Micah's explicit decision (D3).

**Verify (expected results)**
- `SELECT COUNT(*) FROM tennis_atp_player_xwalk;` returns 66,912 (every ATP player has a row, linked or queued).
- `SELECT method, COUNT(*) FROM tennis_atp_player_xwalk GROUP BY 1;` the 'queued' count equals the unmatched count from measure 6 plus any reviewed-out ids. Report both.
- `SELECT COUNT(*) FROM tennis_atp_player_xwalk x LEFT JOIN players p ON p.id = x.lp_player_id WHERE x.lp_player_id IS NOT NULL AND p.id IS NULL;` returns **0** (no dangling link).
- `SELECT COUNT(*) FROM tennis_atp_player_xwalk WHERE lp_player_id IS NOT NULL AND method='name_exact_reviewed' AND reviewed_by IS NULL;` returns **0**.

**Rollback**: `DROP TABLE tennis_atp_player_xwalk;` and, if D3 applied, `DELETE FROM player_source_ids WHERE source='atp' AND league='tennis';` (only after a count check that it deletes exactly the rows the task inserted, measured from a snapshot).

**Dependency**: after decisions D1 to D3. The read-only measures (1 to 8) can run now.

---

## 4. Other measures for the tasks above (read-only, not yet run)

- Doubles draw_size and key checks: see 3.2 and 3.4.
- Tour and lower counts: see 3.5.
- Rankings after T4: see 3.3.

---

## 5. US Open validation (accuracy check for point and match data)

### 5.1 What the US Open data can and cannot check
- The ATP tables hold MATCH rows only. They have no point rows. "Point accuracy" here means the point-derived counters in the matches table (aces, double faults, serve points, break points). Those are the only fields the US Open point feed can check.
- Not checkable from the US Open feed: rankings (`winner_rank`, `winner_rank_points`, `loser_rank`, `loser_rank_points`), seeds and entries, age, height, hand, IOC, `minutes` (optional, see below). Do not count these as validated in any report.
- The 2026 US Open is NOT in the data (latest 'Us Open' date 20250825). So validation uses 2024 and 2025.

### 5.2 Sources
- **Source A, local, zero network (verified present).** `/root/prediction-market-trading/fixtures/usopen-match1101-zverev-sonego-points.json`: a JSON list of 346 points, 57 fields each (verified: the fields include `Ace`, `DoubleFault`, `SetNo`, `GameNo`, `PointWinner`, `PointServer`, `BreakPoint`, `BreakPointWon`, `BreakPointOpportunity`, `SetWinner`, `MatchWinner`, `P1GamesWon`, `P2GamesWon`, `EpochTimeStart`). Use it to: (a) fix the reducer from points to counters, (b) confirm semantics of `PointServer`, `ServeNumber`, `BreakPointOpportunity`. It is a 2026 match, so it does not validate any 2024/2025 row.
- **Source B, network, UNVERIFIED.** The publisher is usopen.org (IBM SlamTracker feed, per `docs/PROVIDER-AUDIT-LIVE-DATA-2026-09-02.md` section 3). The doc records the 2026 paths as measured: `https://www.usopen.org/en_US/scores/feeds/2026/...`. The 2024 and 2025 archive paths are NOT verified. `backend/ingest_usopen_tennis_logs.py` hard-codes YEAR = 2026 and fetches a completed-match index (`completed_matches/eventDays.json`) and per-match history (`slamtracker/history/<id>C.json`). Its code is the reference for URLs and parsing. Do not copy it into the repo for this check.
- **Source C.** None planned.
- Note: the doc says the 2026 feed is not blocked from this box. usopen.org is not on the AGENTS "hostile" list. Still, no scraping. Only the GET requests below.

### 5.3 Network budget (keep to a few, mark unverified until made)
- Step N1 (probe, 1 request): GET `https://www.usopen.org/en_US/scores/feeds/2025/completed_matches/eventDays.json`. UNVERIFIED. Expected: JSON index of 2025 event days. If 404, record "path not published" as an unresolved result, not as a negative finding.
- Step N2 (probe, 1 request): the same for 2024. UNVERIFIED.
- Step N3 (probe, 1 request): one history file for one 2025 main-draw match, found in N1's index. UNVERIFIED.
- Spacing: at least 5 seconds between requests. One retry at most. No parallel requests.
- Total for the probes: 3 requests. Record each URL, status and byte size in the report.
- FULL SAMPLE (254 history files for 127 matches times 2 years) is NOT authorised by this plan. It needs Micah's approval (decision D5), with spacing of about 2 seconds, roughly 10 minutes. Without it, the check uses Source A plus the 3 probes, and the full pass is marked "not run".

Whether a stored copy of the 2024/2025 feeds exists on this box is unknown. Check first, with zero network: `ls /root/prediction-market-trading/data` and `grep -rl "completed_matches" /root/prediction-market-trading /root/legendarypicks/backend/data 2>/dev/null | head`. Report what is found.

### 5.4 Sample
- Population: the 2024 and 2025 'Us Open' rows with `tourney_id` in ('2024-560','2025-560') and round in ('R128','R64','R32','R16','QF','SF','F'). Expected 127 per year, 254 total.
- Qualifying (round Q1, Q2, Q3): 112 per year. Report separately, not pass or fail (the publisher's qualifying index may be incomplete).
- Query: `SELECT * FROM tennis_atp_matches WHERE tourney_id IN ('2024-560','2025-560') AND round IN ('R128','R64','R32','R16','QF','SF','F');`

### 5.5 Fields compared, and how
| Field in ATP table | US Open source field | Checkable with | Notes |
|---|---|---|---|
| `tourney_id`, `round`, match count | index event days and round labels | Source B index (N1, N2) or stored copy | Coverage: 127 per year present |
| `winner_name`, `loser_name` | index player names | Source B index | Compare surname and given-name initial after accent removal |
| winner and loser orientation | index winner flag | Source B index | Sackmann rows store the winner first by definition; check it |
| `score` (set games, tiebreak, RET, W/O) | per-set games: last point of each `SetNo` gives `P1GamesWon`/`P2GamesWon` | Source A to define the reducer; Source B per match | Normalise tiebreak format first and write the rule down before running |
| `w_ace`, `l_ace` | count of points with `Ace = 1`, grouped by `PointServer` | Source A (reducer test), Source B (values) | Confirm `Ace` semantics on Source A |
| `w_df`, `l_df` | count of points with `DoubleFault = 1`, by `PointServer` | same | same |
| `w_svpt`, `l_svpt` | count of points where the player is `PointServer` | same | Confirm on Source A. Optional if unclear |
| `w_bpFaced`, `w_bpSaved` (and `l_`) | `BreakPointOpportunity` and `BreakPointWon` on the server's points | same | Optional. Scored only if semantics confirmed on Source A |
| `minutes` | duration from first to last `EpochTimeStart` | Source B | Optional, not scored (publisher definition may differ) |
| `w_1stIn`, `w_1stWon`, `w_2ndWon` | not clearly derivable from the feed | none | Do not score |

### 5.6 Pass thresholds (fixed before running)
- Coverage: 127 of 127 main-draw matches present in the ATP table for each year. PASS if both years are 127 of 127.
- Winner and loser names: 127 of 127 per year agree after normalisation. PASS only at 127 of 127. Any miss is a FAIL and blocks T4, T6 and T7 sign-off until the cause is named.
- Score string: at least 125 of 127 per year exact after the written normalisation rule, and zero unexplained mismatches. Each mismatch is listed in the report with its cause.
- Aces, double faults (per player-match, 254 player-matches per year): at least 98 percent exact per field (250 of 254 per field per year). Below that, FAIL for that field.
- Serve points and break points: scored only if the semantics are confirmed on Source A. Same 98 percent threshold.
- Any FAIL in names or coverage stops the other fixes from being signed off. A FAIL in aces, double faults or score is reported with the list of mismatches and a cause for each.
- Sample not run (no authorisation for the full set): the report says "full sample not run" and gives the probe results only. It does not claim a pass.

### 5.7 Reporting
- Per year: counts, pass or fail per field, list of mismatches with the ATP id, the match, the two values and a cause label.
- A row is never called "validated" from Source A alone. Source A validates the reducer, not the ATP rows.

---

## 6. Decisions for Micah (a subagent must not decide these)

- **D1 Licence.** The mirror's licence is CC BY-NC-SA 4.0, and `tennis_atp_source.commercial_use` says NO for all files. Share-alike may apply to derived tables. Decide: can the data be in a product DB at all, or only in internal analysis? Attribution text is in `tennis_atp_source.attribution`.
- **D2 Keep the mirror?** Upstream `JeffSackmann/tennis_atp` returns 404. The source is an unofficial mirror (`AngieXuAU/tennis-point-by-point-archive`). Decide: keep it, pin it to the recorded `git_blob_sha` per file, replace it, or drop the ATP tables.
- **D3 ATP ids in `player_source_ids`, and new `players` rows.** Default recommended in this plan: a crosswalk table (T7) with no new `players` rows. Decide whether ATP ids go into `player_source_ids`, and whether ATP-only players ever get `players` rows.
- **D4 Tour vs lower levels.** Views (default, T6) or separate tables. Decide whether 'D' (Davis Cup) and qualifying rounds Q1 to Q3 are in the tour view. Decide the 1968 cut.
- **D5 Full US Open network check.** Authorise about 254 GET requests to usopen.org at about 2 seconds apart (about 10 minutes), or accept the probe-only result.
- **D6 Rankings conflict policy.** Quarantine (default, T4), or another rule. Also whether the 200 identical duplicates are simply removed.
- **D7 draw_size 'R'.** Confirm the meaning from the README and whether a text column `draw_size_text` is acceptable (T3).
- **D8 Unique index vs PRIMARY KEY.** Default: unique indexes (T5). A PRIMARY KEY needs a full table rebuild.

---

## 7. Task cards for subagents

Each card: inputs, the file or table it may write, the verification command, and what it reports. Every card repeats the rules in section 1.1.

### T0. Baseline and guards (Haiku, mechanical)
- Inputs: none.
- Writes: a scratch file `baseline-20261013.txt` in the scratchpad only.
- Steps: resource gate (section 1.2). Count every tennis_atp table (expected 988,216 / 26,399 / 3,420,595 / 66,912 / 176). Record `PRAGMA quick_check` on the snapshot backup `backups-tennis-20261013/picks.dev.db.pre-tennis-atp-20261013.bak` (read-only) and confirm it has no tennis_atp tables. Record `sqlite3 --version`.
- Verify: the counts equal the expected values.
- Report: the counts, the backup status, the SQLite version, free disk.

### T1. Reproduce and make the loader reproducible (Sonnet)
- Inputs: scratch tennis-scripts folder (read only), section 3.1.
- Writes: `backend/ingest_tennis_atp_sackmann.py`, `backend/test_ingest_tennis_atp_sackmann.py`, `backend/data/tennis_atp_sackmann_manifest.json`. Scratch repro DB only.
- Verify: reproduction in 3.1 (old loader fails at amateur rec 580; new loader completes on an empty scratch DB; counts equal dev). `python3 -m pytest backend/test_ingest_tennis_atp_sackmann.py -q`.
- Report: the two file paths, the test result, the repro counts, the sha256 check result (all 176 match or not), and any mismatch. Stage and commit only the three named files, if the lead asks for a commit.

### T2. US Open validation baseline (Opus)
- Inputs: section 5, Source A (fixture), Source B probes N1 to N3 (only after the zero-network check in 5.3).
- Writes: scratch only.
- Verify: the coverage count (127 per year) and the reducer test on Source A (aces and double faults derived from points must equal the fixture's own counts of `Ace` and `DoubleFault` flags).
- Report: per the 5.7 format, with each probe's URL, status and size, and "UNVERIFIED" for any path not yet hit. State the pass thresholds exactly as in 5.6 and whether each is PASS, FAIL or NOT RUN.

### T3. draw_size split (Sonnet)
- Inputs: section 3.2, T1 output.
- Writes: dev `tennis_atp_matches` and (if needed) `tennis_atp_matches_doubles`, after snapshot. Loader change in the T1 file.
- Verify: the expected results in 3.2.
- Report: before and after counts, snapshot path, the 'R' meaning from the README.

### T4. Rankings duplicate policy (Opus)
- Inputs: section 3.3, decision D6.
- Writes: dev `tennis_atp_rankings` (delete), new `tennis_atp_rankings_conflicts`, after snapshot. Loader change in the T1 file.
- Verify: the expected results in 3.3.
- Report: the three counts, the row arithmetic, the snapshot path, and the source files of the conflicts.

### T5. Unique indexes (Sonnet)
- Inputs: section 3.4. Rankings only after T4.
- Writes: dev indexes only.
- Verify: index names exist; scratch-copy duplicate insert fails with a UNIQUE error.
- Report: each index, the measured duplicate count before creation, the created index names.

### T6. Tour and lower views (Sonnet)
- Inputs: section 3.5, decision D4.
- Writes: dev views only.
- Verify: the partition sum equals 988,216 (expected 1).
- Report: each view's row count, the partition sum, and the level list used.

### T7. Player crosswalk (Opus)
- Inputs: section 3.6, decisions D1 to D3.
- Writes: dev `tennis_atp_player_xwalk` (new), and `player_source_ids` rows only if D3 says so.
- Verify: the four expected results in 3.6.
- Report: linked count, queued count, names reviewed, any ambiguous or disagreeing country, and the snapshot path.

### T8. Final validation (Haiku, mechanical)
- Inputs: all measures in sections 3 and 5.
- Writes: scratch only.
- Verify: every expected result in sections 3 and 5 is re-run and compared. Each is marked PASS, FAIL or NOT RUN.
- Report: a table of finding, measure, expected, observed, status.

---

## 8. Other observations (outside findings 1 and 4 to 8; do not fix in these tasks)
- 895 rows labelled 'US Open' are dated before 1900, all in the amateur file (1,575 pre-1900 rows in total). The amateur file carries levels G and D, so the 'G' count includes amateur-era events. These are not comparable to the open era.
- `tourney_date` is the tournament start date, not the match date. Check this before comparing to match-day feeds.
- The file backup predates the load (section 1.3). It cannot roll back any fix.
- The `ingest_runs` table exists (16,838 rows) and has no tennis row. Finding 1 is confirmed.
- Box: free RAM at check was 146 to 214 MB with swap fully used. The gate in 1.2 matters.
