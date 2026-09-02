# HANDOFF 2026-07-26 (pt.4) — usage card rebuilt + NFL data inventory; branch pushed, NOT merged

**Read first.** Supersedes pt.3 for the NFL player page. Pt.2 §4 (prod v0.6.5 / GA4 / tags) still holds.
07-25 §1 product direction still current.

---

## 1. In flight — Codex

> **SUPERSEDED as of 14:30.** This section said "nothing was written to production." **That is no
> longer true** — Micah approved, and Codex wrote. Corrected below; do not act on the old wording.

`tmux codex:0.0`, spec `/root/TASK-prod-data-gap.md`.

- The 0-of-26 resolution failure was a **sandbox DNS artifact**, not a real dead end. With network
  enabled the dry run found 80 candidates. ESPN's full athlete-history path then 403'd (consistent
  with the datacenter-IP bot wall) and it **aborted without writing**; it fell back to the bounded
  current-card path, which worked.
- **Prod was written and independently verified by me** at 14:30: `player_game_logs` league='ufc'
  → **102 rows, 28 fighters, 2021-01-20 → 2026-07-25**, matching Codex's report exactly. Two
  pre-write backups exist (`picks.db.bak-premigrate-ufc-20260726-134719` and
  `-ufc-current-card-20260726-135243`), both `integrity_check=ok`. Disk is fine (209G free).
- Micah then approved a **systemd timer** ("add it") for the current-card ingest — units drafted at
  `ops/systemd/legendarypicks-ufc-fight-stats-prod.{service,timer}` (4×/day, prod `picks.db`),
  untracked and **not yet installed** into `/etc/systemd/system` as of 14:30.
- Not verified by me: the MLB R/RBI merge. A `picks.db.bak-premigrate-mlb-20260726-140903` backup
  exists, but prod rows with an `rbi` key read **0** — either it did not land or it writes under a
  different key. **Check before assuming that workstream is done.**

## 2. Shipped this session — branch `feat/nfl-usage-renderer` @ `15a9b2b`, PUSHED

`cc78729..15a9b2b`, fast-forward, remote confirmed. 10 ahead / 6 behind `dev`, **merges clean (0
conflicts)**. Worktree `/root/lp-nfl-usage`.

| commit | what |
|---|---|
| `e0caa95` | band the usage table + rushing usage (carries/carry_share); **per-column** pruning, not per-band |
| `632b9e3` | expose 7 ingested-but-unrendered keys on `/api/nfl/usage` + derived `epa_per_db` |
| `2f618e9` | **the design pass** — role-driven card, 4 positional tiles, Next Gen band, 2 sparkline fixes |
| `a08c39b` | `docs/NFL-DATA-INVENTORY.md` |
| `15a9b2b` | `docs/NFL-CHART-CONTENT-RESEARCH.md` |

Usage card now: role line ("Every-down receiver") → 4 tiles → banded table. **QB** Snap%/Att-g/CPOE/
EPA-per-dropback · **RB** Snap%/Car%/Tgt%/PPR, Rushing sorts before Receiving · **WR/TE** Snap%/Tgt%/
WOPR/Sep + full Next Gen band. Share columns carry a magnitude bar.

Two sparkline bugs fixed: shares were forced onto a 0-100% axis (21%→37% became 8 identical stubs);
and CPOE −8.5 rendered as a short bar growing *upward*. Diverging metrics now hang below a zero line.

Verified at 1280px on Elliott(RB) / Shaheed(WR) / McBride(TE) / Allen(QB) — screenshots
`/root/lp-verify/slice4-*.png`. **2024 legacy path verified**: `pass_att` resolves via old `attempts`,
`cpoe`/`epa_per_db` null and pruned.

## 3. ~~DO NOT MERGE~~ — BLOCKERS CLEARED, branch is mergeable

Both blockers and all three lower-severity items are closed. Branch is now **0 behind / 17 ahead** of
`dev` (`origin/dev` merged in at `283be92`) — a **strict fast-forward**. Merge is Micah's call; there
is nothing technical left holding it.

| was | now |
|---|---|
| Season Stats zero wall on the default tab | `eb03fa5` — `_nfl_stats_for_position` in `_core.py` picks blocks off position, prunes values second. Rendered zero/None tiles across all 1,217 NFL rows: **7,255 → 408**, and no player loses their section. McBride's Overview is 5 live tiles, was 12 with 7 dead |
| Zero tests on post-slice-4 fields | `1220e89` (+8 usage) and `357390b` (+8 season stats). Every assertion checked against a **mutated implementation**, not just a passing one — 10 mutations, all caught |
| Never checked at mobile width | `e4460b3` — verified at 390px; week column now pinned so a scrolled 14-col table keeps row identity. Body does not scroll horizontally |
| `usage_trend_viewed` unwired | `0c73423` — fires on entry into the Usage tab. Verified in-browser with a gtag stand-in: one event per entry, none on re-render |

Also fixed along the way (`7578d17`): **LP_DB_PATH leaked between test suites**, so the 3 real-DB
tests failed in a whole-suite run but passed file-by-file. This was previously carried as a "known
env artifact" — it meant the full suite could not be used as a gate. Now `conftest.py` restores the
variable and the real-DB tests resolve their own path.

**Full suite: 160 passed, 4 failed.** All 4 predate this branch (identical failures at `15a9b2b`) and
are untouched: 3 × `test_nfl_offseason_api` (`no such table: nfl_adp` — fixture gap) and 1 ×
`test_league_stats_contract` (an MLB comparison assertion). Worth a separate pass on `dev`.

One deliberate non-change: an RB's PPR can move on a game with no usage-table explanation (Elliott
wk16, 6.1 PPR on 1 carry — a rushing TD). Box-score scoring stays off the usage table by choice; the
Game Log tab carries it.

## 4. The data inventory — the findings that change decisions

Full: `docs/NFL-DATA-INVENTORY.md`. Artifact (same numbers, scannable):
<https://claude.ai/code/artifact/efed2820-383c-4a8a-bd25-ed063544cb74>

- **10,717 NFL rows, 776 players, 28 keys, seasons 2024+2025 only.**
- **The two seasons are different schemas.** 2024 dense+legacy-keyed (all 14 box keys present,
  zero-filled); 2025 sparse+canonical (key exists only when the phase applies). **Presence means
  nothing in 2024 and everything in 2025.** 12 renames. `pass_epa`/`cpoe`/`air_yds` are 2025-only.
  Has already caused 2 real bugs. Needs ONE normalizer every reader goes through.
- **Next Gen receiving is a WR/TE feed — 0 RBs, 0 QBs.** An RB's blank aDOT/WOPR is the source, not
  missing coverage. This is why the card picks columns off position first. Even within WR it reaches
  151 of 226.
- `def_snaps`/`def_pct` are noise (17 non-zero rows of 5,360) — should come out of the ingest.
- **`nfl_adp`** (9,611 rows, 2026 only, refreshed daily) is the only table that knows what the market
  thinks of a player, and the player page never mentions it. Percent-owned beside snap share is the
  most direct "should I make this pick" expression in the data.

## 5. The play-by-play finding — highest-leverage ingest change available

`ingest_nfl_pbp_logs.py` calls `import_pbp_data([year])` — **the full nflverse play-by-play, every
play** — aggregates to per-game lines, and **persists only the rollup. No play table exists.**

Micah's angle: these metrics are exactly what nflfastR chart-Twitter posts about. Survey +
feasibility split recorded in `docs/NFL-CHART-CONTENT-RESEARCH.md` (survey marked **unverified** —
this box can't reach X; the feasibility half IS verified off code+DB).

- **Buildable today** (per-game grain): CPOE-vs-EPA scatter, weekly efficiency lines, separation/
  cushion distributions, share trends, leaderboards.
- **Needs plays retained** (per-play): WPA swings, series outcomes, air-yards pass charts, EPA by run
  gap, any down/distance split. **4 of the 6 concrete examples are per-play.**
- **NOT YET SIZED.** ~50k plays × ~370 cols vs a 5.9GB box with ~1.5GB free. Column selection + volume
  must be measured BEFORE writing anything.

**Bonus bug:** `game_date`/`home_away` NULL on all 10,717 NFL rows is **not** a source limit — the pbp
ingest passes literal `None` for both while the frame carries them. Two values in one INSERT.

## 6. Live processes

| what | id | notes |
| --- | --- | --- |
| worktree backend `:8098` | pid varies | **no `--reload`** — restart after every Python edit. Restarted 3x this session |
| worktree `next dev` `:3099` | pid 1187595 | hot-reloads |
| cloudflared | pid 1193442 | https://crossword-expansys-transition-victorian.trycloudflare.com → `:3099` |

Restart `:8098` (use `setsid`, and **never** `pkill -f "uvicorn sports_service"` — the pattern matches
the shell running it and kills your own command, cost a cycle this session):
```
cd /root/lp-nfl-usage/backend && LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  LP_ESPORTS_WARMER_INTERVAL_S=0 setsid nohup /root/legendarypicks/backend/venv/bin/python \
  venv/bin/uvicorn sports_service:app --port 8098 > /tmp/uvicorn8098.log 2>&1 < /dev/null &
```
Tests need `LP_DB_PATH=…picks.dev.db` set or 3 real-DB tests fail with "Player not found" (env
artifact, not a regression).

**Leave alone:** `:3096`/`:8096` = `/root/legendarypicks` @ `dev`, externally managed. `:3095` orphan.

## 7. Still open (unchanged)

Merge-to-`dev` decision · the hub / option B (week matrix, default Snap%) · no NFL pick surface ·
GitHub Action for the version guard · prod visitor figure · `/strength` gate · `streams.py` decapi
wobble · Underdog fighter identity gap · prod data gap (§1).
