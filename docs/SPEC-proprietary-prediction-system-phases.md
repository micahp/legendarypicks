# SPEC — Phases of the Proprietary Prediction System

Status: roadmap, actively evolving. Written 2026-07-22; **updated 2026-10-27**. Append, don't overwrite — mark phases
superseded/re-scoped instead of deleting them.

**Current interpretation:** The July phases below are a historical implementation snapshot, NOT the current
status. The authoritative October 27 change log and reordered phase gates appear in **§7 below** and in
[the updated granular modeling strategy](STRATEGY-GRANULAR-PREDICTION-MODELS-2026-10-26.md#16-evidence-update-and-model-roadmap-2026-10-27).
Do not assign new work from an old "not started" heading without checking §7.

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

---

## 7. October 27, 2026: current model roadmap and superseded July status

This section **supersedes the old phase-status claims above**, but preserves their original text for historical accountability. The user has chosen an independent football-data forecast architecture: **market odds, spreads, totals and sportsbook player projections are excluded as model features, priors and targets**. Bookmaker data remains available only as a timestamped **external benchmark after our forecast has been locked**, not a way to tune the independent model to a line.

### 7.1 Status correction by original phase

| Original phase / July claim | Updated state as of 2026-10-27 | Still unproven or open |
|---|---|---|
| 0. Foundation | Existing scores, play-by-play, player logs, injuries, snaps, roster and schedule history now underpin multiple working NFL prototypes | Publication-time provenance for older datasets and a unified identity/versioned feature store |
| 1. EV/CLV and player projection | Real prop boards, historical hit rates, probability calibration research and prospective NFL props are active research/product work; MLB's old status is a historical observation, not current prod certification | Independent prop forecast quality by contract, conditional DNP/active, as-of captured lines and valid proper scoring |
| 2. Sit/start | Opportunity forecasts and with/without-player concepts now feed broader availability research | Full official inactive labels, probabilistic workload, user-ready evaluation and fantasy application |
| 3. Team ratings | **Not unstarted:** NFL v1 points is locked and graded; v2 EPA and Elo variants have been evaluated; opponent-adjusted contextual play sampling has completed 10k research batches | Matchup-specific player-aware coherent scores, uncontaminated historical inputs, out-of-sample superiority over v1 |
| 4. Season/playoffs | **Not unstarted:** NFL playoff-odds and score samplers exist; statistical full-game simulator S0/S1 executes thousands of games | Cross-team scoring-dispersion gate (earlier ratio 0.791), legal full-game tail coverage, valid tie rules, fair pregame forecasts |
| 5. Public accountability | The NFL model page already locks and grades scores/picks; model selection, leans and qualifying wagers have distinct policy/record definitions | Full publicly graded win/total/spread/player-calibration tables with authentic pregame versions |
| 6. NCAAF | **Not unstarted:** FBS predictive ladder and props research exist, with verified model results and identified coverage/parity blockers | Chronological model/production parity, props baseline wins, league-specific rules and data rights |

A model branch, diagnostic, or local evaluation is not a production release. The current `dev` and production states must be checked at promotion time; do not mark these phases "shipped" from research commits.

### 7.2 Phase 1 NFL consolidation: distinct gates, not a single merge flag

**S0, contextual S1, the v1 game-score model, player-prop projections, 3D visual replay, and a physical game simulator have separate contracts and baselines.** A feature may improve one without improving the others. Follow the [contextual full-game spec](SPEC-NFL-CONTEXTUAL-FULL-GAME-SIMULATION-2026-10-25.md) and [situational matrix](research/NFL-SITUATIONAL-RESEARCH-MATRIX-2010-2026.md).

| Gate | Deliverable and required evidence | State at roadmap update |
|---|---|---|
| C0 Source registry | Frozen game IDs and UTC cutoffs; source publication/observation timestamps, GSIS crosswalk, source hash; explicit strict-as-of / retrospective / unavailable class | **Open**; historical schedule versions not proven available in dev |
| C1 Historical inactives | GSIS-verified official game-day inactive labels by game + dated transaction/roster membership, emergency QB3, amended announcements | **Research underway**; name-only 2024 W1–4 sample, no certified final confusion matrix |
| C2 Probabilistic roster | Forecast `P(dressed)` and `P(snap/routes/targets/carries | dressed)` from Q/D/Out + DNP/LP/FP + role, injury and past usage at each pregame horizon | **Not adopted**; old QBI and AVAIL challengers previously failed their respective gates |
| C3 Game state and rules | Season-specific source/target rule regimes, legal blocked kicks, safety kicks, long FGs, overtime/ties, no invalid final games or unexplained errors | **Partial**; 124-item rule-change inventory exists, not certified complete or integrated into active rules |
| C4 Paired simulation and audit | Unconditional S0/S1 and ablations with identical cutoff, engine and legal reference; every seed recorded; replay vs physical model differentiated | **Research 10k completed**, not a fair paired prospective model comparison |
| C5 Forecast comparison | Scores, margins, totals, three-outcome winners, drive/quarter stats and player props graded chronologically against v1 and independent market benchmark after lock | **Open**; single DAL–PHI diagnostic cannot justify promotion |
| C6 Player movement/visual | 22-player trajectories, ball/catch/score sync, fixed-camera video and tracking benchmark versus constant-velocity controls | **Research only**; rendering and physical predictive power not validated |
| C7 Dev → production | Passing source/provenance contracts, CI, frozen default policy, release evidence and independently validated model improvement | **Not automatically authorized** by research completion or a Phase 1 branch merge |

### 7.3 Availability research evidence and exact modeling targets

A recent read-only dev audit counted: `nfl_hist_injuries` **90,752** rows from 2009–2025, `nfl_hist_snap_counts` **324,612** from 2013–2025, `nfl_hist_depth_charts` **552,514** from 2010–2024, `nfl_hist_participation` **478,989** play keys from 2016–2025, and `nfl_hist_ftn_charting` **185,215** from 2022–2025. Do not generalize these local counts to every publisher or future production DB; coverage and publication times require per-field/per-season checks. The 2025 injury rows have no `date_modified` in this archive, and historical depth charts have no preserved as-of publication time.

The first official-inactive exercise covers **64 NFL games, 2024 weeks 1–4**, with **806 official entries vs 812 `INA` rows**. **804** were reconciled by exact name and manual aliases, including **25 emergency third quarterbacks**; two reported `ACT` conflicts and eight `INA`-only rows required third-source adjudication. These are **not GSIS-certified precision/recall or an approved training label set**. A player's `ACT` weekly roster code may mean team roster membership, not that they dressed; `INA` may attach to players already released, on IR or off the game roster. Cases like the late Evan Engram warmup-injury update require announcement **version and timestamp**, not just the latest webpage. Nouili's Week 1 status remains unresolved in the reported local review. Treat `Questionable` and `Doubtful` as empirically different uncertain states; do not apply post-2016 numeric 50%/25% priors. Snapshot `Out`, practice participation, roster membership, health source, and reported status **at the forecast cutoff**.

**Prediction targets:** `P(game_day_dressed)`; `P(role and workload | dressed)`; `P(player_stat | opportunity, context)`; and coherent team score/game outcome. Preserve `emergency_qb3`, `official_inactive`, `not_on_game_roster`, `identity_unresolved`, and `unknown` as separate data labels. Models must support **early-week, practice-update, final report and ~90-minute-before kickoff** horizons and publish updates before the game-day list arrives. Being dressed is not equivalent to playing a snap.

### 7.4 Integrated simulation case and what it does not establish

The DAL–PHI Week 7 integrated research run simulated 10,000 seeds, with **9,820 valid complete untied** (98.20%), **173 guarded/blocked**, **one error**, and **six other complete outcomes requiring a tie-status audit**. S1 averaged DAL **20.8081**, PHI **19.9695**, 40.7776 total. The actual final was **DAL 38, PHI 21**, 59 total; v1 reference totaled 46.3261. This is a reason to inspect **upper-tail scoring, drive efficiency, quarter state, players and lineups**, not a reason to insert bookmaker scoring priors or retune one game. The 10k output froze **after kickoff** and authentic schedule versions were unverified, so the result is an exploratory engineering milestone, **not an available-before-kickoff forecast**.

The original S0 had 7,993 valid games and first S1 had 8,825. Different code/reference digests mean the apparent coverage improvement is **not** an isolated context treatment effect. An identical seed integer does not guarantee paired randomness after input-digest rekeying. Preserve a **per-seed ledger**, rule regime, blocker reason, result and hashes, and compare S0/S1 under one engine before claiming uplift. Remaining guarded groups in the integrated run were **105 blocked kicks/recovery paths, 45 extremely long-FG thin cells, 23 safety-free-kick paths**; open player stats/OT and run validity gates separately from prediction calibration.

### 7.5 Broader context program and physics boundaries

Research **weekday (including Monday), kickoff hour, team record and quality, rest/bye, travel, divisional rematches, coaching, Q1/Q4 score state, team and opponent style, quarterback replacement, line/secondary injuries, roof, turf/grass, weather forecast, elevation, officials and special teams**. The NFL schedule includes date/time/stadium/roof/surface/referee, and historical `load_officials()` can provide full crews where its annual data are complete; attendance and TV need outside sources. Use controlled estimates and shrink sparse cells. Raw within-team turf or Monday differences are not causal conclusions.

The [rule registry](research/NFL-RULE-REGIME-REGISTRY-2010-2026.json) tracks **124 identified adopted-rule records for 2010–2026**, including experiments and 2026 conditional exceptions, but **is not fully article-diff-certified**. Select legal events by target regime before statistical sampling; don't infer equivalent laws or outcome distributions from non-significant p-values.

The Gridiron Physics 3D replay remains **distinct from the statistical game outcome model**. Video review exposed crowding, targeting, animation/ball possession and touchdown-timing questions. Correct playback must visually correspond to a sampled scoring event; physical motion forecasting needs its own independent tracking, contact, acceleration and ball-ownership evaluation. It must not be labeled a predictive physical mechanism merely because the animation resembles a football play.

### 7.6 Revised sequencing and ownership for agents

1. **Data/provenance:** official inactive list GSIS join and versions, dated transactions, schedule versions, roster eligibility and feature source manifests (plus coverage/rights).
2. **Player opportunity models:** multi-horizon dressing probability, conditional snap/routes/carry/target share, plausible replacement lineups and coherent player-team stats; evaluate against the previous non-adopted QBI/AVAIL definitions.
3. **Legal simulation:** seasonal rules resolver, remaining blocked outcomes, exact game/tie accounting, per-seed audit and reproducible fixed-default control.
4. **Predictive ablations:** match S0/S1/v1 input cutoffs and test chronological scores, margin/total distribution, Brier/log loss, prop CRPS and player usage; no market input contamination.
5. **Context expansion:** measured opportunity-level weekday/rest/venue/officials/QB/injury/quarter effects; preserve failures and nulls.
6. **Product + broader leagues:** publish early-to-final forecast updates with source/timestamp and uncertainty, public grading, playoffs; reuse contracts for NCAAF/NBA/NHL/tennis without forcing NFL rules onto them.

A Phase 1 merge to `dev` is an engineering integration, not a claim of predictive adoption or production deployment. Unverified official inactive labels, full historic rulebook reconciliation and complete as-of provenance remain gates that cannot be satisfied by documentation alone. **Maintain distinct statuses: built / local-tested / pushed / merged-to-dev / deployed / prospectively-validated.**
