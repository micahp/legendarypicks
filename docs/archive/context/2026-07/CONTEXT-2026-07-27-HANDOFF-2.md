# LP handoff — 2026-07-27 pt.2 (supersedes CONTEXT-2026-07-27-HANDOFF.md)

Read §1 first. It invalidates a week of work in the right direction.

---

## 1. THE FINDING: we are recomputing data nflverse already publishes

`ingest_nfl_pbp_logs.py` derives per-game NFL stats from 372-column play-by-play.
Its docstring justified that with *"nflverse's pre-built weekly summary 404s for 2025."*
**That is false.** The release was renamed `player_stats` → `stats_player`:

```
https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.parquet
```

200 for 2024 and 2025. **145 columns.** Every field our rollup computes is in it —
including `passing_epa` and `passing_cpoe`, which I hand-derived and argued with Codex
about. Snap counts (`snap_counts_2025.parquet`, verified 200) and NGS already come from
their own ingests.

**All eight defects found this week were bugs in a reimplementation of arithmetic
nflverse does correctly.** Micah spotted the frame error in one question after two
agents spent a week inside it. I had the artifact open for hours and used it as an
answer key instead of noticing it was the answer.

### Written, dry-run clean, NOT wired in, NOT committed

`backend/ingest_nfl_weekly_stats.py` — ~250 lines, a column mapping plus one derived
value (`dropbacks = attempts + sacks_suffered`, already verified equal). Prints the
artifact sha256 every run (nflverse rewrites files in place). Preserves snap/NGS keys.
Emits the same row set as the rollup *on purpose*, so the swap is diffable;
`--all-positions` opens defensive + kicking lines.

```
venv/bin/python ingest_nfl_weekly_stats.py --year 2025 --dry-run --cache-dir <dir>
```

### Diff vs current dev data (5,373 shared rows)

| field | rows differing | cause |
|---|---|---|
| `att` | 512 | sacks + 2pt as attempts |
| `fpts` / `fpts_ppr` | 310 | fumbles, 2pt, return TDs |
| `dropbacks` | 660 absent | field postdates the data |
| `targets` | 84 | 2pt targets |
| `rec_yds` / `rush_yds` | 16 / 1 | laterals |
| `pass_epa` | 6 | `no_play` / `field_goal` |
| `carries` | 31 | ours always +1 (2pt rushes) |

**Caveat: this diffs PRE-fix dev data, so it overstates what corrected code still gets
wrong.** `4075c2b` already fixes att/targets/laterals/EPA/dropbacks/carries. What the
fixed pbp code still gets wrong is below.

### Two gaps the swap closes that no fix to the pbp path would

1. **THE ENTIRE 2025 POSTSEASON IS MISSING.** Weeks 19–22, **258 player-games, zero
   rows.** Rodgers wk19, Stafford's wk19/20/21 run, all of it. The pbp ingest has never
   produced playoff data. The artifact has it.
2. **fpts is still wrong in the fixed code** — 312 rows. The hand-rolled scorer at
   `ingest_nfl_pbp_logs.py:261` omits fumbles lost (184 rows), 2pt conversions (83),
   special-teams TDs (15). Verified 184/184, 82/83, 15/15 against the artifact.
   **Codex's earlier review named all three exactly and I did not act on it.**

4 rows exist only in old data (Saubert, Gilliam, Hill, Drummond — `targets:1, rec:0,
fpts:0`): the 2pt phantom targets the eligibility fix strips. Snap keys survive either way.

### Recommendation

Do NOT hand-patch three more scoring components. Swap to the copy, keep
`ingest_nfl_pbp_logs.py` for raw play retention only (`nfl_pbp`, 46k plays × 50 cols is
genuinely additive). Verification becomes tautological — you cannot disagree with your
own source.

---

## 2. Also published, also missing: the 2026 schedule

`prop_games` / `team_game_results` / `game_context` have **zero 2026 rows.** The full
272-game schedule is public and free:

```
https://github.com/nflverse/nfldata/raw/master/data/games.csv   # 1999-2026, 2.1MB
```

Three for three today — fantasy points, postseason, schedule — all published, all either
recomputed badly or absent.

## 3. Real dates (I had asserted these wrong; Codex agreed with the wrong ones)

| | asserted | actual |
|---|---|---|
| Week 1 opener | "~Sept 10" | **2026-09-09 Wed** |
| runway | "5 weeks" | **44 days** |
| draft window | "mid-late Aug" | **late Aug → Sept 8**, peak Labor Day (Sept 5–7) |
| Codex ship-by | "Aug 10–15" | 14–19 days out — conservative by ~2 weeks |

Week 1 = Wed Sept 9 → Mon Sept 14. Fantasy final Week 17 ends Jan 4 2027. REG weeks 1–18.
**Still assumption:** actual draft timing. `nfl_adp` is a single snapshot, not a series.
Snapshot it daily and it becomes measurable in ~2 weeks.

---

## 4. NFL league page — where the product conversation landed

Current NFL tabs: `camp` (NflCampHero + NflOffseasonMovers + NflDraftRoom), standings,
stats, schedule, predict. Data on hand: `nfl_adp` 9,611 rows season 2026, 2024+2025 game
logs, `nfl_transactions` 754, `nfl_pbp` 46,452.

Top-200 2026 ADP → 2025 logs: **QB 22/22, TE 18/19, RB 43/46, WR 55/59 = 94.5% skill;
LB/S/DE/CB/PK ~0%** (rookies, IDP, kickers — not ID failures). `--all-positions` on the
new ingest fixes the 0%.

**Codex consulted (2m 09s, it is under 10% of weekly budget — spend carefully):**
- **A. Calendar inversion correct** as delivery order, not strategy. Don't burn all the
  runway on draft; pivot the same components into Week 1 sit/start.
- **B. I was wrong that distribution = differentiation.** Floor/ceiling/boom-bust is
  standard fantasy vocabulary; ESPN player profiles already use that framing. It only
  differentiates with ADP/value overlay, positional replacement context, position-specific
  thresholds, and games-missed.
- **C.** Declare a scoring contract on the card. Scope QB/RB/WR/TE. Rookies = "no NFL
  sample," never zero. p90 on ≤17 games is 1–2 games — show sample size.
- **D. The real catch: a historical distribution is not `prob_over()`.** A missed game has
  no log row, so the distribution is conditional on playing — **injury-prone players look
  safer than they are.** Split performance-given-playing / availability / current role.
- Its reframe: ship as a **"Historical Range & Reliability" board**, explicitly not a
  projection.

---

## 5. DONE this session

- **History rewrite applied + force-pushed + verified.** `git log --remotes --tags
  --grep='Claude-Session'` = **0**; per-branch sweep of every `refs/remotes/origin/*`
  clean. `origin/main` and `origin/mvp-backend-scaffolding` verified **0** — the old
  open question is closed. Trees byte-identical (584 commits, empty diff). All 4 GitHub
  Releases survived. NFL commits pushed, new SHAs `4075c2b` / `01f6c92` / `e48de53`.
- **`:8096` CPU root-caused.** 67% was uvicorn's `--reload` supervisor, not the app —
  `StatReload` stat()s 5,861 `.py` files 4×/sec, 5,733 of them `venv/`. Installed
  `watchfiles==0.24.0` with `--no-deps` (so pip couldn't touch anyio and bounce the live
  server; verified child PID unchanged). **Restart script ready, NOT run:**
  `scratchpad/restart-8096.sh`. `--reload-exclude` **must be an absolute path** — proved
  empirically that `venv/*` and relative `venv` silently exclude nothing.

## 6. Open work, ordered

1. **Swap to `ingest_nfl_weekly_stats.py`.** Commit it, add tests, wire it in, retire the
   rollup half of the pbp ingest. This replaces the old §4 "rerun the corrected
   derivation" plan — importing the reference is strictly less risky.
2. Ingest the 2026 schedule from `games.csv`.
3. NFL 2024 destructive write in `ingest_nfl_logs.py` (5,329 snap rows + 1,253 NGS rows
   wiped on re-run, same shape as `866dbf1`) — still live.
4. Then the draft board, framed as Codex describes.
5. Restart `:8096` when convenient.

## 7. State

- `dev` = `e48de53`, **in sync with origin**. Suite last run: 241 passed, 4 pre-existing
  failures (`test_league_stats_contract`, 3× `test_nfl_offseason_api`) — unrelated.
- Untracked: `backend/ingest_nfl_weekly_stats.py`.
- Codex's 3 WIP files still uncommitted (`espn_client.py`, `ingest_ufc_fight_stats.py`,
  `ingest_wc_logs.py`) — **it wants to land these itself.**
- Prod: v0.6.7, serving wrong NFL numbers and no postseason.
- Artifacts cached in `scratchpad/`: `stats_player_week_2025.parquet`
  (sha256 `afc45559f6385a3f253887f37efcb1124006db799c91a58d8c7151429136f0cc`),
  `stats_player_week_2024.parquet`, `snap_counts_2025.parquet`, `games.csv`.

## 8. The lesson worth keeping

Both agents optimized inside an inherited premise and neither re-checked it. The
correctness work was real but aimed at a component that should not exist. **Before fixing
a derivation, check whether the value is published.**
