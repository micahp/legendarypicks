# IND–JAX Week 8 SLC 10K results and player workload review

**Game:** `2026_08_IND_JAX`  
**Audit status:** `complete`  
**Seeds accounted:** 10,000 / 10,000  
**Completed:** 9,998  **Blocked:** 2  **Simulation/validation errors:** 0  
**Valid box scores reconciled:** 9,998 / 9,998  
**Final ties after overtime:** 12  
**Box-score export:** True  
**Profile:** `v1_full_stack`

## Outcome and integrity

| Seed status | Count |
|---|---:|
| `blocked` | 2 |
| `complete_overtime` | 346 |
| `complete_regulation` | 9,652 |

Regulation end reached: 9,998; tied at regulation end: 0; blocked before regulation ended: 2; reconciliation failures: 0.

| Blocker | Count |
|---|---:|
| `blocked_kick_no_legal_geometry:field_goal:next_snap:kicking_team:next-snap blocked kick needs a legal observed start spot, down and distance` | 1 |
| `blocked_kick_no_legal_geometry:punt:next_snap:receiving_team:blocked_kick_next_snap_outside_field:receiving_team` | 1 |

Audit failures: 0. Full seed-level exceptions and source artifact hashes are in [`audit.json`](audit.json).

## Player eligibility and starter metadata

Archived boxscores scanned: 9,998 valid completed games across 6 worker archives. Starter status is `unknown` when the frozen roster does not provide evidence; it is not defaulted to false.

| Position | Starter true | Starter false | Starter unknown | Roster eligible true | Roster eligible false |
|---|---:|---:|---:|---:|---:|
| QB | 19,996 | 29,994 | 0 | 49,990 | 0 |
| RB | 0 | 0 | 69,986 | 69,986 | 0 |
| TE | 0 | 0 | 99,980 | 99,980 | 0 |
| WR | 0 | 0 | 139,972 | 139,972 | 0 |

QB participation by exported starter flag:

| Starter flag | QB player-game records with a pass, rush, or target | Pass attempts | Rush attempts | Targets |
|---|---:|---:|---:|---:|
| false | 0 | 0 | 0 | 0 |
| true | 19,996 | 728,492 | 66,224 | 1 |
| unknown | 0 | 0 | 0 | 0 |

No `starter=false` quarterback had a credited pass attempt, rush attempt, or target in these archived games.

Quarterbacks with credited use:

| Player | Starter | Evidence basis | Player-game records | Pass attempts | Rush attempts | Targets |
|---|---|---|---:|---:|---:|---:|
| Daniel Jones | true | depth_chart_rank_and_availability | 9,998 | 363,352 | 29,505 | 0 |
| Trevor Lawrence | true | depth_chart_rank_and_availability | 9,998 | 365,140 | 36,719 | 1 |

`roster_eligible` means present in the frozen roster snapshot; it does not claim the player entered the game.

## Player workload bumpers

Historical single-game values are alert boundaries, not legal caps. A new record remains possible; each exceedance is reported with its frequency and seed, never clipped.

| Metric | Historical boundary | Policy |
|---|---:|---|
| player rush attempts | 45 attempts | `record_alert_if_greater` |
| player pass attempts | 70 attempts | `record_alert_if_greater` |
| player targets | 28 targets | `record_alert_if_greater` |
| player receptions | 21 receptions | `record_alert_if_greater` |
| player rushing yards | 296 yards | `record_alert_if_greater` |
| made field goal distance | 68 yards | `record_alert_if_greater_and_require_kicker_capability` |
| attempted field goal distance | 76 yards | `policy_ceiling` |
| gross punt distance | 98 yards | `policy_ceiling` |
| ordinary scrimmage gain | 99 yards | `must_also_obey_available_field_geometry` |

### Simulated record exceedances

| Player | Team | Metric | Boundary | Exceedances | Rate | Maximum | Seed |
|---|---|---|---:|---:|---:|---:|---:|
| Jonathan Taylor | IND | rush_attempts | 45 | 186 | 1.860% | 60 | 1711 |
| Bhayshul Tuten | JAX | rush_attempts | 45 | 13 | 0.130% | 51 | 3807 |
| Alec Pierce | IND | targets | 28 | 9 | 0.090% | 32 | 4884 |
| Bhayshul Tuten | JAX | rush_yards | 296 | 8 | 0.080% | 339 | 440 |
| Josh Downs | IND | targets | 28 | 6 | 0.060% | 31 | 1823 |
| Jonathan Taylor | IND | rush_yards | 296 | 4 | 0.040% | 307 | 3494 |
| Parker Washington | JAX | targets | 28 | 3 | 0.030% | 31 | 4416 |
| LeQuint Allen Jr. | JAX | rush_yards | 296 | 1 | 0.010% | 303 | 5037 |
| Travis Hunter | JAX | receptions | 21 | 1 | 0.010% | 22 | 8453 |

### Provisional workload review gates

These are review thresholds, not rules of play. Role-specific gates are only applied when the run provides enough evidence to identify that role; the complete per-player distributions and reference joins are in [`player-workload-comparison.csv`](player-workload-comparison.csv).

| Player/role | Metric | Ordinary range | Review at | Serious at |
|---|---|---:|---:|---:|
| Jaylen Warren | rush attempts | 10–18 | 23 | 28 |
| Christian McCaffrey | rush attempts | 15–25 | 30 | 35 |
| lead_back | rush attempts | 18–28 | 33 | 40 |
| committee_back | rush attempts | 6–16 | 22 | 28 |
| WR1 | targets | 7–13 | 18 | 23 |
| WR2 | targets | 4–9 | 14 | 19 |
| starting_TE | targets | 4–9 | 14 | 19 |
| pocket_QB | non-kneel QB rush attempts / rushing yards | 0–2 | 4 att / 25 yd | 6 att / 50 yd |
| mobile_QB | rush attempts | 5–12 | 15 | 20 |
| starting_QB | pass attempts | 25–45 | 55 | 65 |

## Player means versus cutoff-safe references

The CSV includes every audited player/metric, simulated zero rate, P95/P99/maximum, benchmark support, reference basis, and absolute and percentage mean differences. The first table uses supported player-level shrunken references only and excludes zero-use rows, which need an eligibility check before workload calibration. Position-prior comparisons and zero-use rows are shown separately. This is a distribution comparison, not a causal attribution to one model layer.

| Player | Pos | Metric | Sim mean | Reference mean | Ref basis | Window | Ref games | Δ/game | Difference | Sim P95 | Sim max |
|---|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| Jonathan Taylor | RB | rush_yards | 100.55 | 58.34 | player_shrunken_mean | target_2026_w1_7 | 7 | 42.21 | 72.34% | 181.00 | 307 |
| Keenan Allen | WR | receiving_yards | 3.98 | 40.08 | player_shrunken_mean | target_2026_w1_7 | 6 | 36.10 | -90.07% | 27.00 | 181 |
| Bhayshul Tuten | RB | rush_yards | 84.18 | 48.30 | player_shrunken_mean | target_2026_w1_7 | 6 | 35.88 | 74.30% | 176.00 | 339 |
| Josh Cameron | WR | receiving_yards | 3.08 | 35.01 | player_shrunken_mean | target_2026_w1_7 | 4 | 31.93 | -91.21% | 22.00 | 176 |
| Laquon Treadwell | WR | receiving_yards | 3.94 | 33.34 | player_shrunken_mean | target_2026_w1_7 | 7 | 29.40 | -88.18% | 26.00 | 149 |
| Chris Rodriguez Jr. | RB | rush_yards | 4.57 | 32.58 | player_shrunken_mean | target_2026_w1_7 | 6 | 28.01 | -85.96% | 29.00 | 204 |
| Seth McGowan | RB | rush_yards | 1.26 | 28.14 | player_shrunken_mean | target_2026_w1_7 | 7 | 26.88 | -95.53% | 6.00 | 153 |
| Deion Burks | WR | receiving_yards | 4.00 | 27.78 | player_shrunken_mean | target_2026_w1_7 | 5 | 23.78 | -85.61% | 26.00 | 144 |
| Josh Downs | WR | receiving_yards | 64.12 | 40.67 | player_shrunken_mean | target_2026_w1_7 | 7 | 23.44 | 57.64% | 138.00 | 275 |
| Brian Thomas Jr. | WR | receiving_yards | 50.38 | 29.15 | player_shrunken_mean | target_2026_w1_7 | 6 | 21.23 | 72.83% | 126.00 | 294 |
| Drew Ogletree | TE | receiving_yards | 1.53 | 18.03 | player_shrunken_mean | target_2026_w1_7 | 4 | 16.50 | -91.52% | 11.00 | 91 |
| D.J. Montgomery | WR | receiving_yards | 3.70 | 19.92 | player_shrunken_mean | multi_2022_2025 | 7 | 16.22 | -81.43% | 24.00 | 153 |
| Nate Boerkircher | TE | receiving_yards | 4.21 | 19.41 | player_shrunken_mean | target_2026_w1_7 | 5 | 15.20 | -78.33% | 25.00 | 116 |
| DJ Giddens | RB | rush_yards | 7.72 | 21.78 | player_shrunken_mean | multi_2022_2025 | 9 | 14.06 | -64.55% | 42.00 | 166 |
| Mo Alie-Cox | TE | receiving_yards | 5.41 | 19.28 | player_shrunken_mean | target_2026_w1_7 | 4 | 13.86 | -71.91% | 28.00 | 113 |
| Brenton Strange | TE | receiving_yards | 47.80 | 34.24 | player_shrunken_mean | target_2026_w1_7 | 6 | 13.57 | 39.63% | 104.00 | 208 |
| Alec Pierce | WR | receiving_yards | 56.54 | 44.12 | player_shrunken_mean | multi_2022_2025 | 64 | 12.42 | 28.15% | 127.00 | 280 |
| Anthony Gould | WR | receiving_yards | 3.96 | 15.10 | player_shrunken_mean | multi_2022_2025 | 10 | 11.14 | -73.78% | 26.00 | 178 |
| Will Mallory | TE | receiving_yards | 1.37 | 12.07 | player_shrunken_mean | multi_2022_2025 | 24 | 10.70 | -88.66% | 10.00 | 70 |
| Jonathan Taylor | RB | rush_attempts | 24.64 | 13.98 | player_shrunken_mean | target_2026_w1_7 | 7 | 10.66 | 76.30% | 40.00 | 60 |
| Travis Hunter | WR | receiving_yards | 25.68 | 36.05 | player_shrunken_mean | multi_2022_2025 | 7 | 10.37 | -28.76% | 86.00 | 242 |
| Trevor Lawrence | QB | rush_yards | 23.07 | 13.35 | player_shrunken_mean | target_2026_w1_7 | 6 | 9.73 | 72.88% | 57.00 | 128 |
| Pharaoh Brown | TE | receiving_yards | 1.48 | 8.34 | player_shrunken_mean | multi_2022_2025 | 55 | 6.86 | -82.22% | 11.00 | 89 |
| Chris Rodriguez Jr. | RB | rush_attempts | 0.96 | 7.76 | player_shrunken_mean | target_2026_w1_7 | 6 | 6.80 | -87.64% | 6.00 | 33 |
| Bhayshul Tuten | RB | rush_attempts | 18.24 | 11.69 | player_shrunken_mean | target_2026_w1_7 | 6 | 6.55 | 56.01% | 33.00 | 51 |
| Ameer Abdullah | RB | receiving_yards | 5.35 | 11.88 | player_shrunken_mean | multi_2022_2025 | 59 | 6.53 | -54.96% | 28.00 | 115 |
| Seth McGowan | RB | rush_attempts | 0.31 | 6.78 | player_shrunken_mean | target_2026_w1_7 | 7 | 6.47 | -95.42% | 2.00 | 27 |
| Ameer Abdullah | RB | rush_yards | 5.03 | 11.26 | player_shrunken_mean | multi_2022_2025 | 59 | 6.23 | -55.32% | 31.00 | 225 |
| Ashton Dulin | WR | receiving_yards | 7.09 | 13.25 | player_shrunken_mean | multi_2022_2025 | 39 | 6.16 | -46.50% | 39.00 | 187 |
| Jonathan Taylor | RB | receiving_yards | 24.30 | 18.64 | player_shrunken_mean | target_2026_w1_7 | 7 | 5.66 | 30.36% | 64.00 | 159 |
| Seth McGowan | RB | receiving_yards | 2.28 | 7.58 | player_shrunken_mean | target_2026_w1_7 | 7 | 5.29 | -69.87% | 15.00 | 127 |
| Keenan Allen | WR | targets | 0.59 | 5.75 | player_shrunken_mean | target_2026_w1_7 | 6 | 5.16 | -89.80% | 3.00 | 16 |
| Daniel Jones | QB | rush_yards | 16.93 | 12.32 | player_shrunken_mean | target_2026_w1_7 | 7 | 4.60 | 37.35% | 42.00 | 91 |
| Alec Pierce | WR | targets | 9.06 | 4.54 | player_shrunken_mean | multi_2022_2025 | 64 | 4.52 | 99.71% | 18.00 | 32 |
| Josh Downs | WR | targets | 9.39 | 5.57 | player_shrunken_mean | target_2026_w1_7 | 7 | 3.82 | 68.68% | 18.00 | 31 |
| Josh Cameron | WR | targets | 0.41 | 4.12 | player_shrunken_mean | target_2026_w1_7 | 4 | 3.71 | -90.04% | 3.00 | 17 |
| Laquon Treadwell | WR | targets | 0.58 | 4.23 | player_shrunken_mean | target_2026_w1_7 | 7 | 3.65 | -86.34% | 3.00 | 20 |
| Keenan Allen | WR | receptions | 0.38 | 3.73 | player_shrunken_mean | target_2026_w1_7 | 6 | 3.36 | -89.94% | 2.00 | 10 |
| DJ Giddens | RB | rush_attempts | 1.93 | 5.26 | player_shrunken_mean | multi_2022_2025 | 9 | 3.33 | -63.33% | 10.00 | 37 |
| DJ Giddens | RB | receiving_yards | 2.22 | 5.54 | player_shrunken_mean | multi_2022_2025 | 9 | 3.32 | -59.92% | 14.00 | 120 |
| … | … | … | … | … | … | … | … | … | … | … | 77 additional player-reference rows are in the CSV |

Position-prior deviations over 25%: 14 rows. These are role-level context, not player-specific calibration failures; full details are in the CSV.

Zero simulated use with positive supported player history: 12 metric rows. Check roster role and substitution eligibility before treating these as workload errors.

| Player | Team | Pos | Metric | Reference mean | Window | Ref games |
|---|---|---|---|---:|---|---:|
| Anthony Richardson Sr. | IND | QB | pass_attempts | 22.43 | multi_2022_2025 | 17 |
| Anthony Richardson Sr. | IND | QB | passing_yards | 155.40 | multi_2022_2025 | 17 |
| Anthony Richardson Sr. | IND | QB | rush_attempts | 5.70 | multi_2022_2025 | 17 |
| Anthony Richardson Sr. | IND | QB | rush_yards | 30.18 | multi_2022_2025 | 17 |
| Riley Leonard | IND | QB | pass_attempts | 21.36 | multi_2022_2025 | 5 |
| Riley Leonard | IND | QB | passing_yards | 146.16 | multi_2022_2025 | 5 |
| Riley Leonard | IND | QB | rush_attempts | 2.57 | multi_2022_2025 | 5 |
| Riley Leonard | IND | QB | rush_yards | 11.34 | multi_2022_2025 | 5 |
| Quinn Ewers | JAX | QB | pass_attempts | 24.47 | multi_2022_2025 | 4 |
| Quinn Ewers | JAX | QB | passing_yards | 175.59 | multi_2022_2025 | 4 |
| Quinn Ewers | JAX | QB | rush_attempts | 2.95 | multi_2022_2025 | 4 |
| Quinn Ewers | JAX | QB | rush_yards | 11.62 | multi_2022_2025 | 4 |

## Run version and changes since the prior run

- Previous run source: `7faa8eda`; this run source: `2a1022a522ec2be57b53cea234e65a3a139dab61`.
- Source diff: 39 files changed, 258304 insertions(+), 96 deletions(-).
- Frozen snapshot SHA-256: `4ae2426576f3ee10eac58ffab0a31b860c431def77604c2b229be883ca544fed`.
- SLC configuration hash: `96dc1423f1743c7faece20b2ddd7d7550d9757e06e915f8b2fd36bb225c99572`.
- Playcall artifact SHA-256: `27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7`.
- Benchmark manifest SHA-256: `312591afedbeba27443c0246c7ce8ea5aecb15f2eeb3703b65af817c769e6aea`.
- Boundary configuration SHA-256: `4e27d54296ffdcbb1b42d2de0dd9c8ba57837aee04d4b5c2a3b3b36d46fbdfb0`.
- Run header saved as [`run-header.json`](run-header.json).

Changes in the producer source range:

- `2a1022a5 fix(nfl): calibrate SLC player participation and accounting`
- `dee4a084 Generate cutoff-safe player workload references`
- `c188ee3b Add cutoff-safe player workload benchmark builder`
- `6a1955be Add SLC scoring and clock replay review outputs`
- `fff76c08 fix(nfl): distinguish final overtime ties from regulation ties`
- `fa06fe84 research(nfl): configure event clock replay windows`
- `52c59c10 fix(nfl): filter lateral rows and retain blocked decisions`
- `be75336f docs(nfl): record ARI-DAL 10K shard run state`
- `fdfb2feb docs(nfl): record SLC transition and pilot diagnostics`

Relevant behavior and scope:

- `52c59c10`: Filter unsupported lateral source rows and retain blocked-decision evidence.
- `fff76c08`: Distinguish a final overtime tie from a tie at the end of regulation.
- `c188ee3b / dee4a084`: Build and publish cutoff-safe player workload references for 2022–2025 and 2026 Weeks 1–7.
- `2a1022a5`: Limit designed-run participants to active QB1; condition opportunity shares by position; honor roster eligibility; derive QB starter status from depth and availability; correct touchdown and box-score accounting.
- `fa06fe84`: Add event-clock replay windows for the separate Model D diagnostic; this is not an enabled SLC playcall layer in this run.

Runtime blocker-fix switches recorded in the run header:

- `blocked_kick_geometry`: enabled
- `blocked_kick_source_audit`: enabled
- `long_field_goal_feasibility`: enabled
- `run_scramble_backoff`: enabled
- `safety_free_kick_boundaries`: enabled

Enabled playcall flags from the run header:

- `coverage`: `True`
- `decision`: `True`
- `decision_filter_enabled`: `True`
- `dirichlet_shares`: `True`
- `exact_yardline`: `True`
- `formation`: `True`
- `playbook`: `True`
- `player_outcomes`: `True`
- `player_outcomes_receiver_only`: `False`
- `player_shares`: `True`
- `point_splits`: `True`
- `qb_decisions`: `True`
- `streak_league`: `True`
- `streak_splits`: `True`
- `target_roles`: `True`
- `team_outcomes`: `True`

Optional QB run-role-style layer: `not recorded`.

## Provenance and interpretation

- Audit JSON SHA-256: `f1b643e591fb24e22933f9c2279a0add366e4c445c5cfcf92acbfe1562623f20`.
- Run-header JSON SHA-256: `4644d911501fb0b81b3d33963a605443abecf4f3a82b15fe3d6aeda41244ec5c`.
- Statistical outliers are distribution warnings. They do not invalidate otherwise legal games.
- The report preserves blocked/error seeds and does not change or clip any outcome.
