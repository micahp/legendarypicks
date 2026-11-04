# Participation model, option A (2026-11-02)

Status: the skill-lineup transition model is built, tested (14 unit tests, plus the 9 model tests), and validated on a 2025
holdout. It is not wired into the simulator, and no realism comparison against SLC v1 has been run. Nothing is committed.

## Corrections made after review

1. **Lineups persist from snap to snap.** The first version drew each snap's skill players independently from rates. That
   design is rejected. Substitutions are now transitions between lineups: the grouping on a snap is drawn from the previous
   grouping in the same situation, a player on the field leaves with a hazard that depends on his position class and his
   stint (consecutive snaps on the field), and a leave is replaced from the bench at the same position class. A grouping
   change moves players by count. The independent draw stays in the validation as a control.
2. **The bench is the full eligible roster, not the players who carried or caught the ball.** The usage forecast lists
   971 carry players and 1,392 target players because it lists observed users. That listing is for display. The simulator
   draws bench players from the snapshot roster, so a player with no historical carries or targets can enter. Players with no
   on-field history get the position prior for their on-field rate, and the usage share falls back to the Laplace floor in
   `participation_model.usage_share`, never to zero. The validation bench is a proxy: each team's 2025 skill players who
   appear in the scrimmage table. The snapshot roster is the one the simulator uses.
3. **Current-season usage is not current-season personnel.** The 2026 play-by-play updates carry and target tendencies only.
   It does not say which other players were on the field. The 2026 grouping, the hazards and the on-field rates are priors
   from 2022 to 2025. The 1.089 log loss from the earlier counterfactual (2025 weekly personnel added) is a potential-value
   experiment. It cannot be reached with the 2026 data that exists now.

## Evidence that lineups persist

Measured on 2022 to 2025 consecutive offensive snaps (all 11 offensive players, from `scrimmage_participation`):
the same 11 players on consecutive snaps 26% of the time; mean Jaccard overlap 0.79 for consecutive snaps against 0.70 for
random same-game pairs. An independent per-snap draw would make consecutive lineups look like random pairs. It does not.

## The model (lineup_fit.py, export_field.py, scripts/nfl_sequence/participation_field.py)

- **Grouping transitions:** P(grouping | team, situation cell, previous grouping). The league transition is shrunk toward the
  league's grouping mix for the cell (20 pseudo-plays). The team's transition is shrunk toward the league transition (50).
- **Leave hazards:** P(leave | position class, stint bucket), with stints of 1 to 6 or more. Fitted on snaps where both
  neighbours match their grouping, and on the classes whose count holds. The hazard is fitted separately for held and changed
  groupings.
- **Swap churn:** in position classes whose count changes, extra churn beyond the count change itself, one rate per class.
- **Bench draws:** each entrant is drawn in proportion to his on-field rate for the team and grouping (appearances shrunk
  to the position prior, 20 pseudo-plays).
- Skill players only. The offensive line and the quarterback are not modelled. The grouping's RB and FB count as RB; the
  WR count is 5 minus RB minus TE.

## Validation (2025 holdout, fit on 2022 to 2024, 3 seeds, 570 team-games, 33,905 snap pairs)

Source: `outputs/lineup_validation_2025.json`.

| Metric | Observed 2025 | Free run | Forced grouping | Independent draw (control) |
|---|---|---|---|---|
| Grouping same as previous snap | 0.558 | 0.583 | 0.558 (given) | 0.558 (given) |
| Skill lineup same as previous snap | 0.241 | 0.237 | 0.227 | 0.066 |
| Skill lineup same, given grouping same | 0.432 | 0.407 | 0.407 | 0.119 |
| Entries per snap | 1.395 | 1.190 | 1.214 | 1.995 |
| Entries per game, RB | 20.1 | 18.2 | 18.8 | 31.4 |
| Entries per game, TE | 26.0 | 22.4 | 23.6 | 33.2 |
| Entries per game, WR | 36.9 | 30.1 | 29.8 | 54.0 |
| Mean stint per player-snap | 5.42 | 5.25 | 5.28 | 4.16 |
| Share of player-snaps with stint 4 or more | 0.420 | 0.474 | 0.468 | 0.319 |
| Counts match grouping | 0.919 | 0.998 | 0.998 | 1.000 |

Reading:
- Lineup persistence matches: 0.237 against 0.241 for the free run. The independent control is far off (0.066), so the
  persistence test separates the two designs.
- Substitution frequency is **not yet matched**. Entries run about 15% low in the free run (1.19 against 1.40 per snap), and
  the gap is in every position class (RB 9%, TE 14%, WR 18% low). The mean stint is close (5.25 against 5.42), but the free
  run has more player-snaps at stint 4 or more (47% against 42%), so its substitutions are not spread the way the data's are.
- About 8% of observed snaps list positions that contradict their grouping (for example a WR listed as a TE). The observed
  column includes those contradictions, which inflate observed entries. Restricted to pairs where both snaps match their
  grouping, observed entries are 1.33 per pair, against the free run's 1.19 over all pairs. That is still about 10% short.
- The model reproduces the count rules: 99.8% of simulated snaps match their grouping. The remaining snaps are bench
  shortfalls, recorded as `short`: 427 of 206,850 snaps across the free and forced arms, three seeds each.

Until the entry gap is closed, the claim that simulated substitutions match historical frequencies does not hold. The
open candidates are a stint-dependent swap rate, and a second swap pass on snaps where two classes change.

## Earlier evaluation (per-snap personnel prior, kept for the record)

The first version scored a per-snap grouping prior and a per-snap on-field draw. It is superseded for lineup use. Its
numbers, 2025 held out: personnel log loss 1.147 for the team prior against 1.172 for the league mix; top-group accuracy
59.1% against 58.8%; on-field log loss 0.298 against 0.411 for the position mean; carry-share log loss 1.66 with the weekly
update against 3.02 prior-only, and target-share log loss 2.48 against 3.59. The usage numbers still hold for carries and
targets. The personnel numbers describe a per-snap prior, not lineups.

## Forecast (outputs/forecast_2026_option_a.json)

- Carry and target shares from the 2026 play-by-play through week 6 (the pinned file). The live database has weeks 7 and 8.
- Lists 971 carry players and 1,392 target players with 2026 uses. Unlisted players get the Laplace floor.
- The on-field transitions and hazards are 2022 to 2025 priors for 2026.

## Limits

- Substitutions are not yet matched in frequency (see above). Do not wire the arm into the simulator until that is closed,
  or until the owner accepts the gap.
- The validation bench is a proxy (2025 appearances), not the pregame roster.
- Personnel groups in SLC v1 come from the formation layer, which counts RB only. The lineup model counts RB and FB together,
  so the simulator arm would need to use the lineup model's grouping, not the formation layer's.
- The offensive line and quarterback are not modelled.
- Pinned 2026 play-by-play ends in week 6. Usage needs a refresh when the pin is updated.

## Files

- `build_tables.py`, `participation_model.py`, `test_participation_model.py` (9 tests passing)
- `lineup_fit.py`: sequences, grouping transitions, leave hazards, swap churn
- `export_field.py`: writes the field table (`outputs/field_2022_2025.json` for production, 2022 to 2024 for validation)
- `validate_lineups.py`: the 2025 holdout comparison (`outputs/lineup_validation_2025.json`)
- `scripts/nfl_sequence/participation_field.py` and `test_participation_field.py` (14 tests passing)
- Scrimmage and usage tables are in scratchpad, not the repo, because of size.

## Root cause and candidates (2026-11-02)

The entry gap is decomposed in `ROOT-CAUSE-SUBSTITUTION-GAP-2026-11-02.md`. Clean pairs (both snaps match their listed
grouping) carry 1.331 observed entries per pair against 1.186 modelled (free arm). About half the clean gap sits at drive
boundaries, and most of the rest is WR. A joint draw of per-class leaver counts, conditioned on the grouping transition
and the drive boundary, fit on 2022 to 2024, brings the free-arm clean figure to 1.313 and matches the multi-class share
(0.333 against 0.337). WR stays 0.023 short. The candidates are research-only (`candidate_substitution.py`) and are not
wired into the simulator.

Field hashes after the refresh: `field_2022_2024.json` sha256 `8f555979fe6ba08f...` (validation and diagnostics);
`outputs/field_2022_2025.json` sha256 `f5ec825afde037a2...` (production table).

Outputs: `outputs/substitution_gap_diagnostic_2025.json`, `outputs/candidate_substitution_2025.json`.
