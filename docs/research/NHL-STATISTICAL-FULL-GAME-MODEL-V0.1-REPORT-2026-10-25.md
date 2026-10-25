# NHL Statistical Full-Game Model v0.1

**Status:** Research prototype delivered; not an adoption candidate.

**Branch:** `research/nhl-statistical-full-game-2026-10-25`

**Model:** `empirical-period-bootstrap-v0.1`

## Result

The first NHL statistical full-game model now generates a complete, ordered hypothetical play-by-play record from the local NHL GameCenter event archive. It samples historical period blocks, remaps event ownership to synthetic home/away sides, removes source player identifiers and coordinates, then computes the score from the generated goal events. It handles regulation, overtime, and the official shootout score adjustment.

This is a league-level event-template bootstrap, not a matchup forecast, next-event model, player simulation, or physical hockey engine. Requested team labels are display labels and do not affect event or score distributions. The generated examples are usable as statistical PBP records for a later read-only Gridiron viewer; no Gridiron code or UI was changed in this phase.

## Data and source validation

PBP comes from the read-only local archive at `/root/lp-data/nhl-fullframe-event-audit-2026-10-21`. Its frozen manifest has SHA-256 `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990` and lists 4,876 regular-season games. Team scores and shots on goal were independently checked against the local GameCenter `/boxscore` archive at `/root/lp-data/nhl-official-outcome-backfill-2026-10-20`; its manifest SHA-256 is `0ba44bcebefecb0a8eefbea995e8f5370583600eec77d0be12be574f308d71a2`. That manifest contains 4,576 `official_gamecenter` records and 300 records carried forward from a prior official audit cache.

Across the 4,533 games in start seasons 2018–2021, every selected PBP and boxscore body passed manifest size/hash checks. PBP and boxscore game IDs, home/away team IDs, final score fields, and team SOG fields agreed in all 4,533. PBP goal events reconciled to the independent final score in all games after applying the shootout convention: shootout attempts are not player goals, and the shootout winner gets one official scoreboard goal.

Event-derived SOG (`shot-on-goal` events plus regulation/OT goals) disagreed with boxscore SOG in 60 games: 2018 12, 2019 17, 2020 11, and 2021 20. The cause is unknown; those games are quarantined rather than repaired. The model also requires component-specific checks for event ownership, periods, chronology, and complete final scores.

The 2018 PBP timeline remains quarantined: its `sortOrder`-ordered event clocks had 13,394 backward transitions across 1,268 of 1,271 games, including reversals up to 1,200 seconds. No such reversals were found in 2019–2021. The training split therefore uses eligible 2019–2020 games, and 2021 is development-only. The exposed, partial 2022 slice was not used.

| Population | Listed | Eligible | Quarantined |
|---|---:|---:|---|
| 2019 training | 1,082 | 1,064 | 17 event-SOG mismatches; 1 incomplete period sequence |
| 2020 training | 868 | 857 | 11 event-SOG mismatches |
| 2021 development | 1,312 | 1,292 | 20 event-SOG mismatches |

## 2021 development results

Evaluation used 10,000 generated game draws, with fixed-seed simulation and 95% intervals from resampling the 1,292 eligible development games. Runtime, including source verification, was 28.264 seconds in this environment.

| Metric | Result | 95% game-bootstrap interval |
|---|---:|---:|
| Regulation/OT goal CRPS per team | 0.9922 | 0.9644–1.0196 |
| Official final-score CRPS per team | 0.9926 | 0.9673–1.0211 |
| Final-score energy | 1.5807 | 1.5418–1.6226 |
| Winner Brier | 0.2487 | 0.2466–0.2511 |
| SOG CRPS per team | 3.9111 | 3.7946–4.0302 |

These are development metrics, not evidence of superiority: no paired baseline comparison was run, and the interval for winner Brier does not establish improvement. The model uses the same league-level home/away distribution for every 2021 game.

The distribution is underdispersed and somewhat low on event counts:

| Count | Observed 2021 mean / variance | Simulated mean / variance |
|---|---:|---:|
| Regulation/OT home goals | 3.220 / 3.353 | 3.069 / 2.955 |
| Regulation/OT away goals | 2.974 / 2.938 | 2.775 / 2.618 |
| Official home score | 3.257 / 3.338 | 3.097 / 2.959 |
| Official away score | 3.011 / 2.940 | 2.807 / 2.636 |
| Home SOG | 32.248 / 47.233 | 31.232 / 39.948 |
| Away SOG | 30.957 / 47.518 | 30.006 / 39.958 |
| Nonboundary PBP events | 300.430 / 1,008.949 | 295.923 / 589.705 |
| Home-minus-away official goal margin | 0.246 / 7.090 | 0.291 / 5.976 |

The event-block bootstrap retains within-period event sequences, but independent period sampling does not reproduce full-game dependence or the wider observed variation. It slightly underestimates average goals, SOG, and nonboundary event count, and substantially underestimates event-count variance. This is a concrete limitation of v0.1, not a reason to add complexity without a controlled comparison.

## Reproducible records

- Regulation example (`nhl-statistical-game-v0.1-seed-31415.json`): 285 events, final 5–2. SHA-256: `e8daf15ad69a2276bf3cb06d682d841aa88dd49cda076791fdd5589621d00fbb`.
- Shootout-path example (`nhl-statistical-game-v0.1-shootout-path-seed-8.json`): 356 events, regulation/OT tied 2–2, official final 3–2. Seed 8 was selected only to exercise this branch; this is not an unbiased sample or performance evidence. SHA-256: `57db4fbc26caa4493a26b82b56965a9f9fc2dc100598b6e4703181308f490e18`.
- Full development diagnostics (`nhl-statistical-game-v0.1-development-2021.json`): SHA-256: `5081344716ed99ae4064c31e2c3b7bd9b64ad0d4f521ab6b1329effa434abfd5`.

The model source, run instructions, and generated JSON artifacts are maintained on the companion local branch `research/nhl-statistical-full-game-2026-10-25`. This `main`-branch publication contains the report only.

The seed-31415 regulation example was generated a second time and was byte-identical (SHA-256 `e8daf15ad69a2276bf3cb06d682d841aa88dd49cda076791fdd5589621d00fbb`). An independent reader also re-derived the state transitions and SOG counts for both examples, checked contiguous event sequence and monotone in-period clocks, verified regulation/OT/SO duration bounds, and found no emitted player/goalie identity or coordinate fields.

## Decision and next work

Keep v0.1 as a research prototype. It satisfies the first engineering deliverable—a reproducible complete statistical game event stream with regulation/OT/shootout accounting—but the 2021 results show underdispersion and there is no baseline evidence to justify forecast adoption. No production forecasts, databases, Gridiron/NFL code, or server were changed. The model generation and evaluation runs and source/body accounting checks completed; no test suite was run.

Next, build an NHL-specific, read-only Gridiron event viewer that renders the immutable statistical record as hypothetical. Separately preregister a conditional event/score model against this frozen v0.1 baseline, using the 2021 population for development and requiring genuinely later unseen data before any adoption claim. Keep physical, role-based player simulation as another track; this statistical event record does not model movement, players, or causal possession.
