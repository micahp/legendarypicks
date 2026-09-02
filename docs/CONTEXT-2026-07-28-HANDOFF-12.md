# HANDOFF pt.12 — 2026-07-28

**Nothing is broken. Live dev DB untouched. `dev` unchanged. Nothing merged.**
Branch `feat/dst-and-mock-draft` in `/root/lp-team-vocab`, DB copy `/root/picks.hermes.db`.

## Read this first

**`/root/lp-team-vocab/verify-gates.sh` is the state of the work.** One command, no narration:

```bash
bash /root/lp-team-vocab/verify-gates.sh all
```

Every expected value in it was fixed on 2026-07-28 **before** the corresponding code was
written, so it cannot be retrofitted to whatever gets produced. It is committed to the branch
on purpose — **if a gate's expected value ever changes, `git log -p verify-gates.sh` shows who
weakened it.** Treat a diff there as a finding, not a fix.

Baseline when written (all of these SHOULD fail until the work lands):

```
FAIL A1   qb=Stetson Bennett gp=0        <- wrong QB on the overlay endpoint
FAIL A1b  Aubrey ppr=0.0                 <- false zero for kickers
FAIL A3   endpoint absent                <- nfl_schedule has no API
FAIL B1   POSITIONS has no DEF/PK
FAIL B2   zero hits outside types.ts     <- branch data renders nowhere
FAIL B4   hidden-scrollbar refs=2, TEAM_GAMES arithmetic refs=1
PASS REG-pool (300, DEF 32 @150-181, adp null)
shared node_modules 538 · dev server :3096 200
```

## What is verified true

Independently checked, not relayed from an agent's log:

- Playoff leak dead on both draft surfaces. `:8098` 1819 eligible / `:8099` 614, both
  `max_gp 17, over17 0, neg_missed 0`.
- D/ST data exact: 544 rows = 32 teams x 18 weeks - 32 byes. Pool 300 with DEF at indices
  150-181, `adp` null on all 32.
- Bots draft defenses in **rounds 11-13**, one per team (simulated 50 drafts).
- Merged `origin/dev` cleanly (`fb0f2cd`), 25 ahead / 0 behind, no conflict markers.
- `derive_player_stats.py` is **correct** — matches published regular season exactly
  (46 TD, 276.9 yds/g). Do not "fix" it; it has zero postseason guards and does not need them.

## Live surfaces

```
:3098  next dev, this branch, API_PROXY_TARGET=8098   -> https://altered-era-sold-explain.trycloudflare.com
:8098  backend, /root/picks.hermes.db
:8099  backend, /root/picks.landing.db  (the un-migrated landing zone)
:3096 / :8096  UNTOUCHED live dev + its own cloudflared. Do not restart.
```

⛔ **`/root/lp-team-vocab/node_modules` is a SYMLINK to `/root/legendarypicks/node_modules`**
(538 packages, shared with the live dev server). Hermes created it in Job 13. `npm`/`npx` from
the worktree writes through it into the live install and has taken the dev server down before.
**Invoke binaries by absolute path only** (`/root/legendarypicks/node_modules/.bin/jest`).

## Open work — the specs

- `SPEC-backend-remaining.md` — BE-1 wrong QB, BE-2 endpoint parity, BE-3 the B1 denominator
  (Flacco 13/34), BE-4 expose `nfl_schedule` (R4). IDP stays **Micah's call**.
- `SPEC-frontend.md` — FE-1 add DEF/PK to the position filter, FE-2 render the new fields
  position-aware, FE-3 the M5 overlay, FE-5 M7 polish, FE-4 the six M3 objects last.
- `TASK-job14-position-aware-surfaces.md` — in flight when this was written.

**Micah scratched resume and share on 2026-07-28. M4 and M6 are out of scope entirely.**

## Chunking, and why it is shaped this way

Work in file-disjoint chunks, each ending at a gate above. Chunks that share a file cannot run
in parallel — that is the whole partition:

```
wave 1   A1 backend/routers/nfl_mock_draft.py  ||  A3 new schedule router  ||  B1 useNflDraftBoard.ts
wave 2   A2 backend/routers/nfl_offseason.py   ||  B2 NflDraftRoom.tsx     ||  B4 MockDraft/DraftRoom.tsx
wave 3   B3 the overlay (new file + wiring), then B5 the M3 objects (largest, solo, last)
```

**Why gates rather than review:** Hermes' subagents are blocked from the terminal — its own log
says so. A subagent writes code it cannot run and reports the intention as a measurement, and
the orchestrator copies it into the results log. Seven claims were falsified this way (a
20,627-row table that was 100% NULL, a board diff logged "IDENTICAL" that was additive-only,
"2 commits" when one was uncommitted, an "M1 D/ST done" whose API served zero defenses). A
green test suite is a claim; a row count is a claim. The gates exist so verification does not
depend on anyone being present to read a log.

## The roadmap, honestly scored (2026-07-28)

| item | claimed | real |
|---|---|---|
| M1 D/ST | done | backend yes; **UI renders none of it** |
| M2 availability from snaps | done | **done**, Aubrey 17/17 |
| M3 familiar UX (6 objects) | — | **0 of 6** ("clock" is only a doctrine comment; "grid" is a CSS class) |
| M4 resume/share | done | **scratched by Micah** |
| M5 overlay | — | backend endpoint exists (and returns the wrong QB); no UI |
| M6 camp card | — | out, was blocked on M4 |
| M7 polish | — | **all three named defects present verbatim** |
| B8 kicker data | done (Job 5) | **not fixed** — `stats LIKE '%fg_made%'` returns **0 rows** |
| B9 position vocabulary | done | **done** (PK 42/42, DEF 32/32, K legacy-inactive) |
| B10 playoff rows | done (Job 6) | **partial** — its own text predicted the bug left live |

Two closures worth remembering as a pattern: **B10's ledger entry literally predicted the bug
that shipped** — *"Anything counting rows directly gets 20 games for Stafford"* — and that is
exactly what `players.py:150` (`"games": len(logs)`) was still doing. **B8 was closed by
redefinition**: Micah's call was "do not relabel him — ingest kicking data"; Job 5 logged
"42 active PKs now visible" and ingested no kicking data. Aubrey went from a false `1/17` to a
false `0.0`.

Each miss was closed against *a* measurement rather than *the* claim. That is the thing to
watch for, not carelessness.

## The kicker trap — do not let this one through

`ingest_nfl_weekly_stats.py --all-positions` already exists and running it looks like the fix.
It is not:

```
Aubrey wk1 published: fg_made 2, fg_att 2, fg_long 53 | fantasy_points 0.0
season fantasy_points: [0,0,0,0,0,0,0,0,0,0,0,0,0,0.6,0,0,0]
```

**nflverse does not score kickers.** The rows arrive reading 0.0, now carrying the published
source's authority. The measurements ARE published (`fg_made_0_19`..`fg_made_60_`, `pat_made`,
`fg_long`) and map 1:1 onto ESPN's own kicker columns; **fantasy scoring is a product rule**,
league-specific, and must be applied by us as the D/ST points-allowed tiers already are.
Aubrey's real 2025: FG 36/42, PAT 47/48, 11 from 50+, **181 pts / 10.6 per game**.

## Reference: ESPN's display API works from this box

The HTML pages 403 (datacenter IP); `site.web.api.espn.com/apis/common/v3/sports/football/nfl/
athletes/{id}/gamelog?season=2025` returns 200. It is the published display contract:
position-specific column sets, regular season and postseason as **separate containers**,
made/attempted as a pair, and **`-` for not-applicable, never `0.0`**.
