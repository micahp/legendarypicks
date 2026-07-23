# SPEC — Phases of the Proprietary Prediction System

Status: roadmap, actively evolving. Written 2026-07-22. Append, don't overwrite — mark phases
superseded/re-scoped instead of deleting them.

This is the build sequence for the actual prediction/rating engine — distinct from
`SPEC-nfl-product-direction.md`, which is about which *features* to build (sit/start, waiver
feed, mock draft) against the moat-adjacency framework. This doc is about the *system underneath*
those features: how we get from where we are today (a props scraper with a broken EV calc) to a
real proprietary edge — our own numbers, not just relayed market prices.

Each phase depends on the substrate of the one before it. Don't skip ahead — Phase 3 (team
ratings) is meaningless without Phase 1 (real EV/projections) already working, because a team
rating system still needs individual player/game inputs to be honest in the first place.

## Phase 0 — Foundation (done)

Already built, not re-litigated here: ESPN-based scores/schedule/stats backend, `player_game_logs`
(111k+ rows across 4 leagues), Bovada props scraper (`bovada_scraper.py`) feeding `props` /
`prop_games`. This is real infrastructure, not a gap — it's the raw ingredient everything below
consumes.

## Phase 1 — Real EV/CLV (MLB done and live; other leagues partially blocked)

The props-vs-market edge engine. Without this, there is no proprietary signal anywhere in the
product — "EV" used to just compare the market's price to itself (see
`SPEC-nfl-product-direction.md` for the full root-cause diagnosis).

**Status (2026-07-22, current)**: done for MLB and merged. Two commits on the former
`feat/mlb-ev-clv` worktree branch, now in `dev` (`bcfe6a9`): (1) CLV fixed — derives "close" from
`captured_at <= game.start_time` rather than a never-set `is_close` flag, real data now (1,546+
results). (2) EV fixed — `analytics/projections.py`'s `prob_over()` wired in as an independent
probability source (player's own last-30-games history vs. the line), falling back to de-vig only
when there isn't enough game-log history. Verified live: 90/500 sampled props are now
projection-backed with a real, non-degenerate EV distribution (72 positive where there were 0
before) instead of the old market-agrees-with-itself tautology. Production capture scheduling is
live (`legendarypicks-mlb-capture.timer`, MLB-only, every 5 min, verified against the real prod
backend/DB before enabling — not just the isolated dev copy, after the systemd incident taught
that lesson). **Not yet done**: the actual fixed code isn't serving live requests yet — prod runs
from a built Docker image, not live from the checkout, so a deliberate `docker compose up -d
--build` redeploy is still a separate, held decision.

**NFL/NBA/NHL: EV/CLV split into two halves that are blocked for different reasons, and only one
of them actually requires the season to have started.**

- **The market half** (de-vig against real captured odds, and all of CLV) — fully blocked, no way
  around it. No book lists player props for a league with no games; there's no price to capture,
  full stop. This half can't start until each league's regular season is live.
- **The projections half** (`prob_over()` against a player's own game-log history) — **not
  blocked at all**, and worth doing now as dead-time work. Real historical game logs already
  exist: NFL 5,377 rows / 605 players (2024+2025), NBA 24,086 rows / 580 players (2026), NHL
  48,017 rows / 842 players (20252026). The same market→stat mapping pattern as MLB's
  `_MLB_MARKET_STAT` (NFL: pass_yds/receptions/rush_yds; NBA: pts/reb/ast; NHL: goals/assists/
  shots) can be built and validated against real historical outcomes *before* any of those
  leagues' seasons start — so the projection engine is already proven the moment real props
  appear, instead of starting that validation cold once the season begins.

Once each league's market half unblocks (season starts, real props appear), only the capture
scheduling + wiring needs to be delegated per-league — the same pattern already proven on MLB.
NFL's market half unblocking directly feeds Phase 2.

## Phase 2 — Application layer: sit/start + waiver-wire (not started)

Same Phase 1 engine, second UI, fantasy framing instead of betting framing — this is not new
modeling work, it's a new consumer of Phase 1's output. See `SPEC-nfl-product-direction.md`'s
ranked list for the generic-vs-personalized scoping (personalization needs a real league-roster
integration; the generic version doesn't).

## Phase 3 — Team-level rating system (not started, blocked on real data gaps)

The actual "proprietary" layer in the sense Micah means it — our own read on which teams are
good, not just individual player props. Two real methodologies under consideration, genuinely
different in what they need:

- **538-style Elo**: margin-of-victory-based, updated after every game, with a QB-adjustment
  layer (a team's rating should move hard when the starter is hurt — same injury signal Phase 2
  needs) and home-field/rest adjustments. Simpler to build, less transparent about *why* a rating
  is what it is.
- **FPI-style**: offensive/defensive/special-teams efficiency margins, each adjusted for
  strength of schedule, combined into a per-game efficiency rating. More transparent, more work,
  and it's the framework ESPN runs across both NFL and NCAAF with one shared methodology —
  relevant if Phase 6 (NCAAF) is real.

**Known blockers, not yet resolved**: NFL's `team_game_results` covers one season only (2025) —
Elo-style carryover needs at least one prior season to blend from. No rating/simulation code
exists for any traditional sport today (esports has an Elo model for LoL/MSI as a *pattern*
precedent, not a data precedent). Micah is independently researching which public system
(FiveThirtyEight-style vs. FPI-style) is most accurate on playoff predictions — that finding
should decide which methodology this phase actually builds, not a guess made here.

## Phase 4 — Season/playoff simulation (not started, depends on Phase 3)

The literal "who wins the Super Bowl" deliverable. Monte Carlo forward-simulation of the
remaining schedule using Phase 3's team ratings, producing division/conference/championship
probabilities per team. Cannot be built before Phase 3 exists — there is no "simulate the season"
without a real team-strength number to simulate from. This is also where EA-Sports-style game
simulation was explicitly ruled out as a comparable (see product-direction doc) — that's a
different category of system (a game engine with licensed player ratings), not a statistical
model we can build toward the same way.

## Phase 5 — Accountability / analyst-tracking layer (not started, no new modeling needed)

The BettingPros/Action-Network-style "track the analysts" idea. The mechanic already exists —
it's the same accountable binary-pick-with-permanent-record system as
`SPEC-esports-pick-desk-mvp.md` (pick, lock, settle against an authoritative result, public
record, crowd comparison), pointed at Phase 3/4's model output instead of (or alongside) esports
matches. Open question is sourcing, not modeling: our own users' picks (buildable now) vs. named
external analysts' public picks (a data-sourcing problem — where do their picks come from, how do
we verify them honestly).

## Phase 6 — Multi-league expansion: NCAAF (not started, real scope)

Confirmed zero NCAAF presence anywhere in the codebase today — a genuinely separate build
(hundreds of FBS teams, conference structure never modeled, likely a different ESPN API surface
than the one powering NFL). Only worth starting once Phases 1-4 are proven on NFL — the point of
building this system once, properly, is that Phase 6 becomes "apply the same phases to a new
league" rather than a second from-scratch system.

## Sequencing summary

```
Phase 0 (done) → Phase 1 (in progress) → Phase 2 (sit/start, unlocked by Phase 1)
                                       → Phase 3 (team ratings, blocked on data + methodology choice)
                                            → Phase 4 (season/playoff simulation)
                                       → Phase 5 (accountability layer, no hard dependency, can start anytime after Phase 3/4 has an output to track)
                                       → Phase 6 (NCAAF, repeats Phases 1-4 for a new league)
```
