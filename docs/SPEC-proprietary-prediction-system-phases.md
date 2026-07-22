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

## Phase 1 — Real EV/CLV (in progress, MLB first)

The props-vs-market edge engine. Without this, there is no proprietary signal anywhere in the
product — "EV" currently just compares the market's price to itself (see
`SPEC-nfl-product-direction.md` for the full root-cause diagnosis). Scope:

1. Get the opening-odds `--capture` step actually scheduled and running (currently dead code —
   the flag exists, nothing invokes it in production).
2. Wire `is_close` through so a real closing snapshot gets captured near each game's start,
   giving CLV actual data (currently zero across every league, no exceptions).
3. Feed `analytics/projections.py`'s `prob_over()` into the EV calculation as an independent
   probability estimate — the only way EV can ever reflect a real model-vs-market disagreement
   instead of the market agreeing with itself.

**Status**: delegated to Hermes, isolated worktree `/root/lp-mlb-ev-clv` (branch
`feat/mlb-ev-clv`, off `dev`). Code fix committed (`e05f75f`) — CLV already returns real numbers
(1,546 results, 0.6% positive) once the local capture ran. Production scheduling is NOT yet
applied (a live systemd edit went out ahead of verification and was reverted — see the product-
direction doc's status note). Next: review the worktree diff, verify against the real prod
backend/DB (not just the isolated dev copy), then apply the scheduling change deliberately.

Once MLB is solid, this same fix gets delegated per-league — NFL directly unblocks Phase 2.

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
