# Context reset — four-league team stats

**Updated:** 2026-07-14 (America/Chicago)

## Read this first

The primary product goal is now **real team statistics for the four major leagues:
MLB, NBA, NFL, and NHL**.

Do not make League Overview / "What changed" the next feature, and do not continue
the MLB identity-repair project merely because tooling for it exists. The immediate
work is to make the Teams destination genuinely useful in all four leagues with
measured, season-appropriate data and explicit coverage guarantees.

The intended next sequence is:

1. Audit the existing NBA, NHL, and NFL team-game data and ingestion code without
   changing the shared database.
2. Define one honest aggregate/coverage contract that supports league-specific team
   categories.
3. Complete season coverage for NBA and NHL and implement NFL extraction/backfill.
4. Expose real Teams tabs for MLB, NBA, NFL, and NHL.
5. Verify the real frontend/backend contract without disrupting the shared runtime or
   tunnel.

## Delegation policy

When the user asks to delegate work to Reasonix, use the existing tmux pane
`reasonix:0.0`. Do not create an internal Codex sub-agent and name it Reasonix.
Delegate by sending a fully bounded prompt to that pane, inspect its proposed
commands before allowing execution, and monitor its output with tmux capture.

Reasonix must stay in `/root/lp-leagues-hub` on `feat/leagues-hub`. It must never
touch `/root/lp-pick-desk`, branch `dev`, the shared frontend/backend/tunnel
processes, or write to `/root/legendarypicks/backend/data/picks.dev.db`. Team-stats
schema and backfill work must use a new single-link regular SQLite file under
`/tmp`. With current memory pressure, begin with one league/season against fixtures,
check `free -h` before heavier work, and do not run a full or multi-year ingest
without a new resource review.

## Repository state

- Worktree: `/root/lp-leagues-hub`
- Branch: `feat/leagues-hub`
- Branch is five commits ahead of `origin/feat/leagues-hub` as of this handoff.
- Do not switch the dev tunnel to another worktree.
- Do not run `npm run build`; a previous build overwrote `.next` used by `next dev`
  and broke the visible development site.

Local commits not yet pushed, newest first:

- `819b174` — copy-only MLB identity repair applier and application report
- `871f964` — review the MLB identity repair population
- `609c949` — make Statcast ingestion resolve-or-queue unresolved identities
- `be7b27a` — proposal-only MLB identity repair planner
- `a2fa715` — measured MLB team aggregates and league navigation

Already pushed to `origin/feat/leagues-hub`:

- `87503b7` — Sport.Fun corpus narrative and product recommendations
- `04f1709` — seven-day esports retention and durable API-key hydration
- `0318194` — recent-form changes in the league stats UI
- `fc887ff` — recent-form evidence in the stats API
- `13fe7db` — advanced categories, sorting, formatting, and URL state

Unrelated shared-worktree state must remain untouched:

- modified `components/Scores/GameCard.tsx`
- untracked `backend/data/esports_team_logos.json`
- untracked `backend/venv`
- this context document is currently untracked unless a later session commits it

## Shared runtime safety

The user experienced two dev-site outages during this work. Treat runtime stability
as a hard constraint.

Last known shared services:

- frontend: Next dev on `127.0.0.1:3095`
- backend: Uvicorn on `127.0.0.1:8095`
- backend source: `/root/lp-leagues-hub/backend`
- shared development DB:
  `/root/legendarypicks/backend/data/picks.dev.db`
- Cloudflare quick tunnel points at the frontend on port 3095

Do not restart the frontend, backend, or tunnel during ordinary implementation or
diagnosis. If a restart becomes genuinely necessary, first capture the exact command,
working directory, database path, and environment. The backend must retain its
PandaScore, GRID, YouTube, and DeepSeek environment; `04f1709` self-hydrates missing
keys from `/root/.hermes/.env`, but full user-visible output still needs verification.

The frontend was recovered successfully with this detached shape:

```sh
setsid bash -c 'exec env API_PROXY_TARGET=http://127.0.0.1:8095 node_modules/.bin/next dev -H 127.0.0.1 -p 3095' > logs/dev-frontend.log 2>&1 < /dev/null &
```

This is recovery context, not permission to restart it proactively.

## What is complete in the league UI

Commit `a2fa715` added:

- `/api/{league}/team-aggregates`, currently supporting measured MLB only;
- a 30-row MLB Teams view derived from `team_game_results`;
- coverage checks for all 30 teams, reciprocal paired game rows, scores, winners,
  and invalid games;
- neutral league-switcher links above the page title, visually similar to the home
  navigation row;
- no highlighted current-league text and no switcher background container;
- Teams omitted for leagues where the app cannot yet make an honest season claim.

Isolated end-to-end verification passed after that commit: MLB rendered 30 rows,
other leagues did not show Teams, the switcher was neutral, and there were no browser,
request, or React-key errors. Real shared-runtime verification remains necessary after
the four-league work, but do not disturb the runtime merely to repeat isolated proof.

## Current four-league team-data boundary

### MLB

- `team_game_results` has season-complete enough captured results for the current
  aggregate view.
- The current columns are Games, Wins, Losses, Runs For, Runs Against, and Run
  Differential.
- Coverage is explicit but is not yet reconciled against an external authoritative
  schedule (`external_schedule_reconciled: false`).
- MLB is the existing reference implementation, not the final cross-league contract.

### NBA

- `team_game_stats` already has per-game fields for shooting, rebounds, assists,
  steals, blocks, turnovers, fouls, paint/transition scoring, and related metrics.
- `backend/backfill_team_stats.py` can pull NBA ESPN boxscores, but existing captures
  are partial and its date-loop/upsert behavior needs a correctness audit.
- `/api/{league}/team-stats` currently returns raw recent rows with a 200-row limit;
  it is not a season aggregate or coverage contract.

### NHL

- `team_game_stats` already has per-game fields for shots, blocked shots, hits,
  takeaways, giveaways, faceoffs, power play, shorthanded goals, and penalties.
- `backend/backfill_team_stats.py` can pull NHL ESPN boxscores, but existing captures
  are partial and need full-season reconciliation.
- Goalies are a separate player-stat ingestion gap; they should not block honest NHL
  team aggregates.

### NFL

- NFL team-stat ingestion is not implemented. `backfill_nfl()` only examines up to
  seven recent days and explicitly skips extraction.
- Build season-aware historical ingestion rather than querying only the current
  offseason date window.
- The eventual Teams UI should distinguish offense, defense, and special teams rather
  than flattening unlike metrics into one generic table.

## Required team-stats product contract

The API should not imply that all leagues share the same useful statistics. Preserve
a common response envelope while making categories and columns league-specific.

At minimum, every response should communicate:

- league and season;
- whether the view is supported;
- data source and captured/reconciled scope;
- first and last covered game dates;
- expected and observed team counts;
- expected, observed, paired, and invalid game counts where determinable;
- category definitions and sortable columns;
- team rows with games played so per-game and rate metrics have visible denominators;
- a machine-readable reason when coverage is not trustworthy.

Suggested initial categories:

- MLB: record and run production/prevention;
- NBA: scoring/shooting, rebounding, playmaking/ball security, and defense;
- NHL: scoring/shots, possession/physical play, and special teams;
- NFL: offense, defense, and special teams.

Never silently treat a partial capture as season-to-date. Prefer a truthful unsupported
response while ingestion is incomplete, but the product objective is to complete the
ingestion—not to hide NBA, NHL, and NFL Teams indefinitely.

## Concrete next task

Begin with a read-only audit of:

- the `team_game_stats` and `team_game_results` schemas;
- row, game, team, season, date-range, paired-row, null-field, and duplicate coverage
  for MLB, NBA, NHL, and NFL in the shared development database;
- `backend/backfill_team_stats.py`, `_core.py` extraction/snapshot helpers, and the
  current raw `/api/{league}/team-stats` route;
- ESPN scoreboard/summary shapes already captured in tests or fixtures.

Then write the implementation plan and tests around observed gaps. Developing code and
testing on fixtures/copies is authorized by the product request. Mutating the shared
development database for a full backfill should be announced first, backed up, and
verified; production remains a separate approval and promotion.

## Parked MLB identity-repair work

The MLB identity work was a data-integrity prerequisite identified in the previous
recommendations, but the user clarified that it is not the current main product goal.
Do not continue it automatically.

What was proven on an isolated `/tmp` copy:

- 135 safe identity repairs applied successfully in one transaction;
- 2,781 correctly keyed logs moved to canonical players;
- 1,380 displaced-key logs moved to represented candidates;
- 5,213 unrepresented displaced logs and 404 stale aggregates were archived;
- 7,342 affected props were preserved;
- duplicate MLBAM groups remained zero;
- Statcast aggregates regenerated for the repaired population;
- whole-population safe proposals fell from 135 to zero;
- 31 deliberately ambiguous/no-anchor cases remained unresolved.

The copy-only applier refuses non-`/tmp` databases, symlinks, hardlinks, WAL/SHM
sidecars, and mismatched database/proposal hashes. Its guard, planner, and Statcast
tests pass.

No repair was applied to the shared development database or production. Applying it
to shared dev requires explicit user approval. It does not need to happen before
building the four-league team-stats contract on fixtures or database copies.

## Research documents

- `docs/RECOMMENDATIONS-2026-07-13-LEAGUES-HUB.md`
- `docs/SPORTFUN-ARTICLE-CORPUS-NARRATIVE-2026-07-13.md`
- `docs/MLB-IDENTITY-REPAIR-PLANNER-2026-07-13.md`
- `docs/MLB-IDENTITY-PROPOSAL-REVIEW-2026-07-14.md`
- `docs/MLB-IDENTITY-COPY-APPLICATION-2026-07-14.md`

The recommendations document still contains the older ordering in which MLB identity
repair precedes team-stat expansion. The user's latest instruction supersedes that
ordering: **team stats for MLB, NBA, NFL, and NHL are the main goal now**.

## Reset-session definition of done

Do not declare the goal complete after adding tabs or returning rows. Completion means:

1. all four leagues have measured, league-appropriate season team aggregates;
2. ingestion can reproducibly build and update that coverage;
3. the API discloses coverage and fails closed on incomplete data;
4. the frontend exposes useful sortable Teams categories in all four leagues;
5. tests cover aggregation integrity, coverage failure, and league-specific contracts;
6. the real dev frontend/backend/tunnel path is verified without collateral runtime
   regressions.
