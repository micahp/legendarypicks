# SPEC — NFL Product Direction

Status: strategic direction, actively evolving. Written 2026-07-22. Append, don't overwrite —
mark superseded sections instead of deleting them; the version history is part of the reasoning.

**Supersedes the framing of `SPEC-nfl-mock-draft-simulator.md`**: that spec is still valid as a
build plan, but it is no longer the headline NFL feature. This doc explains why and what is.

## The moat-adjacency framework

Micah's framing, and the right way to evaluate any NFL feature from here on: **props are the
moat** — data-intensive, hard to replicate casually, directly monetizable (the Phase 2 "did it
hit" B2B API plan). Every feature question should be "is this adjacent to props, or is it a
content-parity distraction?" — the esports board-polish grind (near-zero traffic, no monetization,
already abandoned once) is the standing cautionary tale for the wrong answer to that question.

## The core insight: sit/start and waiver advice ARE props, wearing different clothes

"Will this player outperform his line" (a prop) and "should I start this player over my other
option" (a fantasy decision) reduce to the identical underlying computation: a projected
performance probability. The EV/CLV fix (see below) is not a props-only investment — it is
*also* the sit/start engine, the moment its output gets a second UI pointed at fantasy framing
instead of betting framing. This reframes several things that looked like generic
"ESPN-content-parity" builds into genuine moat-adjacent work:

- **Injuries** — not a standalone content tab. An input to sit/start calls, waiver
  opportunity signals, AND (see below) a real input to game/season-outcome prediction (538's NFL
  Elo model's signature refinement is a QB-injury-driven rating adjustment). One data source, three
  consumers.
- **Transactions (Offseason Movers, already shipped)** — already a genuine year-round habit
  driver (posts daily, not just preseason) and a direct input to "who's trending up" waiver
  content.
- **Draft Room / mock draft simulator** — real, but the weakest piece for retention: a mock
  draft is a one-shot, pre-season-only artifact. Worth having (see the existing spec), not worth
  leading with.

### Ranked priority (moat-adjacency + buildability, highest first)

1. **Weekly sit/start signal** — near-free once the projections/EV engine is real (in progress,
   see below). Same computation as props, second UI.
2. **Waiver-wire / "trending up" feed** — buildable today from Offseason Movers + an opportunity
   signal (team change, depth-chart opening from an injury/release). Caveat, stated plainly: this
   is the *generic* version ("players worth watching"), not the *personalized* version ("add this
   guy, he's open in your specific league") — the personalized version needs a real Yahoo/ESPN/
   Sleeper league-roster integration, a materially bigger lift, and is the actual north star if
   this becomes a real retention driver.
3. **Injuries data** — as an input to #1 and #2, not a standalone tab. Recon not yet done on
   whether a free ESPN-style injury feed exists (the transactions API precedent — reachable even
   though www.espn.com's own CDN blocks this host — suggests it's worth checking before assuming
   it's out of reach).
4. **Draft Room / mock draft simulator** — see `SPEC-nfl-mock-draft-simulator.md`. Real, but
   scoped correctly now: an August-relevant feature, not the retention mechanism.
5. **True personalization (connect-your-league)** — the biggest lift of anything on this list,
   and the thing that would make #1/#2 excellent instead of generic. Not v1.

## EV/CLV: what's actually broken (verified 2026-07-22)

Diagnosed precisely before delegating (not guessed): this is props-specific (not moneyline/
game-winner prediction).

- **EV** computes mathematically-guaranteed-zero results. `_ev_inputs()` (`backend/_core.py`)
  falls back to `props.odds` alone whenever `prop_odds_snapshots` has no opening row for a prop —
  which is *always*, because nothing populates that table. The three scheduled systemd services
  (`legendarypicks-props*.service`) only ever run `bovada_scraper.py all --ingest`; the
  `--capture` flag that would populate `prop_odds_snapshots` exists in code but is never scheduled.
  Without a captured pair, `p_fair = implied_prob(odds)` — the same price used as its own "fair"
  probability — and `ev(odds, implied_prob(odds))` is exactly 0 by construction. Confirmed live:
  200k+ MLB rows, `positive_ev_pct: 0.0`, `mean_ev` ≈ 0 (rounding noise only).
- **CLV** is empty for every league, no exceptions. The `is_close` column exists
  (`prop_odds_snapshots`, default 0) and the CLV query reads it, but nothing ever sets it to 1 —
  a genuine missing pipeline stage ("M6 closing-snapshot capture"), not a math problem.
- Even once "paired" de-vig is real (capture actually running), EV still only measures whether
  the market agrees with itself — it needs an independent probability estimate to ever show a
  real edge. `analytics/projections.py`'s `prob_over()` already exists and is the natural source;
  it's just never wired into the EV computation.

**In progress**: delegated to Hermes, MLB-only first, in an isolated worktree
(`/root/lp-mlb-ev-clv`, branch `feat/mlb-ev-clv`, off `dev` — NOT `feat/nfl-camp-mode`, kept
deliberately separate after almost landing on the wrong branch). Scope: (1) get `--capture`
actually scheduled with a real opening+closing cadence, (2) wire `is_close` through so CLV has
data at all, (3) feed `prob_over()` into EV as an independent signal. Verification bar: real
`de_vig_confidence: "paired"` rows, a non-degenerate EV distribution, `clv` returning
`n_props > 0`. Once MLB is solid, the same fix gets delegated per-league (NFL directly benefits
the sit/start engine above).

## Championship/playoff prediction — inputs audit

The ambition stated: predict the Super Bowl winner, benchmarked against known systems. Three
different categories got conflated in the original ask and are worth separating, since they need
completely different inputs:

- **538-style Elo** (margin-of-victory, QB-adjusted, home-field/rest adjustments): we have the
  raw ingredient (`team_game_results`, real per-game data across all four leagues) but two real
  gaps — (1) NFL's `team_game_results` covers **one season only (2025)**; Elo needs
  season-to-season carryover (538 blends last year's final rating toward the mean as the next
  season's prior), which isn't possible with one season on file. (2) No QB-adjustment layer
  exists — the exact same injury signal the sit/start engine needs, reinforcing the "one input,
  multiple consumers" theme above.
- **FPI-style** (efficiency margin — offense/defense/special-teams, each strength-of-schedule
  adjusted — combined and Monte-Carlo-simulated forward for playoff odds): bigger lift than Elo,
  more transparent, and it's the one ESPN itself runs across **both NFL and NCAAF** with one
  shared framework — relevant if NCAAF is really in scope (see below). Zero code for this exists
  today.
- **EA Sports-style sims**: a different category entirely — a game engine simulating actual plays
  via EA's proprietary licensed player ratings, not a stats model. Not a real benchmark to build
  toward the same way as the two above; dropped as a design target.

No rating/simulation system exists for any traditional (non-esports) sport in this codebase today
— esports has one (LoL MSI, Elo-based) as a precedent for the *pattern*, not the inputs.

## Analyst-accountability tracking (BettingPros/Action Network-style)

The modeling/mechanic side of this is **already solved** — it's the same accountable
binary-pick-with-permanent-record mechanic as `SPEC-esports-pick-desk-mvp.md` (pick, lock at a
deadline, settle against an authoritative result, permanent public W-L record, compare against
the crowd). Applying it to named external analysts instead of anonymous crowd share is a framing
change, not a new system. The open question is sourcing, not modeling: track our own users' picks
(already buildable on existing infra) vs. specific named analysts' public picks (a data-sourcing
problem — where do their picks come from, and how do we verify them honestly).

## The content flywheel: "every data point is two-fold"

Micah's framing: every data point (an injury, a trade, a play, a down) is simultaneously (1) a
predictive input and (2) content-worthy on its own — "beat/missed expectation" framing is
inherently shareable. This is not a new system to build — **`PropChart` already does exactly
this at the player level** (bar chart of last N games vs. the line, hit rate, projection). The
open idea is the same mechanic one level up: team/game-level "beat expectation" charts (e.g. "this
team has covered in 8 of its last 10"), which reuses the same underlying line/actual-result data,
just aggregated differently. Cheap extension of something proven, not new infrastructure.

## NCAAF — real scope, not a footnote

Checked directly: **zero NCAAF presence anywhere in the codebase.** If "just as important as
NFL" holds, this is a genuinely separate build — hundreds of FBS teams, conference structure never
modeled, and (not yet confirmed) likely a different ESPN API surface than the one powering our NFL
pipeline. Worth a recon pass on ESPN's college-football API surface before scoping further, same
way the NFL transactions API was found by checking `site.web.api.espn.com` directly rather than
assuming.

## Open questions / next steps

- Injury data source recon — does a free ESPN-style feed exist (parallel to the transactions API
  find), and would it need real ingestion work or is it another `site.web.api.espn.com` win?
- NCAAF API surface recon — same question, different league.
- Whether "waiver-wire personalized to your league" (real Yahoo/ESPN/Sleeper integration) is worth
  pursuing at all before the generic version proves people use it.
- Micah's own research into the most-accurate public playoff-prediction system (in progress,
  external to this doc) should inform whether Elo or FPI is the actual target to build toward.
