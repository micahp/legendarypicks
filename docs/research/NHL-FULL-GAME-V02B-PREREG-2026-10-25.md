# NHL Full-Game v0.2b: Preregistration and Evaluation Protocol

Date: 2026-10-25  
Branch: `research/nhl-game-state-v02b-2026-10-25`  
Frozen parent: alpha2 commit `888a956734e4066f124d06f65cefbc0dcd84fa75`

## Purpose and scope

This is a research-only continuation of the frozen v0.2 alpha2 simulator. It tests whether
game-state consistency and live-state-conditioned event transitions improve the development
simulation. It does not authorize selection for production, changes to NHL forecasts, edits to
frozen v0.1/alpha2 artifacts, or Gridiron integration.

The alpha2 implementation remains the comparison point. All new code and outputs use versioned
v0.2b paths. Historical databases are read-only; raw archives stay outside Git.

## The two implementation questions

1. **Does this code need to exist?** A bounded state-transition layer is needed to test whether a
   simulated faceoff, penalty, or goalie change causally affects later events. The current donor
   sequence cannot answer that. The new layer will be omitted if it cannot be tested against
   observed source sequences and generated-game invariants.
2. **Does this value need to be computed?** Official NHL GameCenter play-by-play and box scores
   publish historical events, goals, shots, and player game totals; those remain copied and
   verified source facts. They do not publish continuous possession or tactical intent. Those
   states will be explicitly labeled latent model states inferred from earlier training play-by-
   play, never observed target-game labels.

## Data and leakage boundary

- Training source population: eligible 2019 and 2020 start-season games in the frozen v0.1 corpus.
- Development population: all eligible 2021 start-season games in that corpus, expected 1,292 of
  1,312 listed. The evaluation script must reproduce the exact eligible keys and quarantine
  reasons from the frozen v0.1 loader before scoring.
- The verified 2021 GameCenter box score has player IDs and `playerByGameStats` for 1,292/1,292
  eligible games in the measured archive. These fields are evaluation labels only for the target
  game. A target game's participants, starter flags, shifts, scores, and event outcomes must not
  enter its pregame snapshot.
- For each 2021 target, historical team/player summaries may use only eligible source games with
  game date strictly earlier than the target date. Start from the 2019/2020 training pool and
  update forward through prior 2021 games. Same-day games are excluded unless a reliable scheduled
  start ordering and source publication cutoff can be proven; this protocol excludes them.
- Do not use the current 2026/27 roster database or 2026 B3 forecast ledger for 2021. The local
  NHL `player_game_logs` and `roster_snapshots` tables do not cover 2021. The historical adapter
  must be constructed from the independently hashed local GameCenter PBP/box-score archive.
- Read-only inventory of every relevant NHL source table in both Legendary Picks databases was
  completed before implementation. On `picks.dev.db`, the stored NHL rows include: 48,017 2026
  regular-season player-game logs over 1,312 games (2025-10-07 through 2026-04-16); 3,126 2026
  postseason rows over 82 games; 3,584 2027 player-game rows over 94 games (2026-09-29 through
  2026-10-13); 2,624 2026 team-result rows over 1,312 games and 188 2027 team-result rows over 94
  games; matching team-game-stat row counts; and NHL `player_stats` season aggregates for seasons
  2026 and 2027 (1,038 and 790 player IDs). `player_game_logs_sportsdataverse` has no NHL rows.
  `game_summaries` has 171 NHL rows fetched 2026-10-04 through 2026-10-25; these are not a 2021
  historical corpus. NHL roster snapshot headers are season 2027 only. In `picks.db`, the same
  2025/26 coverage is present; the current-season snapshot contains 96 games / 3,660 player rows,
  192 team-result/stat rows, and 790 player aggregate IDs. These counts describe the two queried
  local database snapshots, not all NHL data available elsewhere. Queries used read-only SQLite
  connections; no database was changed.
- For prospective 2026/27 snapshots, use the existing ingested NHL GameCenter player/team rows,
  roster membership and forecast ledger only when their game date, ingest/publication timestamp,
  and feature cutoff all precede the simulated puck drop. The 2026/27 rows stop at 2026-10-13 in the
  measured DB snapshots; they do not include later target results. The 2026 season aggregates and
  logs are prior-season evidence for these games.
- These ingested DB records are not substituted for the 2019/2020 training pool or 2021 development
  labels: they occur later in time and using them there would leak the future. The archive-backed
  2021 historical adapter remains required for the preregistered paired development comparison.
- Historical candidate roster eligibility is inferred only from prior team appearances. Any
  player absent from prior history is an explicit coverage limitation; no target-box-score roster
  repair is allowed.
- 2018 remains chronology/source quarantine. 2022 remains previously exposed and is excluded.
  The ten Stathletes games are unrelated development evidence and are not used here.
- 2021 is development-only. No adoption claim is permitted. A later unseen or prospective season
  is required for adoption.

## Frozen comparisons

All model comparisons use the same eligible 2021 game keys, target definitions, historical
cutoffs, and per-game scoring implementation:

1. **v0.1:** frozen league-level historical period sampler, rebuilt with the frozen v0.1 code and
   its 2019/2020 training population. No target-team conditioning.
2. **v0.2 alpha2:** frozen alpha2 generator, supplied by a new historical pregame adapter using
   only prior verified box scores. This is an `alpha2-compatible historical replay`, not the
   original 2026 slate forecast and not a claim that 2026 B3 Elo is available in 2021.
3. **v0.2b:** alpha2-compatible historical inputs plus the separately versioned state-consistency
   and live-transition changes below.
4. **Historical-rate reference:** team scoring and prevention rates computed forward-only from
   prior eligible games, with shrinkage to the league mean; descriptive baseline only.

The v0.2b transition features are trained on 2019/2020 only. Any rates updated during 2021 use
strictly prior target dates. No v2/B3 prediction can be used as a training feature unless its
training provenance is proven out-of-fold or forward-only; this protocol does not depend on it.

## Controlled implementation sequence

Implement and measure each block separately, retaining alpha2 and earlier v0.2b blocks as
versioned controls:

- **B0, alpha2 replay:** no behavioral change; establish the historical adapter and reproduce
  frozen alpha2 generation on test inputs.
- **B1, state integrity:** faceoff winner sets latent possession; penalty timers and manpower are
  reconciled; goalie pulls/substitutions are explicit personnel state; shootouts terminate at the
  earliest mathematically decisive attempt. Donor event times may remain as timing scaffolding in
  this block.
- **B2, state-conditioned transitions:** sample event family and acting team from training-only
  transition distributions conditioned on simulated score, strength, latent possession, and prior
  event. Faceoff/turnover/shot outcomes update possession. Donor sequences may provide a fallback
  only when the transition cell is unsupported, with fallback use counted and reported.
- **B3, goalie pull policy:** estimate a trailing-time/score-state pull hazard from eligible
  2019/2020 records; do not use target-game starter or goalie presence labels as pregame inputs.

No block may be presented as evidence for another block. Each must have an isolated causal test;
paired 2021 metrics are reported for B0, B1, B2, and B3 where implemented. If a block cannot be
completed without violating the data boundary or accounting invariants, report it as not run.

## Causal and integrity tests

Tests use pinned real PBP/box-score/shift observations where available. Hand-authored fixtures are
identified as such and are not the sole evidence.

- Replaying identical frozen input and seed produces byte-identical game JSON.
- Holding seed and all other state fixed, intervening on the faceoff winner changes latent
  possession and changes the next possession-dependent event/shot allocation.
- Adding a supported minor penalty updates penalty time, removes the penalized skater from legal
  on-ice personnel while active, creates a manpower advantage, and restores manpower at expiry or
  a rule-valid goal release. Major penalties do not end on a power-play goal. Unsupported penalty
  classes fail closed or are counted as quarantined.
- Pulling a goalie changes empty-net status and subsequent goal probability under identical
  underlying random draws; it never leaves both a goalie and an extra attacker represented as the
  same player slot.
- A more capable goalie changes conditional save probability under common random numbers without
  changing shot occurrence or shot identity.
- The shootout stops immediately when the remaining attempts cannot erase the lead; paired rounds
  do not continue after clinch. Shootout bonus goal is separate from player goals and goalie
  regulation/OT statistics.
- Generated goals, SOG, attempts, player totals, goalie totals, clocks, periods, penalties, and
  on-ice personnel reconcile independently from the producing functions.
- Compare each selected source fixture to its verified original GameCenter payload. Record which
  test fixtures are invented and which real payload keys were checked.

## Metrics and uncertainty

For identical eligible 2021 games, report paired per-game values and paired differences for:

- regulation+overtime goals CRPS per team;
- official final-score CRPS per team;
- joint final-score energy score;
- winner Brier score;
- team SOG CRPS per team;
- observed versus predicted means, variances, and quantiles for goals, SOG, attempts, score margin,
  penalties, OT, and shootouts;
- event-family and manpower calibration, including unsupported-cell/fallback rate;
- simulation runtime, source preparation runtime, and Monte Carlo draw count.

Use a paired game bootstrap with a fixed seed and at least 2,000 resamples for 95% intervals.
Report Monte Carlo error separately from game-sampling uncertainty. Common random numbers are
shared across ablations wherever the event mechanism permits; a state intervention must not reuse
random draws in a way that suppresses its downstream causal effect. Final evaluation uses the
largest per-game draw count feasible under the resource gate, frozen before any comparison result
is inspected. If this requires changing the planned count, commit a dated protocol amendment first.

Calibration summaries must show the complete eligible population and relevant score/strength
strata. Missing candidate predictions are a failure, not a silently reduced denominator. Report
per-game coverage and every exclusion.

## Shift rejection diagnosis

The alpha2 report's `190` and `168` values are aggregate rejected donor-selection attempts from
two 500-simulation matchup instruments. They are not counts of unique source periods. The shift
diagnostic will deduplicate by source game ID × period and separately classify:

1. raw source interval/identity/coverage defects;
2. errors introduced by remapping source shifts to a historical candidate roster;
3. periods that pass source quality but fail current lineup/manpower acceptance;
4. repeated rejection encounters across simulation draws.

Never relax a source gate merely to increase acceptance. Preserve counts and examples at each
level and pin the shift manifest checksum.

## Resource and artifact rules

- Inspect implementation paths for hidden parallelism before batch execution.
- Run `uptime`, `free -h`, and top processes before the full evaluation; run one process at a time
  at reduced priority. Do not start below 1.5 GiB available memory. Recheck during long work.
- Begin with a smallest-real-game smoke run and measure its runtime before freezing the final
  Monte Carlo count. Record the command, elapsed time, and machine state.
- New code, protocol amendments, test logs, results, and reports live under v0.2b-specific paths.
  Do not edit, regenerate, or overwrite v0.1 or alpha2 artifacts.
- Databases are read-only; do not call ESPN; do not write production forecasts or databases; do not
  change Gridiron or any live service.
- Commit locally on the isolated branch. No push is authorized by this protocol.

## Decision boundary

This is a development comparison, not a gate change. Regardless of the 2021 score, retain Phase
2A/v0.1 and alpha2 as frozen research references. Recommend further work only if a candidate
improves the relevant paired outcomes without materially damaging SOG calibration or invariants;
adoption requires a genuinely unseen later-season or prospective evaluation.

## Amendment 2 — B2 transition specification

Date: 2026-10-25. This amendment is committed before any B2 matchup or development metric is
reviewed. It refines the preregistered B2 implementation without changing the evaluation population,
comparators, or adoption boundary.

- **Training population:** eligible 2019 and 2020 GameCenter PBP only, verified against the
  frozen PBP manifest. No 2021 or later target result contributes to transition fitting.
- **State key:** previous event family; whether latent possession is known; strength relation to
  possession (`EVEN`, `PP`, `PK`, `SPECIAL`, `UNKNOWN`); and score state (`TIED`, `HOME_LEADS`,
  `AWAY_LEADS`). Families are faceoff, shot attempt, giveaway, takeaway, penalty, hit, and
  stoppage. Unsupported penalty classes are represented as stoppages in the fitted transition pool.
- **Family backoff:** use the exact state cell when it has at least 25 transitions; otherwise back
  off to previous family plus possession-known status, then previous family, then the global
  training distribution. Record the selected level and cell count per event.
- **Event owner:** a shot follows known simulated possession. Other owned families sample the
  training owner relation (`same` or `opposite` latent possession, or home/away when possession is
  unknown), using the exact state/family cell at 10 or more observations and a family/known-status
  pool otherwise. A donor owner is only the final recorded fallback. A faceoff winner is sampled
  from simulated on-ice faceoff strengths and sets possession.
- **Clock and lineup boundary:** B2 changes the event family and acting side at each available
  donor event slot, but retains donor event count, clock slots, and shift intervals. It does not
  estimate event-arrival times or event intensity; those remain donor scaffolding and are excluded
  from any claim of a complete state-conditioned clock process.
- **Shot process:** B2 samples shot type/distance bin from the verified 2019/2020 shot-quality
  population. Generated attempts then pass through the candidate's SOG and conditional-goal
  outcomes, current simulated goalie, and team conversion offsets. Shot coordinates are not
  invented when the selected event slot has no observed shot coordinates.
- **Unsupported penalty states:** simultaneous newly sampled penalties that cannot be paired
  explicitly, and a third concurrent manpower penalty requiring queued serving, are emitted as
  stoppages with a structured omission reason and counted. They do not alter manpower. The rate is
  reported; no implicit penalty approximation is permitted.
- **Randomness:** B2 uses a separate deterministic transition RNG initialized from the game seed
  XOR `0x9E3779B9`. Same candidate/input/seed must remain byte-identical. B1/B2 comparisons are
  seed-paired; they are not described as full common-random-number coupling because a changed event
  family changes downstream draws.
- **Candidate identity:** B1 remains donor-family state-integrity control;
  `nhl-game-state-v0.2b-b2` is the transition candidate. B3 goalie-pull policy is not part of B2.

This amendment does not authorize production selection, a gate change, forecast writes, or a push.

## Amendment 3 — Ingested team SOG inputs

Date: 2026-10-25. This amendment freezes the prospective team-shot input before further
candidate-performance evaluation. It does not change the 2021 evaluation protocol, select a
candidate, or authorize an adoption/gate change.

- The simulator's default read-only database is `backend/data/picks.dev.db`. Its `team_game_stats`
  and `team_game_results` contain 1,312 completed 2025/26 games (2,624 paired team rows) and 94
  completed 2026/27 games (188 paired team rows) as measured before the Oct. 25 cutoff. The 2025/26
  team-stat coverage manifest is complete (1,312/1,312); 2026/27 coverage is 94/94 and marked
  in-progress. The production DB snapshot has 96 current-season games; it is not pooled with the
  development DB. Each run uses one explicitly pinned DB path.
- `team_game_stats.shots` is populated from NHL GameCenter right-rail `sog` for 2026/27
  (`nhle.com:gamecenter/right-rail+landing`). The legacy 2025/26 rows map ESPN `shotsTotal` to the
  same `shots` column. The current NHL GameCenter population reconciles by native `game_id` and team
  to ingested player `sog` in 186/188 team-game rows; two rows differ by one shot. The 2025/26 ESPN
  and NHL-native player logs use different game-ID vocabularies. Do not join those rows by date/team;
  no verified crosswalk is available.
- For a prospective NHL season, eligible team-game rows must have a game date strictly before the
  target date, completed status, a season equal to the target start-season or the immediately
  previous start-season, and result/stat captures strictly before the frozen cutoff. Both team
  result sides must be reciprocal on the same database `game_id`; the opponent's shot row is read
  by that same ID and stable team abbreviation. Target-game and same-day results are ineligible.
- Per-team attack rate is the arithmetic mean of its eligible team-game `shots`; suppression rate is
  the arithmetic mean of opponents' `shots` in those same games. Each eligible game has equal
  weight across the two included seasons. Matchup team SOG mean is the arithmetic mean of the
  attacking team's attack rate and the opposing team's suppression rate. The existing player-based
  SOG sum remains a separately reported diagnostic and continues to allocate generated shots among
  eligible simulated players; it is not blended into the team total. Missing eligible paired data
  for either team is a hard input-preparation error.
- The prior/current-season DB rows are prospective inputs only. They must not enter the 2021
  backtest. The historical adapter must derive prior team rates from the independently verified
  GameCenter archive with strict forward-only cutoffs. The historical comparison stays not-run
  until that adapter exists.
- Team goals remain supplied by the cutoff-filtered B3 forecast model and player/goalie conversion
  process in this block. DB team goal-result rates are available but remain diagnostic evidence for
  a later, separately preregistered scoring-rate experiment; they are not blended into this team-SOG
  input.

This amendment does not authorize production selection, a gate change, forecast writes, or a push.
