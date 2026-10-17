# SPEC: NFL Pregame Play-Sequence Generator v1

Status: proposed, not implemented. Owner: Legendary Picks. Target: Gridiron Physics pregame entertainment simulation. Contract: [GRIDIRON-CONTRACT-v1.md](GRIDIRON-CONTRACT-v1.md).

## Product goal

Given an **upcoming NFL matchup** and a frozen pre-kickoff snapshot, generate a complete, **hypothetical** football game as a chronological sequence of plays. Each sampled decision and outcome changes the next state. Publish the resulting play script and aggregate game/player stats so Gridiron Physics can animate the game *before the actual game occurs*.

The product is an engaging, coherent, repeatable animated simulation, **not** a claim of market-beating Brier or a prediction of the exact future sequence. Historical games train and validate the generator; browsing historical games or branching off actual plays is explicitly out of scope for v1.

### Repository boundaries

- **LP owns:** data selection and as-of provenance, pregame snapshots, state/rules reducer, trained statistical play decisions and outcomes, player selection, random seeds, generated play logs, stats and API/CLI.
- **Gridiron owns:** roster/ID enrichment for physics, formations/assignments, 0–99 player ratings and physical parameters, animation, cameras, replay, game playback, user experience.
- **Contract owns:** identifiers, situation/outcome schema and explicit provenance. Both repos maintain identical v1 contract docs and fixtures.
- The existing LP game score distribution, NFL v1/v2/Elo and player forecasts can inform prior team strength and role/pace parameters, but **must never supply a fixed final score that the generated game is forced to achieve**.

## Existing inputs to reuse, with caveats

- `backend/ingest_nfl_pbp_logs.py` defines the curated `nfl_pbp` table, keyed by `(game_id, play_id)`; historical REG seasons 2010–2025 have been backfilled in the dev research workflow. The code lists `down`, `ydstogo`, `yardline_100`, `game_seconds_remaining`, `play_type`, `yards_gained`, `pass_attempt`, `rush_attempt`, participants, `qb_dropback`, `qb_scramble`, `no_huddle`, `xpass` and `pass_oe`. **Listing a column in code is not proof of physical table population or coverage**. Audit `PRAGMA table_info`, per-season NULL rates and source checksums first.
- `nfl_pbp` does **not** provide reliable all-22 per-snap lineups, complete routes or defensive coverage calls. Gridiron must mark these as reconstructed/author-defined, not observed.
- The play dataset does not provide a full, trusted preplay score/timeouts/penalty/turnover schema yet; reconstruct or import these with explicit tests before relying on them.
- `nfl_ratings.py`, `nfl_score_dist.py`, `nfl_sim.py` and the adjacent Elo/score-simulation work are pregame context and evaluation baselines, not play-script generators.
- Gridiron ratings are **not** ground-truth tracking measurements. If LP later consumes these attributes, version the as-of snapshot and treat them as experimental features.

## M0: Snapshot and training audit

Write a data coverage report for 2010–2026 by season and event type. Pin source artifacts/checksums and player-identity mappings. Define exactly which fields are available at forecast time; never train preplay decisions using current-play yards, EPA, WPA, success, outcome or post-play score. In particular, externally fitted `xpass`, `pass_oe`, `cpoe`, `epa` and `wpa` may encode model-fitted future data: **do not use them as causal/as-of features without independently verified chronological fits**. They can be audit labels or separately identified challengers.

A `pregame_snapshot` freezes schedule, home/away, forecast as-of UTC, roster and projected starters, inactives/availability as known then, team strength, play pace, role shares and rules version. Missing/unverifiable fields are null with provenance; never silently replace them with postgame observed starters or participants. The historical replay reconstruction can use additional outcome knowledge, but the pregame generator cannot.

## M1: Deterministic NFL state reducer

Implement `State -> (Action, SampledOutcome) -> NextState` separately from all learned models.

State includes: season/ruleset, period and clock remaining in period, offense, defense, home/away scores, possession, down, yards to gain, offense-relative `yardline_100`, timeouts, current drive, and accumulated team/player stats. Drive starts, kickoffs, extra points/2pt, punts, field goals, turnovers, sacks, incompletions, penalties, safeties, halftime and overtime must have explicit transition paths or **conspicuously marked, tested approximations**. A runaway/invalid simulation fails; it never receives a fabricated final score.

Use real recorded events to test state transitions against known score/possession/down progression **before** generating hypothetical events. Team offense-relative `yardline_100` is the canonical coordinate, not an absolute x coordinate.

## M2: Train baseline probabilistic generator

Develop simple, regularized, auditable distributions before more ambitious models. Each stage is conditional on state and previous sampled stages:

1. Legal decision / play call: rush, dropback, kneel, punt, field goal and other legal actions; stratify by score, clock, distance, field position, team tendency and opponent.
2. Dropback branch: sack vs scramble vs pass attempt, then target/air-depth, complete/incomplete/interception; conditional receiving YAC. A sack is not an attempt; a scramble is an outcome of a dropback.
3. Designed-rush branch: rusher and signed gain with long-tail/negative-gain handling.
4. Defense interaction: opponent/defense pressure and coverage-quality latent/context features at minimum. Charted Cover-2/Man/Blitz labels are **not in canonical PBP**, so do not present concept-specific learned odds without approved charting.
5. Participant distribution: pregame available QB, receiver/target and rusher probabilities, based on projected role shares and eligible roster, not the player who led the completed game's attempts.
6. Tempo: between-snap duration, live-ball duration and clock-stopping logic, conditioned on game situation.
7. Special teams, fumbles, penalties, and rare events: separate conservative baseline distributions with explicit coverage/approximation reporting.

The output is **a drawn event**, not merely a marginal score probability. A generated play with a completion updates QB attempts/completions/pass yards and receiver targets/receptions/receiving yards consistently. No separately drawn totals may conflict with the play log.

## M3: Generate a complete prospective game

Entry point (proposed): `python -m backend.nfl_sequence.generate --game-id <scheduled-game-id> --as-of <UTC> --seed <int> --output <path>`.

Use a deterministic PRNG whose seed is derived from game ID, pregame snapshot hash, model version and trial index. Keep statistical outcome randomness independent from Gridiron's physics-seed streams. Each valid game must reach a legal final through its own possessions, decisions and transitions. Save complete chronological plays and a derived stat summary, never impose LP's separately modeled predicted final score.

For 3D playback, produce one full high-detail event script per selected trial. For thousands of trials, emit compact stats/events summaries without animation frames. Future `simulate-batch` aggregation is optional after single-game v1 works.

## Output and service

Implement the **shared v1 schema**:
- `GET /api/gridiron/v1/upcoming-games`: game catalog with stable IDs and kickoff times.
- `POST /api/gridiron/v1/simulations`: pregame game ID/as-of/seed -> generated simulation or job reference.
- `GET /api/gridiron/v1/simulations/{id}`: complete, immutable ordered script, roster refs, model/version/seed and summary.

These are proposed endpoint shapes; v1 may use offline CLI + versioned JSON fixtures before adding an HTTP backend. Return status/errors explicitly for missing pregame roster or an unsupported rules event. Do not provide a fictional success payload.

## Delivery gates

- **A1:** Generate the same complete simulation bit-for-bit from the same version, snapshot and seed; different seeds produce demonstrably varied drives and outcomes.
- **A2:** Every play has a valid before/after state; game clock, possession, score and player stats reconcile. Zero silent fallback final scores or postgame leakage.
- **A3:** Generated games exhibit credible ranges of plays, drives, QB dropbacks/attempts, penalties, scoring, turnovers and clock usage on held-out historical regimes. Report defects rather than hiding them behind plausible final scores.
- **A4:** Generate full scripts for at least two upcoming matchups using distinct pregame snapshots; both pass schema validation and Gridiron's adapter.
- **A5:** Publish observational labels: **historical training**, **learned model output**, **estimated participants/coverage**, and **physics-generated motion**. No generated play is presented as actual NFL PBP.

For entertainment v1, acceptance is coherent, varied, legally valid complete games and successful 3D playback. Forecast accuracy remains a later, separate model-evaluation track; don't block a clearly labeled entertainment simulation on sportsbook Brier.

## Not v1

Historical game browsing; “What If From Here”; user-called plays or branching after a live snap; validated autonomous physics deciding winners; betting signals; head-impact claims; licensed coverage recognition. Preserve the current Film Room and Slant What If experiment, but they are **not dependencies** for the pregame game-simulation release.

## First implementation handoff

1. Commit the data/feature audit and as-of input contract without changing production ingests.
2. Implement/replay-test the rules reducer, including special-teams/clock transitions.
3. Train a small conditional event baseline and stitch into a complete seeded game.
4. Export two distinct prospective-game scripts following the shared contract and hand to Gridiron.
5. Instrument why generated games look wrong (possessions, penalties, play counts, QB attempts, missing player refs); repair at the responsible stage rather than constraining the final result.

No production route, scheduled ingest, default NFL forecast, or live DB migration should change during these research milestones.
