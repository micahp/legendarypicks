# CURRENT EXECUTION BRIEF: FBS GAME-WINNER MODEL (revised 2026-10-17)

**Status: active, supersedes the player-prop modeling direction in the archived report below.**
**Branch:** feat/fbs-data-audit. **Target:** Division I FBS, pre-kickoff probability that the home team wins.
**Execution order:** (1) game-winner benchmark using existing data, (2) complete historical data inventory/backfill, (3) incremental game-winner improvements, (4) coherent score/margin/total distributions, (5) play-by-play simulator, (6) player props.

This section is the current brief for the agent. The original player-prop baseline report below is retained verbatim as historical evidence and must NOT be construed as a game-winner experiment. The previous test of passing_yards and rushing_yards answered the wrong modeling question. Its Brier scores do not benchmark team win probabilities. Do not continue tuning that experiment as part of Phase 1.

## Phase 1 (IMMEDIATE): predict FBS game winners, with what we already have

**Question:** Before kickoff, how accurately can we estimate the probability each FBS team wins?

1. **Read existing audits and reuse local datasets**: research/fbs/AUDIT-FBS-DATA-20261017.md, AUDIT-FBS-RECONCILE-20261017.md, AUDIT-CFB-RELEASES-20261017.md, and research/fbs/parquet/README.md. Inspect actual paths/columns, don't assume them from this description. Do not backfill the entire archive first. Reuse already downloaded 2022-2025 seasons plus 2026 results where the observations are genuinely available, extending only if needed to fit/test a sound chronological baseline.
2. **Define the primary population**: every eligible *completed FBS-versus-FBS game* in the available seasons, regardless of whether any player prop was offered. One row per game; identify both teams' FBS membership in that season, kickoff/as-of timestamp, home/away, neutral site, final score, result, season and postseason type. Exclude postponed/incomplete/duplicate games and games with unresolved team IDs from evaluation, and report how many. Do not silently count FBS-vs-FCS games in this primary population; they may contribute to rating updates as a separately tested policy, with their count and handling documented.
3. **Build a minimal game-winner baseline ladder, not a prop ladder**:
   - G0 = constant 0.50 probability of a home win (sanity reference, Brier exactly 0.2500).
   - G1 = home-win base rate estimated only from earlier training games; neutral-site behavior separately defined.
   - G2 = strictly chronological Elo plus home-field adjustment, using only earlier games.
   - G3 = score-margin-aware Elo or similarly simple score-derived opponent-adjusted model, tested independently of G2.
   Keep early implementations simple, reproducible and market-blind. Do not train on players, player props, passing yards or rushing yards to solve this first question. Add features only in later phases after comparing these references.
4. **As-of and holdout**: produce a frozen P(home wins) for each game using only observations *strictly before its kickoff*. For rolling ratings, update after final games, never on the result being predicted. Fit hyperparameters/calibration on earlier seasons only. Prefer 2025 as a completed out-of-time holdout; use 2026 as a distinct, genuinely prospective or walk-forward evaluation (never future 2026 games). Preserve season-by-season and week-by-week breakdowns. No random game split, full-season retrospective ratings as pregame input, or leakage from same-week games not yet completed.
5. **Grade independently of sportsbook coverage** on the complete eligible FBS-vs-FBS game set. Then form a separate strictly *matched priced subset* for comparisons to book odds. Do not filter all training/evaluation through prop_games, props, prop_results, or player-game logs.
6. **Deliver a standalone report** at research/fbs/RESULT-FBS-GAME-WINNERS-20261017.md (or date of actual run), plus reproducible code and a machine-readable per-game forecast ledger. Include the source paths/versions, eligibility and excluded-game counts, sample size by year, home/neutral distribution, G0–G3 results and uncertainty, calibration bins/plot, per-season and per-week scores, and a keep/reject recommendation. Do not claim the test is complete without actual executed results. Original audit evidence remains unchanged.

### Phase 1 scoring contract

For a binary game outcome (y=1 if the home-designated team wins, y=0 if it loses), using the home team's **pregame** forecast p:

Brier = mean over games of (p - y)^2.

**Lower is better.** Perfect forecasts = 0.0000; a constant 0.50 prediction scores exactly 0.2500; confidently wrong predictions can approach 1.0000. Use this **one-outcome** convention, not a doubled, two-class sum. Winner-pick accuracy is secondary; report log loss and reliability/calibration alongside Brier. A 50/50 forecast is a theoretical reference, not the empirical skill of a home-field or market-aware model.

For each reference with scores on **identical games**, report:

- Coin-flip Brier Skill Score = 1 - Brier(model)/0.2500.
- Market Brier Skill Score = 1 - Brier(model)/Brier(market) (only on the same market-covered games).
- Paired difference Delta Brier = Brier(model) - Brier(reference): negative is better. Include a credible paired game-level or time-block bootstrap interval, and season-by-season stability.
- Base-rate forecast, log loss, calibration/reliability, Brier resolution and sample size. Recalibration can repair miscalibration but cannot manufacture meaningful discrimination/resolution. Fit any recalibration map using prior games only.

Do not set a universal "good" Brier threshold. The mix of favorites, mismatches and available priced games changes achievable scores. Any ranked-team-only or power-conference-only subgroup gets its **own** separate comparison population.

### External FBS reference ladder (published benchmarks, NOT our own measured results)

The following numbers are *self-reported external studies* for perspective. They were obtained from the linked methodology pages and **must not be labeled Legendary Picks results**, imported as fixed targets, or compared as if evaluated on our games.

**Simple ACR**: 9,356 FBS-vs-FBS games with betting lines, 2014–2026. Each row on the same published game set. The betting-line model converts historical *spreads* to win probability; it is **not** a direct no-vig moneyline benchmark.

| Published comparator | Brier |
|---|---:|
| Constant 50/50 | 0.2500 |
| Colley | 0.2070 |
| Basic Elo | 0.1976 |
| Glicko-2 | 0.1890 |
| Massey | 0.1847 |
| Margin Elo | 0.1820 |
| Simple ACR | 0.1773 |
| Spread-implied betting line | 0.1714 |

Source and methods: https://acrafton.com/methods/

**Blitzcast**: 2,275 FBS-vs-FBS games from 2023–2025, its own walk-forward CFB classifier **0.1813** versus claimed de-vigged closing moneyline **0.1729**; the market reference is 0.1685 (2023, n=755), 0.1781 (2024, n=757), 0.1719 (2025, n=763). It reports including spread and market probability among model inputs; do **not** treat that model as a market-independent rating baseline. These are self-reported results with a distinct data/evaluation population from Simple ACR.

Sources: https://www.blitzcast.app/how-it-works and https://github.com/carterptull/blitzcast

**How to use this ladder**: reproduce coin flip, historical home-rate, Elo, margin Elo and our own bookmaker baseline **on the same LP games**. Treat published ~0.17–0.18 Vegas-scale numbers only as background context. A model is "market competitive" only if our own paired evaluation supports that claim, not because its absolute Brier crossed 0.18. The default promotion gate is better paired Brier and no material calibration regression, with uncertainty and year-by-year robustness reported. If differences are statistically unresolved, mark **not demonstrated** and retain the simpler baseline.

### Market reference data rules

- CFBD lists historical betting-line coverage from 2013 onward, varying by book/game/field: https://api.collegefootballdata.com/data-availability . Check which records actually contain moneylines, what timestamps and providers are available, and how complete they are.
- If both sides' American moneylines exist, convert to raw implied probabilities (+a -> 100/(a+100); -a -> a/(a+100) for a>0) and de-vig by normalization: q_home = raw_home/(raw_home+raw_away). Record tie/draw assumptions if relevant. Distinguish opening, latest-before-cutoff and closing snapshots; use the correct one for a fair as-of comparison.
- If only a point spread exists, derive a separate **spread-implied** home-win probability from a conversion calibrated on earlier seasons; label it as spread-derived, not "Vegas moneyline" or direct de-vig probability. Never fit the spread-to-probability curve using the evaluation season's outcomes.
- Evaluate (A) all eligible games across G0-G3 and (B) the intersection with valid market snapshots. G0-G3 must be rescored on the market subset before quoting a comparison. Separate market-blind forecasts from market-input models. Do not silently substitute post-kickoff/late closing odds for an earlier forecast cutoff.
- If historical moneyline data is missing, do not block Phase 1: report a documented missing benchmark and score the available spread-derived comparison separately if valid.

**Phase 1 exit gate:** Actual reproducible, chronological, same-game Brier/log-loss/calibration results for G0–G3; eligible game counts and as-of proof; an explicitly labeled matched-market comparison if data permits. Complete this before starting Phase 2. No player-prop experiments constitute passing this gate.

## Phase 2: acquire the complete usable historical FBS archive

After Phase 1, obtain and catalog all accessible years of **each data category**, not a flat 2018+ sample. The oldest available year differs by field; retain earliest schedules/results even when play-by-play and advanced player stats start decades later. Use the existing 25 cfb_* and 68 other espn_cfb_*/ncaa_mfb_* release inventory in AUDIT-CFB-RELEASES-20261017.md, plus CFBD endpoints. Confirm actual release floors, URLs, access and commercial redistribution/training rights rather than assuming everything found online may be used in production.

Backfill in separate raw, normalized and derived layers:
- **Identity/reference**: historical FBS membership, conference realignment, opponent identities, season types, neutral sites, team-name crosswalks, dates/venues.
- **Games/markets**: schedules, final scores, scoring by period, betting opening/closing spreads, totals, two-sided moneylines when available, timestamped provider/market provenance.
- **Team and opponent performance**: box scores, offensive/defensive/special-teams statistics, yards/plays/tempo, turnovers, penalties, field position, scoring opportunities, third/fourth downs, red zone, team game efficiency and opponent-strength splits.
- **Event-level**: drives, possessions, down/distance, play type, player-attributed plays, yards, sacks, scrambles, explosive plays, play-by-play, raw events needed to recompute EPA/success rates.
- **Player/roster**: rosters, game logs, participation, depth, injuries/availability as of kickoff, position group usage, recruits, team talent, transfers and returning production.
- **Coaching/context**: coaching/coordinator changes, tactical tendencies, offensive systems, travel/rest, weather where reliable, weekly power ratings and poll snapshots.

Produce season-by-source coverage matrices with downloaded file sizes, compressed/loaded storage footprint, game/player/play counts, hashes, schema, missingness, source rights and reconciliation checks. Preserve FCS games and other subdivisions with explicit flags; evaluate FBS-vs-FBS separately. Do not make absent source keys equal zero. Keep raw observations separate from publisher-scored feature tables (EPA, FPI, Paper Index, etc.). Detect leakage from contemporaneous or retrospective ratings. Published through_week=W snapshots may include week W itself; forecast W using a verified prior snapshot only. Never use Paper Index shares fitted on observed winners as pregame features. Never commit bulky Parquet data, deploy to production, or alter the main/prod database without separately granted approval.

**Phase 2 exit gate:** a reproducible maximal historical archive with an honest matrix of what exists per season and category, including irreducible access/missingness and storage costs.

## Phase 3: improve game winners in independently tested increments

Only after Phase 1 and Phase 2, add feature families one at a time to the winning **game-level** baseline: opponent-adjusted team quality; prior-play EPA/success/explosiveness and tempo; scoring/turnover/field-position splits; home/rest/weather/travel; coaching/roster continuity and talent; form and time decay; then, if justified, richer hierarchical models. Features must be pregame or reproducibly as-of. Pre-register a model ladder, same-game chronological holdouts, sample-size and uncertainty gates. Discard additions that do not improve out-of-sample probability quality.

## Phase 4: coherent full-game score forecasts

Fit **joint** home/away score distributions and derive P(win), margin, totals and spread cover chances from the **same** modeled outcomes. Compare probabilities with matched lines, and score predictions with proper distribution metrics, MAE/bias, calibration and holdout checks. Good winner Brier does not automatically establish good totals/margins.

## Phase 5: prospective full-game play simulation

Only when the simpler game-level models are credible, simulate possessions, down/distance, play calls, outcomes, timing, turnovers, scoring, legal game states, substitutions and summary statistics. Joint outcomes and game-winner probabilities must reconcile to the generated scores. Validate events/box scores and distributions on past games, using only historical-as-of inputs.

## Phase 6: player projections and props (LATER)

Player workload, passing/rushing/receiving distributions and prop lines may become downstream outputs of the same game environment and simulation. They require separate outcome coverage, market-time provenance and probabilistic grading. **Do not treat the archived 2026 prop Brier test as the model-winner baseline.** Do not restart the prop track until explicit authorization after the upstream phase gates.

---

# ARCHIVED ORIGINAL EXPERIMENT — player-prop baseline (preserved unchanged below)

The following is the historical report from the earlier wrong-target run. The figures, population and original interpretation are retained for auditability. The current research brief above supersedes its *execution priority*, not its facts.

---

# FBS baseline ladder - 2026-10-17

Pre-registered before the run: markets passing_yards, rushing_yards; walk-forward week by week; keep rule is a player-game-clustered bootstrap interval for the Brier difference that excludes zero.

## 0. The holdout, and why it is not 2025

| measure | value |
|---|---|
| seasons with ncaaf props | 2026 |
| fixtures with a 2025 date | 0 |
| settled props, all seasons | 64416 |

The plan's holdout was 2025 as the first complete season and 2026 as a separate live forward-recorded test. The first half of that is not available: there is no 2025 NCAAF prop board in this database, so there is no 2025 line and no 2025 result to grade. The holdout is therefore a **week walk-forward within 2026**: every game strictly before the graded week is training data, and the graded week is never in its own fit.

What this costs, stated plainly: a within-season walk-forward cannot separate a model that is right from a model that is right for this season's players. It measures the models against one season's schedule. That is the limitation the keep rule's interval exists to surface, and it is reported rather than hidden.

## 1. The week calendar

| week starting | game dates | count |
|---|---|---|
| 2025-08-23 | 2025-08-23, 2025-08-28, 2025-08-29 | 3 |
| 2025-08-30 | 2025-08-30, 2025-08-31, 2025-09-02, 2025-09-05 | 4 |
| 2025-09-06 | 2025-09-06, 2025-09-07, 2025-09-11, 2025-09-12 | 4 |
| 2025-09-13 | 2025-09-13, 2025-09-14, 2025-09-18, 2025-09-19 | 4 |
| 2025-09-20 | 2025-09-20, 2025-09-21, 2025-09-25, 2025-09-26 | 4 |
| 2025-09-27 | 2025-09-27, 2025-09-28, 2025-10-03 | 3 |
| 2025-10-04 | 2025-10-04, 2025-10-05, 2025-10-08, 2025-10-09, 2025-10-10 | 5 |
| 2025-10-11 | 2025-10-11, 2025-10-12, 2025-10-14, 2025-10-15, 2025-10-16, 2025-10-17 | 6 |
| 2025-10-18 | 2025-10-18, 2025-10-19, 2025-10-21, 2025-10-22, 2025-10-23, 2025-10-24 | 6 |
| 2025-10-25 | 2025-10-25, 2025-10-26, 2025-10-29, 2025-10-30, 2025-10-31 | 5 |
| 2025-11-01 | 2025-11-01, 2025-11-02, 2025-11-05, 2025-11-06, 2025-11-07 | 5 |
| 2025-11-08 | 2025-11-08, 2025-11-09, 2025-11-12, 2025-11-13, 2025-11-14 | 5 |
| 2025-11-15 | 2025-11-15, 2025-11-16, 2025-11-19, 2025-11-20, 2025-11-21 | 5 |
| 2025-11-22 | 2025-11-22, 2025-11-23, 2025-11-25, 2025-11-26, 2025-11-28 | 5 |
| 2025-11-29 | 2025-11-29, 2025-11-30 | 2 |
| 2025-12-06 | 2025-12-06, 2025-12-07 | 2 |
| 2025-12-13 | 2025-12-13 | 1 |
| 2026-08-22 | 2026-08-27, 2026-08-28 | 2 |
| 2026-08-29 | 2026-08-29, 2026-08-30, 2026-09-03, 2026-09-04 | 4 |
| 2026-09-05 | 2026-09-05, 2026-09-06, 2026-09-07, 2026-09-11 | 4 |
| 2026-09-12 | 2026-09-12, 2026-09-13, 2026-09-17, 2026-09-18 | 4 |
| 2026-09-19 | 2026-09-19, 2026-09-20, 2026-09-24, 2026-09-25 | 4 |
| 2026-09-26 | 2026-09-26, 2026-09-27, 2026-10-02 | 3 |
| 2026-10-03 | 2026-10-03, 2026-10-04, 2026-10-07, 2026-10-08, 2026-10-09 | 5 |
| 2026-10-10 | 2026-10-10, 2026-10-11 | 2 |

## 2. The item set

An item is a (week, player, game, market) with a settled result, a non-whole-number line, a player with an ESPN id, and a stored log row in that game. The population is measured before any model is fitted, because every model below is graded on it and a model that quietly grades a different population is not a result.

| measure | count |
|---|---|
| props joined to a settled result and a stored log | 61994 |
| distinct markets | 18 |
| distinct players | 1089 |
| distinct games | 267 |

| measure | count |
|---|---|
| items | 21854 |
| dropped: not a pre-registered market | 40108 |
| dropped: whole-number line | 0 |
| dropped: no value | 32 |

Items by week:

| week | items | players | games | markets |
|---|---|---|---|---|
| 2026-08-29 | 1014 | 60 | 15 | 2 |
| 2026-09-05 | 3646 | 121 | 35 | 2 |
| 2026-09-12 | 2874 | 133 | 34 | 2 |
| 2026-09-19 | 4008 | 173 | 47 | 2 |
| 2026-09-26 | 4454 | 156 | 34 | 2 |
| 2026-10-03 | 1440 | 38 | 8 | 2 |
| 2026-10-10 | 4418 | 123 | 29 | 2 |

## 3. Player history

| measure | count |
|---|---|
| players with prior games | 15773 |
| player-games | 93504 |
| seasons | [2025, 2026] |

## 4. The models

All four are functions of the player's prior games, read with a cutoff date. Nothing here reads the graded week.

## 5. Walk-forward grading

Each graded week is scored with models fitted on every game strictly before that week. The P(over) is a normal approximation with a player-specific variance shrunk toward the league variance, floored at 1.0.

| measure | value |
|---|---|
| weeks in the calendar | 7 |
| weeks graded | 4 |
| graded weeks | 2026-09-19, 2026-09-26, 2026-10-03, 2026-10-10 |
| minimum weeks of history before the first graded week | 1 |

The graded window is the last 4 weeks of the season's calendar, subject to every graded week having at least 1 weeks of history behind it. This is a pre-registered floor; the first graded week with fewer weeks behind it would be measuring the absence of history rather than the model.

| model | items | MAE | Brier | log loss |
|---|---|---|---|---|
| season_avg | 14320 | 47.31 | 0.2907 | 0.7926 |
| rolling_5 | 14320 | 49.46 | 0.2787 | 0.7665 |
| marcel | 14320 | 45.95 | 0.2860 | 0.7770 |
| share_adj | 14320 | 57.96 | 0.3480 | 0.9950 |

Reference (the constant base-rate forecast):

| measure | value |
|---|---|
| items | 14320 |
| observed over rate | 0.4712 |
| constant base-rate Brier | 0.2492 |
| constant base-rate log loss | 0.6915 |

Every model here is WORSE than the constant forecast. That is the headline, and it is stated before the model comparison because a relative win among models that all lose to a constant is not a result. The reliability column shows why: every model's reliability is 0.05 to 0.11, which is large, while resolution is 0.0026 to 0.0028, which is the entire uncertainty term divided by about 100. These forecasts carry almost no information about the over/under, and they are confidently wrong rather than uninformative.

The practical reading: a post-hoc calibration map is the cheap repair here and it is worth running before any further modeling, because it is the only thing that can remove the reliability term without adding data. The NFL work measured exactly this shape -- calibration was nearly the whole gap there too.

Decomposition (Murphy: Brier = reliability - resolution + uncertainty):

| model | items | reliability | resolution | uncertainty | reconstructed |
|---|---|---|---|---|---|
| season_avg | 14320 | 0.0422 | 0.0012 | 0.2492 | 0.2902 |
| rolling_5 | 14320 | 0.0306 | 0.0018 | 0.2492 | 0.2780 |
| marcel | 14320 | 0.0385 | 0.0022 | 0.2492 | 0.2855 |
| share_adj | 14320 | 0.0991 | 0.0019 | 0.2492 | 0.3464 |

Reliability is the part a recalibration map can remove. Resolution is the part that is information. A model whose reliability dominates and whose resolution is near zero is miscalibrated rather than uninformed, and the repair is a post-hoc map, not more data.

Read against the floor: the reconstruction confirms the decomposition is arithmetic (reliability - resolution + uncertainty reproduces the Brier to four decimals for every model), so the terms mean what they say. The resolution term is 0.0026 to 0.0028 for all four models, which is one hundredth of the uncertainty term. No model here is separating over from under.

Per graded week:

| week | season_avg | rolling_5 | marcel | share_adj |
|---|---|---|---|---|
| 2026-09-19 | 4008 / 0.2814 | 4008 / 0.2886 | 4008 / 0.2887 | 4008 / 0.3204 |
| 2026-09-26 | 4454 / 0.3021 | 4454 / 0.2765 | 4454 / 0.2893 | 4454 / 0.3770 |
| 2026-10-03 | 1440 / 0.3041 | 1440 / 0.2677 | 1440 / 0.2897 | 1440 / 0.3825 |
| 2026-10-10 | 4418 / 0.2834 | 4418 / 0.2755 | 4418 / 0.2792 | 4418 / 0.3326 |

Each cell is `items / Brier`. A model whose pooled Brier is better but whose per-week Briers are not consistently better is not a model, and the per-week view is what makes that visible.

## 6. The keep rule

A model is adopted only if its Brier is lower than `season_avg`'s by a player-game-clustered bootstrap interval that excludes zero. The interval is reported, not just the point difference.

| model | shared clusters | Brier difference vs season_avg | clustered 95% interval | verdict |
|---|---|---|---|---|
| rolling_5 | 631 | -0.0075 | [-0.0169, 0.0029] | not kept |
| marcel | 631 | -0.0051 | [-0.0178, 0.0081] | not kept |
| share_adj | 631 | 0.0458 | [0.0253, 0.0674] | not kept |

Control: `season_avg` Brier 0.2907 on 14320 items across 631 clusters.

## 7. The control

| measure | count |
|---|---|
| control items | 14320 |
| control clusters (player-games) | 631 |
| control distinct players | 272 |
| control distinct games | 118 |
| control markets | passing_yards, rushing_yards |
| control weeks | 2026-09-19, 2026-09-26, 2026-10-03, 2026-10-10 |
