# HANDOFF 2026-07-26 (pt.5) — v0.6.7 SHIPPED TO PROD; pbp retained; integrity crossroads opened

**Read first.** Supersedes pt.4 entirely for the NFL usage work — that branch is merged, released,
deployed and verified. 07-25 §1 product direction still current.

---

## 0. THE NEAR MISS — read before running any ingest

**Fixed and committed as `866dbf1`.** Recorded here because the script looked idempotent and was not,
and because the same shape almost certainly exists in other ingests.

The bug (pre-existing, NOT introduced this session): the pbp ingest wrote its rollup
with a bare `INSERT OR REPLACE` carrying only its own `STAT_FIELDS`. Every other key in the row was
merged in *afterwards* by different ingests — `ingest_nfl_snap_counts` writes `off_snaps`/`off_pct`/
`st_*`, `ingest_nfl_ngs_receiving` writes `separation`/`cushion`/`adot`/`air_yds_share`/
`yac_above_exp`. Re-running the pbp ingest **deleted all of them.** Measured on a dev copy:

```
BEFORE  2025: off_pct=5360  separation=1213
AFTER   2025: off_pct=0     separation=0
```

Those are the exact keys the v0.6.7 usage card runs on, and the exact 10,689 rows migrated to prod
that afternoon. **Running the old ingest against prod would have taken the live feature down.**
Codex also found `INSERT OR REPLACE` reassigns the row `id` (REPLACE = delete + insert). Nothing
references `player_game_logs.id` today — no FKs, all joins go through `player_id` — so that half is
latent, not live, but it means the table has no stable row identity, which blocks per-row provenance
and correction history later.

Fix (`866dbf1`): the ingest declares the keys it **owns** (`STAT_FIELDS` + the two `fpts`) and
carries every other key forward; `ON CONFLICT DO UPDATE` instead of REPLACE so the row id survives;
`player_id`/`game_date`/`home_away` are COALESCEd so a later run cannot null out an earlier one's
value. It prints the preserved-key count and names, so a future run proves it deleted nothing.

Verified on a real dev copy: **38,223 keys preserved across 5,360 rows**, `off_pct` 5360→5360,
`separation` 1213→1213, **min/max row id identical before and after**. Suite 229 passed / 4 baseline.

**The generalizable lesson:** an ingest that writes a partial stats blob with `INSERT OR REPLACE`
destroys every other ingest's contribution to that row. `ingest_nfl_snap_counts`,
`ingest_nfl_ngs_receiving`, the MLB and UFC paths — **audit each one for the same pattern.** This was
found only because retention work happened to require re-running the ingest.

## 1. In flight — Codex, `tmux codex:0.0`

**Mid-diagnosis, read-only, no writes authorized.** Question posed: 2024 receiving lines derived
from the pbp parquet disagree with the weekly-summary rows already in dev on **20 player-games**,
and the weekly summary is consistently higher.

```
rec_yds: same=4239  DIFFER=20  pbp-only=4
  00-0033526 wk5   24 vs 9        00-0033576 wk3   41 vs 24
  00-0033526 wk13  15 vs 5        00-0036158 wk9   20 vs 10
  00-0030564 wk7   -2 vs 6
```

**Why this matters more than 2024:** if the weekly summary is right, the pbp aggregation has a real
bug — and the pbp path is the **sole writer of the entire 2025 season**, where there is no second
source to catch it.

**PROVISIONAL ANSWER (Codex, still verifying when the session ended):** the cause is **lateral
attribution**. nflverse pbp carries `lateral_receiver_player_id` and `lateral_receiving_yards`, and
the aggregation in `ingest_nfl_pbp_logs.py` ignores both — it groups on `receiver_player_id` and sums
`receiving_yards` only. Codex traced the first three cases (including the negative Hopkins one) and
they converge on this; **not** penalties and **not** two-point conversions. It was cross-checking
official gamebooks and quantifying whether all 20 share the signature.

**If that holds, the implication is the important part: the weekly summary is RIGHT, the pbp
aggregation UNDER-COUNTS, and 2025 — currently served from prod — has the same flaw with no second
source to catch it.** The fix is to include lateral columns in the passing/rushing/receiving
aggregations. **Verify Codex's conclusion before acting on it; it was mid-verification.**

Also still uncommitted and owned by Codex: `ingest_ufc_fight_stats.py` (+1,236 lines),
`espn_client.py`, `ingest_wc_logs.py`. **Codex explicitly said it wants to land these itself.**
Prod's UFC path depends on that dirty working tree.

## 2. Shipped — prod is on v0.6.7, verified live

`dev` = `328e611`, 0 ahead / 0 behind origin. Tags `v0.6.6` and `v0.6.7` pushed.

| what | detail |
|---|---|
| **v0.6.7 live** | `legendarypicks.xyz` 200; McBride wk18 → `snap_share 0.95, tgt_share 0.286, wopr 0.561, sep 4.05` |
| **usage endpoint** | ~180ms → **~13ms**. It was a missing index, **not** a cache — the team-sum queries scanned every NFL row twice per request. A cache would have hidden the scan and had a poor per-player hit rate. |
| **prod DB migrated** | 10,689 rows enriched with `off_pct`/`off_snaps`/Next Gen. Prod had the rows but none of these keys — v0.6.7 would have returned 200 and rendered **dashes**. Backup `picks.db.bak-premigrate-nflstats-20260726-162530`. |
| **v0.6.6** | retagged properly on `906f2fc` (all 3 esports commits) with real changelog. Was a hand-made tag, no bump, no notes. |
| **`.dockerignore`** | build context **3.0GB → ~50MB**. Also stopped `.env.local` — whose own first line says *"never reaches prod"* — from shipping in every prod image pointing at the dev backend on `:8095`. Gitignored ≠ excluded from a build context. |
| **WC descheduled** | removed from `run_history_refresh.DEFAULT_JOBS`, moved to `DEFERRED` with a reason. Confirmed in prod: timer ran 17:19:41, **2 jobs, 0 failed**. `AGENTS.md` §0 now states WC is dormant until 2030 and NFL is the calendar. |
| **untracked prod code** | 11 scripts + 4 systemd units were running in prod **untracked**. Committed (`c306f36`), units byte-identical to `/etc/systemd/system`. Runbook committed too (`320d36f`). |
| **backup safety** | `history_refresh_common.backup_database` was `shutil.copy2` on a live DB. Now the SQLite **online backup API** (`62e6185`, Codex). I verified it against a real 136MB copy under 152 concurrent writes: 0 errors, integrity ok. |

## 3. Play-by-play — retained; the handoff's blocker was wrong

pt.4 §5 carried this as "NOT YET SIZED … ~50k plays × ~370 cols vs a 5.9GB box with ~1.5GB free,"
implying it might not fit. **It fits trivially.**

- 48,771 plays × **all 372 columns = 28MB uncompressed**. The parquet is 20MB and downloads in 1.1s.
- Retained subset: **34 columns, 15.7MB/season in SQLite with 4 indexes.** Dev grew 130 → 146MB.
- **Peak RSS is unchanged (~425MB).** The ingest *already* built a 388MB frame and threw the plays
  away. Retention costs disk and essentially no memory — the expensive part already happened.
- Dev now holds **46,452 plays for 2025**. Player lookups are **3ms**.
- Only 34 cols, not 372, deliberately: `desc` alone is 4.7MB/season, and 372 undocumented columns is
  a schema nobody can reason about later.

**Also fixed:** `game_date`/`home_away` were passed as literal `None` while the frame carried both —
NULL on **100% of NFL rows**. Now populated on all 5,377 pbp-sourced 2025 rows. Tests added to an
ingest that had **none** while being the sole writer of the 2025 season; all 4 mutations caught.

**Big finding:** the 2024/2025 schema split is **NOT in the source.** Both seasons' parquet are
identical — 372 columns, all 34 retained columns present in both. The divergence was created
entirely by the two different ingest *paths*. That makes "recompute 2024 through the 2025 path" a
real option instead of a hand-written 12-key rename — **but see §1, it is not a free re-keying.**

**NOT done:** raw artifact retention. This is the curated query layer, not an archive. nflverse
**rewrites historical files in place** — the 2020 parquet was re-uploaded 2025-04-30, five years
after that season. So stored rollups can silently drift from a fresh download.

## 4. The integrity crossroads — Micah's framing, and where it landed

Micah reframed the pbp question as *"how much data integrity do we want."* Codex's thesis (worth
re-reading in full in its transcript):

> **The core defect is the absence of an explicit row contract** — who (canonical identity), what
> observation (player + event + stat group/role), what fields mean, and why it is trustworthy
> (source snapshot + transformation version). One JSON blob carries all four implicitly.

> **"Retain PBP now, but the first-order fix is a canonical, versioned fact contract. Without that,
> source retention merely gives you excellent evidence of inconsistent outputs."**

- **51 MLB batting/pitching collisions = grain** ("what row is this?"). The natural key
  `UNIQUE(league, source_player_key, season, game_no)` has no role dimension.
- **133 MLB split identity owners = identity spine** ("who is this?"). **A role dimension would not
  fix this** — needs a source-ID crosswalk.
- On the normalizer: **normalize at ingest and rewrite history. Do NOT make a reader-side normalizer
  the architecture** — it leaves storage internally contradictory, gets bypassed by raw SQL, exports
  and **B2B customers**, and turns every consumer into a semantic fork. *(This reverses advice given
  earlier in the session; Codex is right, especially for a dataset intended to be sold.)*
- On `def_snaps` (42 non-zero of 10,689): **do not rewrite non-zero to zero. "Zero is a claim."**
  Flag the metric unavailable until reconciled.

**Why normalization matters, demonstrated rather than argued** — same question, two spellings:

```
SUM(...'$.rec_yds')          -> top: Jaxon Smith-Njigba 2025, 1793   (only 2025 players)
SUM(...'$.receiving_yards')  -> top: Ja'Marr Chase      2024, 1708   (only 2024 players)
```

Chase's 1,708 beats three of the five "top" seasons in the first list and is simply absent. **Neither
query errors. Both look correct.** The app is fine today because its readers COALESCE both spellings
— it stops being fine the moment anything queries storage directly, which is exactly the Phase 2
B2B plan.

## 5. Mistakes made this session — recorded so they are not repeated

1. **Said prod was WAL. It is `journal_mode=delete`** (dev is the WAL one). Codex caught it — and
   `/root/TASK-prod-data-gap.md` guardrail 2 *said so in writing* and had not been read first.
   **Read that spec before touching prod.**
2. **Called the WC ingest "outright broken"** off a TypeError that was actually caused by our own
   `git stash` hiding a dependency. It passes 7/7. Verify before declaring.
3. **Said the UFC fight-stats timer fires at 17:21.** It is `disabled`/`inactive`, superseded by
   `legendarypicks-history-prod.timer`. True at 15:01, stale after Codex consolidated at 15:34, and
   repeated without rechecking.
4. **The NFL migration used the blind `UPDATE stats = dev.stats` that Micah's own spec forbids.**
   Verified per-row across all 10,717 rows that it dropped 0 keys and changed 0 values, and Codex
   independently confirmed every blob now matches dev — so no damage. But it was safe *by
   verification*, not *by construction*. **Key-union is the correct default** for additive
   enrichment. Codex's constrained modes: add-missing-abort-on-collision; rename-under-explicit-
   equality; correct-with-expected-old-value; replace-only-on-matching-prior-hash-and-source-version.
5. Committed two logical slices in one commit (staging left over from a blocked commit). Caught and
   split before pushing. One commit per slice.

## 6. Live processes

| what | state |
| --- | --- |
| prod stack | `legendarypicks-frontend-1` / `-backend-1`, up, `:3100` / `:8100` behind nginx |
| `:3096` / `:8096` | dev, **externally managed — do not restart** |
| `:8095`, `:3095` | still up |
| worktree `:8098` / `:3099` / cloudflared | **torn down this session** (Micah: not needed after merge) |
| `/root/lp-nfl-usage` | worktree still exists, branch merged |

Box healthy: ~2.0GB available, load ~1.7. **Load the `resource-check` skill before any batch job** —
it is a real project skill at `legendarypicks/.claude/skills/`.

## 7. Still open

**Immediate:** Codex's UFC/espn/wc WIP (§1) · Codex's 20-row diagnosis (§1) · run pbp retention
against **prod** (dev only so far) · **audit the other ingests for the §0 destructive-write pattern**.

**The integrity program (§4), in Codex's recommended order:** define the NFL v1 contract → stop
creating bad history at the ingest boundary → **raw source retention** → repair 2024–25 with
constrained migrations → define the real prop-outcome grain (event/player/market, book, line, side,
capture time, settlement, result, rule version, correction history) → dual-run and reconcile before
selling → MLB identity/role grain **last**, so a cross-league redesign does not eat the NFL window.

*One dissent worth carrying:* raw source retention is hours of work and near-zero risk, while
contract definition is weeks. Every week without retention is another week of games permanently
unfalsifiable, and nflverse rewrites files. **Consider retention before contract definition.**

**Carried from pt.4, still open:** the hub / option B (week matrix, default Snap%) · no NFL pick
surface · GitHub Action for the version guard · prod visitor figure · `/strength` gate ·
`streams.py` decapi wobble · Underdog fighter identity gap.

**New, minor:** the test suite is not hermetic — a test makes a live ESPN request and fails on
blocked DNS (Codex hit this). `/api/player/{id}/stats` reports NFL players as `"league":"mlb"` (it is
the Statcast endpoint; pre-existing, not from this session).
