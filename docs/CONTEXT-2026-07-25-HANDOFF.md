# HANDOFF 2026-07-25 — LP product direction pivot + NFL usage data/renderer

**Read this first.** Supersedes `CONTEXT-2026-07-24-HANDOFF.md` for product direction and NFL work.
The 07-24 doc's open items (resource-check skill, MLB backfill, UFC fight_time) are all **done** —
see "Closed from 07-24" at the bottom.

---

## 1. The strategic thread — this is the important part

A long direction conversation, driven by Micah, landed on several conclusions. These are decisions,
not options.

**Rejected:** the trading/market-making path as the main value prop. His words: *"i actually don't
want this to be our main value prop/way we make money. it's hard to do and it's not even the most
fun way we could be making money."* Do not propose player-shares, AMM, or token mechanics. This is
now evidence-backed, not just preference — see §2.

**Rejected:** an "accountable judgment engine" (grade what the coach *should* have done). I proposed
it, Codex killed it with evidence, and the kill is correct: `scoring_plays` has **0 NFL rows**, and
`ingest_nfl_pbp_logs.py` downloads nflverse play-by-play then **discards** down, distance, yard
line, timeouts, and win probability. LP has a *settlement* engine ("did the prop hit"), not a
*judgment* engine. Full memo: `/root/CODEX-RESPONSE-product-direction-2026-07-25.md` (299 lines,
with a verification ledger — worth reading).

**Rejected:** Codex's counter-proposal, a daily 3x3 NFL trivia grid ("Receipt Grid"). Micah:
*"directionally cool but not what i'm going to push."* My objection stands too: it is functionally
Immaculate Grid, and it doesn't use LP's differentiated data.

**Accepted direction:** the app is a **sports analytics tool whose data points are the product AND
the distribution**. Every high-engagement sports content format is a query against a game-log
database, so the content engine and the product are the same artifact. Posting becomes a byproduct
of building rather than a second job — which is what makes Micah's "distribution solves itself by
posting consistently" plan actually sustainable.

His current elevator pitch is *"it's a sports analytics tool and you can watch esports"* — two
products joined by "and". He says he is **confident in the brand, not the product direction**. The
reframe that landed: **the brand is the spec.** The app is named *Legendary Picks* — "Picks" is the
product, "Legendary" is the earned record. Sport.Fun took a year to arrive at "Picks. But you own
it."; LP was named that on day one. Analytics is the *input* that grades the pick, not the product.
Esports is the **venue** (the only place LP can legally embed live video — see
`docs/EMBEDDABLE-STREAMS-VERIFICATION-2026-07-24.md`), so the loop is pick → watch → graded.

**Accepted near-term focus:** fantasy football, because it is the only thing with a calendar forcing
function. NFL kickoff ~2026-09-10 (verify), drafts cluster late Aug–early Sept. Two windows: draft
tools now, then weekly in-season decisions. Existing scaffolding: `NflDraftRoom`, `NflScheduleTab`,
`NflOffseasonMovers`, `NflCampHero`, `useNflTransactions`, plus `SPEC-nfl-product-direction.md`.

**Acquisition thesis (Micah raised it, it is real):** what gets acquired is not users but the
**prop-outcome ledger**, because it is time-cumulative and cannot be bought retroactively — nobody
can buy 2026's "what was the line and did it hit" after the fact. That is the only clock-based moat
LP has. Implication: building a consumer game that overlaps Sport.Fun makes LP a competitor to be
outspent; deepening the ledger makes it an asset. Buyer list is broader than Sport.Fun (Underdog,
PrizePicks, Sleeper, Sportradar, Genius). Caveat: Sport.Fun's token/marketcap has "taken a
beating," so being paid in it is not a payday.

**Still unverified, treat as hypothesis:** "smarter fans is a big thing nowadays." All supporting
evidence is competitors' *supply* decisions, not demand. Codex's better hook: **"prove you know
ball,"** not "get smarter."

**Instrumentation is the hard blocker with a deadline.** No analytics library is installed anywhere;
prod showed 0–19 unique app-route visitors/day. The NFL season is the only large traffic event on
the calendar — arriving uninstrumented spends the one annual spike and learns nothing. Sport.Fun's
entire strategy rests on a measured activation threshold ("first trade + 5–8 tournaments"); LP
cannot form such a sentence. This is an afternoon of work with a September deadline.

## 2. Sport.Fun corpus extended (pushed)

`docs/SPORTFUN-ARTICLE-CORPUS-NARRATIVE-2026-07-13.md` gained **Act VII** + a dated addendum
(commit `7fd3dbd`, pushed). Source article archived at
`/root/ai-research/data/adamfdf_articles/season-2-is-coming-a-bigger-better-arena-not-to-cry-in-20260725.md`,
INDEX 25 → 26 (ai-research commit `72430a4`, pushed to main).

Headlines from Adam's Season 2 update: identity declared settled ("Picks. But you own it."); **market
health is his #1 problem, still open after a year and five successive mechanisms**, now delegated to
a shadow-mode agent ("Motty") that does not yet hold the buyback wallet; revenue was always **packs,
not market fees** ($7m from 15k wallets, Oct 2025), and Season 2 adds a **Season Pass** whose lead
feature is a *"best in class AI Assistant"* — i.e. his scarcity is LP's abundance. Scouting deferred
to Q4 explicitly because new supply would split liquidity.

## 3. NFL usage data — DONE, committed, NOT pushed

Three commits on `dev`, **unpushed**: `4e37340`, `2980b33`, `33390c4`.

**`backend/ingest_nfl_snap_counts.py`** (`4e37340`) — snaps were the missing "opportunity available"
half; logs had targets/carries but no snaps, so snap share was uncomputable. Two join frictions
solved: nflverse keys snaps by `pfr_player_id` while the spine stores `nfl_gsis_id` (crosswalk via
`nfl.import_ids()`), and **2024 rows have no `game_id`**, so the join is `(player_id, season, week)`.
Uses `json_patch`, so re-runnable and non-destructive. Backfilled dev: **5,329 rows 2024 + 5,360
rows 2025, 99.7% match.** OL/DL have snap rows but no game log — intentionally skipped.

**`backend/ingest_nfl_ngs_receiving.py`** (`2980b33`) — **the routes-run answer.** Routes run is
PFF/paid. I tried deriving it (snap share × team pass plays) and it fails for RB/TE because being on
the field for a pass ≠ running a route when blocking — verified: the proxy put Goedert at a **42%
TPRR**, far above any real elite rate. NGS sidesteps routes entirely by shipping **air yards share**
free, which with the derivable target share gives **WOPR = 1.5 × target_share + 0.7 ×
(air_yds_share/100)** — the actual standard usage metric. Also lands aDOT, separation, cushion,
yac_above_exp. **NGS keys on `player_gsis_id`, already in the spine → 100% match, no crosswalk.**
Backfilled dev: 1,253 rows 2024 + 1,213 rows 2025. Week 0 rows are season aggregates, skipped.

Verified output (2025 Wk1, by WOPR — elite is >0.8, so this is credible):
```
Jaxon Smith-Njigba SEA 77% snaps 13tgt 59.1% tgt_sh 91.0% ay_sh -> 1.523
Zay Flowers        BAL 90%        9    47.4%        54.3%       -> 1.091
Garrett Wilson     NYJ 100%      10    45.5%        58.0%       -> 1.088
```

**Target share is NOT stored — it is derived** with a window function over
`SUM(targets) PARTITION BY (game_id, team)`, falling back to `(season, game_no, team)` for 2024.
Verified against PHI Wk1 2025.

**THE TRAP:** two stat vocabularies. 2024 (`source='nflverse'`) = `receiving_yards`,
`rushing_yards`, `passing_yards`, `receptions`, `fantasy_points_ppr`. 2025
(`source='nflverse_pbp'`) = `rec_yds`, `rush_yds`, `pass_yds`, `rec`, `fpts_ppr`. Every read must
COALESCE both or 2024 silently returns nulls. `targets` is identically named in both — do not
COALESCE it.

**Unused but available, same one-line loader pattern:** `import_injuries`, `import_depth_charts`,
`import_weekly_pfr`. Depth charts + injuries are the "granular game context" Micah wants for
previews and playoff odds.

## 4. IN FLIGHT — the renderer

**Spec:** `docs/TASK-nfl-usage-renderer.md` (commit `33390c4`). Builds
`GET /api/nfl/usage/{player_id}` + `NflUsageTrend.tsx` + `useNflUsage.ts` + tests. Scope-locked to 6
files, DB read-only, no new deps, 7 required tests, Codex-verifiable acceptance criteria.

**Why it exists:** `player_game_logs` (130k rows) is wired as a **computation input only** — it
feeds prop probabilities and projections and comes out as a single number. The per-game trend renders
in exactly one place (`components/Props/PropChart.tsx`) and only via a prop with a market+line.
`GET /api/players/{id}` already returns 25 game logs with full stat blobs and **no frontend consumes
it** (grep for `game_log|gameLog|game_no` in `components/`+`app/` = zero hits). Data ✅ query ✅
endpoint ✅ renderer ❌.

**⚠ STATE AT HANDOFF: Hermes has EXITED (0 processes) and left the work UNCOMMITTED and UNVERIFIED.**
The 6 files exist in the worktree as untracked/modified, but the spec required them committed on
`feat/nfl-usage-renderer` and it did not commit. Its stdout was fully buffered so **its final report
and its own pass/fail checklist were lost** — `/root/hermes-nfl-usage.log` is 0 bytes. Nothing about
this code has been reviewed, tested, or type-checked. **Next session: treat these files as unverified
draft.** Have Codex (already briefed, tmux `codex:0.0`) run the acceptance checklist from scratch —
pytest, `npx tsc --noEmit`, the 2024-vocabulary check, and a hand-checked target share — before
anything is committed or merged. Do not trust the code because it exists.

**Original dispatch state:** Hermes (`deepseek-v4-pro`) ran in worktree `/root/lp-nfl-usage`, branch
`feat/nfl-usage-renderer` off `dev@33390c4`. It has produced all files:
`backend/routers/nfl_usage.py`, `backend/test_nfl_usage.py`, `components/Leagues/NflUsageTrend.tsx`,
`components/Leagues/hooks/useNflUsage.ts`, and modified `components/Leagues/types.ts` +
`backend/sports_service.py`. Codex has the manager brief and reviews against the checklist.

**⚠ MY SPEC BUG — tell Codex:** the spec says modify `backend/main.py` for router registration. The
real app entrypoint is **`backend/sports_service.py`** (see `scripts/hermes-worktree.sh`:
`uvicorn sports_service:app`). Hermes correctly used `sports_service.py`. Codex's acceptance
criterion (a) — "only the 6 files in Scope" — would **wrongly reject** this. `sports_service.py` is
in scope; `main.py` was my error.

## 5. Operational gotchas learned today

- **Do NOT run `scripts/hermes-worktree.sh up`.** It binds `:8096` and `:3096`, the exact ports the
  live externally-managed dev servers + cloudflared tunnel occupy. Create the worktree manually and
  symlink `node_modules`, `backend/venv`, `backend/data/picks.dev.db`, and `.claude` (the last is
  needed or the resource-check skill is unreachable from the worktree).
- **Hermes CLI:** the prompt flag is **`-z`**, not `-c` (`-c` = continue an existing session by
  title). OpenRouter key was **exhausted (402, ~1h cooldown)**; DeepSeek works, and valid model
  names are **`deepseek-v4-pro`** / `deepseek-v4-flash` (NOT `deepseek-chat`).
- **`tmux send-keys` can type a command without submitting it.** I twice reported Hermes as running
  when it was not, inferring from the absence of an error instead of checking for the process. Then
  a `nohup` launch I'd written off as dead was actually alive, so **two independent Hermes agents
  were briefly writing into the same worktree**. Found via PPID (one orphaned to PID 1), killed,
  kill verified. Always `pgrep` for the actual process after launching, and check PPIDs before
  assuming one agent.
- Box is 5.8GB, ~2.2GB swap in use, **31 `live_valuefade.py` processes** running from
  `/root/prediction-market-trading`. No parallel dev servers.

## 6. Open loose ends

- **Push `4e37340`, `2980b33`, `33390c4`** — committed to `dev`, not pushed.
- Hermes/Codex round trip on the renderer; apply the `sports_service.py` correction.
- **The `/strength` quality gate is broken and unfixed** (`prediction-market-trading/quality.py`):
  `_BASE` defaults to `:3007` where nothing listens (backend is `:8096`), and `_score_from_payload`
  reads `abbreviation`/`abbr` while the live payload uses **`abbrev`**. It fails closed silently.
  Consequence, verified: `quality-gated-hold` ran Jun 9–14 only, 59 ledgers, **0 BUY records** — the
  broken gate vetoed every candidate, so that strategy was never actually tested. Micah has
  deprioritized this whole path; fix only if asked.
- Version drift: `package.json` 0.6.4 + CHANGELOG v0.6.1–v0.6.4 vs last real tag **v0.6.0**. Four
  dangling numbers. **NO tags, NO releases without explicit per-instance approval.**
- `streams.py` treats decapi's `"X is offline"` as definitive, so a decapi wobble marks all Twitch
  dark for 90s.
- Unexplained: a scheduled esports match once reported `state=live` with a future start time.
- Unexplored embed sources: FIFA+, EHFTV, Courtside 1891, Volleyball World, World Rugby,
  `thepwhl.com`, Audacy.
- An unanswered prompt of Micah's still sits in Codex's history (Player X + sport.fun + app +
  lineups).
- Underdog fighter identity gap ("Ramazan Temurov" vs "Ramazonbek Temirov") — knowingly out of scope.

## Closed from 07-24

MLB R/RBI backfill complete (2026-03-15→07-23; the 3 gap days are the real All-Star break).
`ingest_mlb_logs.py` root-caused and rewritten day-by-day — `pybaseball.statcast(parallel=True)`
spawns a thread per day, which was the resource incident (`f19ea39`). `resource-check` skill written
(no hook — explicitly rejected, do not re-propose). MLB `hits_runs_rbis` compound chart fixed
(`4575b64`). UFC `fight_time` was in the ESPN `/status` response and being discarded; now derived and
ingested (`a97a638`). Esports viewer last-known-good fallback (`875185a`). Embeddable-streams
verification doc written and pushed (`988a238`). AGENTS.md §12 (`4df5d0a`, now pushed).
