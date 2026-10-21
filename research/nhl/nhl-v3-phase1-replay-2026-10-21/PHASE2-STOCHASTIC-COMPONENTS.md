# Proposed Phase 2 stochastic simulation components

Phase 1 only establishes chronology, deterministic replay, and the information
boundary. No parameter or probability is fitted or invented here.

| Component | Inputs available before the simulated game or generated during it | Generated state/events | Calibration target |
|---|---|---|---|
| Initial conditions | Pregame teams, venue/date, accepted roster availability, eligible historical team/player priors | Opening faceoff state and initial lineups | Published schedule and accepted pregame lineup/availability snapshots |
| Possession and zone sequence | Pregame team/player features plus current simulated state | Possession changes, zone entries/exits, stoppages | Sequence and rate summaries from accepted historical events; latent possession remains inferred |
| Shot generation | Simulated possession, manpower, shooter/goalie states, pregame skill features | Shot attempt, shooter, shot type/location, miss/block/on-target outcome | Event totals, shot-type mix, location distribution, shooter SOG where eligible |
| Penalty process | Simulated state, pregame discipline features | Penalty call, delayed-call phase, penalty duration/type | Penalty timing/type/duration and ensuing accepted manpower observations |
| Manpower and special teams | Generated penalty ledger, period clock, simulated score | Skater counts, power-play intervals, penalty expiry/offsetting events | Situation-code distributions and penalty-linked transitions; ambiguity remains explicit |
| Goalie deployment | Pregame goalie availability plus simulated score/time and substitution state | Starter, substitution, empty-net pull/return | Directly verified PBP goalie IDs and published goalie TOI; never shift-derived saves/SA |
| Score and period flow | Generated shot outcomes, current score, period rules | Regulation and overtime score, period transitions | Accepted team score and period-specific scoring distributions |
| Shootout | Pregame team/player features and simulated overtime tie | Alternating attempts and winner | Shootout event outcomes; winner's official one-goal convention applied only to final-score output |
| Event assembler | Component outputs and simulated clock/state | Publisher-independent deterministic generated event sequence | Schema validity, chronological invariants, conservation checks |

Phase 2 should fit and validate these components separately before composing
them. Replay results may serve as historical evaluation targets, but the
simulation request must not contain the actual game's future events, final
score, target rows, or event-derived states. Calibration, chronological
holdouts, parameter uncertainty, and prospective leakage checks are required
before any simulator result is treated as predictive.
