# Scoring review and program reset: decision memo

Date: 2026-11-07
Author: lead (PM), taking over after the 2026-11-07 session was rate-limited mid-slate
Status: the scoring defect is not undiagnosed. It is **25 days old**, its cause is documented, and the experiment that would fix it was never landed.

Companion files in this folder:

| File | Contents |
|---|---|
| `scoring-distribution-analysis.md` | this memo |
| `slc-scoring-distribution-analysis.xlsx` | tables and charts: score bins, game tails, team strength, mechanism, provenance, defect history |
| `scoring_compression.png` | two-panel figure: score density and the between-team spread |
| `scoring-tables/*.csv` | the raw tables behind every number here |
| `thursday-postgame-review.md` | the bounded postgame review of the JAX-BAL game along the causal chain |
| `sunday-repro-audit.md` | audit of the 13-game Sunday smoke bundle: 5 pass, 2 fail |

---

## 0. Why this memo exists

The owner asked why the engine cannot produce team scores below 17 or above 27, then asked how far the program is from completing the goal.

Working through the repository rather than the chat history changed the answer twice:

- First, the coarse claim is not true. The engine produces sub-17 and 27-plus team scores at close to the real rate.
- Then, the defect that *is* real is not new. It was measured, gated, blamed on a specific mechanism, and handed to an agent on **2026-10-13**. Three and a half weeks later it is still open, and two later attempts did not close it.

This memo states the chain, gives the numbers, and proposes one bounded piece of work with the gate that already exists.

**A disclosure about method.** I derived the compression myself before running the repo's `prior_art.py`, and only then found that `docs/RESULTS-nfl-sim-g4-elo-2026-10-13.md` had recorded the same result with a better harness. That is the same failure this memo criticises: the knowledge was present and nobody routed it. The recomputation below is therefore offered as **independent confirmation of a known result**, not as a new finding.

---

## 1. Bottom line

1. **"Cannot model under 17 or over 27" is wrong at the bin level** and right at the extreme. Under 17 happens 24.7% of the time against 25.2% observed. But shutouts are 5x too rare, 40-plus games are 2x too rare, and blowouts are 54% too rare.
2. **The defect that matters is that the engine compresses the gap between good and bad teams.** Real spread 4.571 points; simulated 3.616; ratio **0.791 against a pre-registered floor of 0.80**. On the SLC engine's own 2025 backtest it is 0.77.
3. **The cause is documented in two parts**: the score sampler passes only ~72% of a team's expected advantage through to its simulated points (M3 slope 0.723), and the defensive split layer is not connected at all.
4. **The fix was assigned and never landed.** A pre-registered G4b experiment was opened on 2026-10-13. There is no such branch on origin today and no results document.
5. **The later SLC replacement test could not have worked.** It compared *means* on 3 matchups x 40 seeds, with no variance estimand. A spread defect needs a spread measurement and hundreds of seeds.
6. **Priority should move off player workload, rule breadth and slate volume and onto two things:** the sampler pass-through and a connected defensive split. Judge against the existing G4 gate, not a new invented one.

---

## 2. The diagnosis is 25 days old

| Date | Event | Where |
|---|---|---|
| 2026-10-13 | G4 gate set for team spread with a floor of 0.80. The real-score option **fails at 0.791**. Real spread 4.571, simulated 3.616. | `docs/RESULTS-nfl-sim-scores-2026-10-13.md` |
| 2026-10-13 | Follow-up refutes "the ratings regress to the mean" and localises the cause to the sampler: **M3 slope of simulated on expected points per game is 0.723.** Even with a perfect pass-through the ratio would only reach ~0.905. | `docs/RESULTS-nfl-sim-g4-elo-2026-10-13.md` |
| 2026-10-13 | Next experiment pre-registered: *"raise the sampler's pass-through (fewer neighbours, or a variance-restoring step on the expected points)"*. Branch `feat/nfl-sim-g4b`, worktree `/root/lp-sim-g4b`, assigned to an agent. | `docs/CONTEXT-2026-10-13.md` line 67 |
| 2026-10-28 | Integration ledger records that **the detailed offensive and defensive team splits are "not connected... There is no defensive split"**, and that only a partial offense-side by-down effect exists. | `docs/research/SLC-INTEGRATION-LEDGER-2026-10-28.md` |
| 2026-10-29 | An SLC team-strength ablation runs 3 matchups x 40 seeds on three arms. It reports paired t-intervals on **`home_margin`, `total_points`, `home_win` only**. No variance or spread metric exists in the analyser. | `docs/research/slc-team-strength-passthrough-2026-10-29/`, `analyze_team_strength_passthrough.py` |
| 2026-11-05 | The 2025 realism backtest, 271 games x 30 seeds x 3 arms, still measures the spread at 0.77 of true. Same defect, unchanged. | `docs/research/SLC-2025-REALISM-RESULTS-2026-11-05.md` |
| 2026-11-07 | The slate work continues on snapshots, rules and one-seed smoke runs. The spread defect is not on the slate's critical path or in its completion criteria. | `docs/research/slc-sunday-smoke-2026-11-08/` |

**Verification of the gap.** Three measurements:

- `git ls-remote --heads origin` returns 218 branches and **none matching `g4`**, on `origin` or on the direct GitHub URL. No G4b results document exists anywhere in the repo.
- On the `slc-v2` branch the four backend simulator files last changed on 2026-10-13 (`nfl_sim.py` `19092c69`, `nfl_sim_scores.py` `1e5fce62`, `nfl_sim_margin_source.py` `8d48e3b8`) or earlier. No variance-restoring step was added.
- `backend/nfl_sim_margin_source.py` still states its own pass-through hypothesis as open, in the docstring of a file whose purpose was to settle it.

So the G4b experiment was either never finished, never pushed, or its branch was deleted. The one later attempt replaced it with a means-only test that cannot see the defect it was aimed at.

---

## 3. The owner's claim, tested precisely

544 observed team-games (2025, 272 games) against 15,726 simulated team-games (V2, 271 scored games x 30 seeds), from the committed 2025 backtest:

| Team-games | Observed | V1 | V1.5 | **V2** |
|---|---:|---:|---:|---:|
| under 17 | 25.2% | 23.6% | 24.4% | **24.7%** |
| 17 to 27 | 45.0% | 48.2% | 48.0% | **47.3%** |
| over 27 | 29.8% | 28.2% | 27.7% | **28.1%** |
| KS distance | — | 0.046 | 0.039 | **0.040** |

The bins are close. The truncation is in the extremes:

| Tail event | Observed | V2 | Ratio |
|---|---:|---:|---:|
| shutout | 1.29% | 0.26% | 0.20 |
| 3 or fewer points | 2.76% | 1.18% | 0.43 |
| 6 or fewer points | 4.60% | 2.97% | 0.65 |
| 10 or fewer points | 13.24% | 9.25% | 0.70 |
| 35 or more | 12.13% | 9.32% | 0.77 |
| 40 or more | 6.43% | 3.23% | 0.50 |
| standard deviation | 9.94 | 8.78 | 0.88 |
| p10 / p90 | 10 / 37 | 12 / 34 | — |

The low end in detail, with game-clustered 95% intervals (`scoring-tables/low-end-scoring.csv`):

| Cut | Observed | 95% CI | V2 | 95% CI | V2 / observed |
|---|---:|---|---:|---|---:|
| 3 or fewer | 15 of 544 (2.76%) | 1.47 - 4.23% | 185 of 15,726 (1.18%) | 0.98 - 1.39% | **0.43** |
| 10 or fewer | 72 of 544 (13.24%) | 10.66 - 15.99% | 1,454 of 15,726 (9.25%) | 8.53 - 9.95% | **0.70** |

On a 272-game season that is about **15 team-games at 3 or fewer against roughly 6**, and **72 at 10 or fewer against roughly 50**. The simulated mass is not missing; it has moved up. At the exact values: 0 points 1.29% against 0.26%, 3 points 1.47% against 0.91%, 7 points 1.47% against 0.91%, 10 points 4.78% against 3.40%, while 13 points runs 3.86% against 5.45%.

At game level, the missing events are the ones a viewer would notice:

| Game-level event | Observed | V2 | Ratio |
|---|---:|---:|---:|
| blowout, margin 21+ | 18.0% | 9.7% | 0.54 |
| a team held under 10 | 16.9% | 11.4% | 0.67 |
| both teams under 17 | 7.0% | 5.8% | 0.83 |
| both teams over 27 | 9.9% | 8.3% | 0.84 |
| total 60 or more | 16.5% | 13.2% | 0.80 |
| mean absolute margin | 11.15 | 9.87 | 0.89 |

**"We cannot model under 17 or over 27" is the wrong summary of a real observation.** The engine is not stuck in the middle; it is stuck at the edges, and it is stuck there because it cannot separate teams.

---

## 4. The defect: the engine compresses team strength

The 2025 backtest does not contain this table, so it is worth stating plainly.

| Between-team measure | Observed 2025 | V2 |
|---|---:|---:|
| SD of team-season scoring averages, raw | 4.15 | 2.59 |
| that SD after removing 17-game sampling noise (±2.41) | **true spread 3.38** | — |
| simulated spread as a share of true | — | **77%** |
| best team minus worst team, season average | 16.3 pts (LA 30.5, LV 14.2) | **9.1 pts (SEA 26.5, TEN 17.4)** |
| correlation of team-season averages | — | 0.80 |
| correlation of single team-game scores | — | 0.27 |

The engine ranks teams in roughly the right order and then refuses to believe the ranking. Its best offense is 9 points better than its worst; the league's is 16.

This is the same quantity the G4 gate measured in October, with the same answer: **0.79 against a floor of 0.80**, and 0.77 on this engine's own backtest. The gate was set, it failed, and it has not been revisited.

---

## 5. Why: two documented causes, neither addressed

### Cause 1: the sampler shrinks the advantage

`RESULTS-nfl-sim-g4-elo-2026-10-13.md` measured a slope of simulated on expected points per game of **0.723**. A team with a 3-point expected edge is simulated as roughly 2.2 points better. The sampler alone costs about 0.11 of the spread ratio; the inputs cost the rest.

The pre-registered remedy was explicit: *"raise the sampler's pass-through (fewer neighbours, or a variance-restoring step on the expected points)"*. It was not implemented.

### Cause 2: there is no defensive split, so matchups cannot separate

The 2026-10-28 integration ledger states it directly: detailed offensive and defensive team splits are **not connected**, and *"There is no defensive split"*. Only a partial offense-side by-down effect exists inside the play-call layer.

That is a structural reason for compression, not a tuning error. If every offense faces roughly a generic defense, then a good offense and a bad offense are pulled toward each other, and the same is true of defenses. No amount of tuning the offense side can restore the missing matchup variance, because the term is absent from the model.

### What the engine does instead

It manufactures volume and protects the ball, and the errors cancel in the mean:

| Metric per team-game | Observed | V2 | Change |
|---|---:|---:|---|
| drives | 10.48 | 10.51 | matches |
| plays per drive | 5.87 | 6.59 | **+12.2%** |
| yards per drive | 31.9 | 37.3 | **+16.9%** |
| points per drive | 2.23 | 2.20 | -1.3% |
| giveaways | 1.10 | 0.79 | **-28%** |
| sacks, share of pass plays | 8.0% | 3.7% | **-54%** |
| scrimmage plays | 60.6 | 68.1 | +12.5% |
| scrimmage yards | 327.8 | 384.6 | +17.3% |
| points | 23.01 | 22.79 | -1.0% |

Derived: **yards required per point rises from 14.3 to 16.9 (+18.4%)**, while **points per play falls from 0.380 to 0.334 (-12.0%)**.

The result is a team that almost never gets shut down (200-yard games: 1.0% against 7.0% observed), almost never blows the game open (500-yard games: 6.9% against 2.2%), and almost never gives the ball away. There is a floor under offensive production and a ceiling on conversion. Both tails are squeezed out, and the average survives because the two errors offset.

---

## 6. What is not the cause

- **Not blocked seeds.** V2 blocked 267 of 8,160 seeds (3.27%). Blocking is uncorrelated with how extreme the real game was: r = -0.07 against deviation in total points, r = +0.02 against margin. Blocked share is 2.84% in the most extreme quintile of games against 3.03% in the middle. Stop investigating this.
- **Not the coarse bins.** Section 3.
- **Not seed volume.** These are 15,726 simulated team-games. The defect is structural and will not move with more seeds.
- **Not the five blocker fixes or the identity fix.** The top two deficiencies are unchanged across V1, V1.5 and V2, which are three different builds.

---

## 7. Thursday as an illustration

Two companion reports in this folder do the detailed work; this section states what they change.

From the 1,000-seed corrected V2 rerun, with the actual result:

| Quantity | Simulated median | Actual | Percentile of actual |
|---|---:|---:|---:|
| Jacksonville points | 24 | 33 | 82nd |
| Baltimore points | 20 | 10 | 10th |
| total points | 44 | 43 | 44th |
| Jacksonville margin | +4 | +23 | 95th |

The total sat at the median while **both** team outcomes were tail events in opposite directions. A compressed team spread produces exactly this: the model insists the teams are close, reality separates them, and the totals offset. Reviewing Thursday by its total points would have missed the only thing worth learning from it.

`thursday-postgame-review.md` adds a second, independent range failure that is arguably more damning:

- **The actual play mix is outside the model's support.** Baltimore threw 19 passes; that is the **0.3rd percentile** of V2's simulated distribution. The two teams combined for 45 pass attempts, which is the **floor** of V2's 3,000-seed support (minimum 45/46/47 by arm), while their 58.7% run share sits at the 98.6th-99.2nd percentile. Rush attempts, 64 combined, were at the 60th percentile. So the engine gets total rushing volume right and cannot generate the passing volume a real team used while trailing by up to 30 points.
- This is the same defect as section 5's plays-per-drive problem, seen from a different angle: the engine's drives run 6.3-6.5 plays against an actual 4.5-4.7, and it passes more than real teams do in lopsided games.

**A correction to prior art, from that review.** The V2 `snaps` field is not a snap count. Independently verified: team-seed snap totals average 333 (theoretical minimum about 740 for 11 players x 68 plays), only 14 players per team-seed have any snaps, the starting quarterbacks record 0 snaps on 995/1000 and 983/1000 seeds despite throwing in every seed, and 2,712 player-rows hold production with zero snaps. The 2025 realism report's V2 snap rows are therefore invalid, including its RB1 snap-share comparison (0.613 simulated against 0.636 observed). That row should be withdrawn, not cited. The same review also found `targets` is identically `pass_attempts` in 2000 of 2000 team-seeds, the box-score `status` field contradicts the seed ledger on every row, and simulated possession time sums to 3,575 s against a 3,600 s regulation clock.

---

## 8. Where the program stands

Two goals have been reported as one. Separated:

**Goal A: secure a Sunday slate.** Execution and the 50-seed pass done; the slate is still not validated.

| Criterion | Status |
|---|---|
| Inputs frozen pre-kickoff, 13 games, hashes recorded | done |
| One complete legal game per matchup | done, 13 of 13, all `valid_full_game: true` |
| Reproducible executed code | **FAIL** (audited): the patch is byte-identical to the committed `9667cbc1`→`2f87d817` diff, so the "uncommitted, exist in no commit" claim is false; base+patch cannot reproduce the recorded tree because the seed headers pin `pregame_snapshot.py` to its HEAD hash while the patch leaves it at its 9667 version; run headers record three different `source_commit` values (11x `0febeff7`, 2x `7890e7cc`, 1x `da4636cd`) |
| 50-seed pass with medians and bands | **done** in `98a10fbc2`: 13 of 13 matchups, 49 to 50 complete seeds each, medians and 10th to 90th bands published |
| Legality across the 50-seed pass | **3 of 13 fail validation**, and two of the three are the "adjacent-play state continuity" blocker declared closed: `CIN_ATL` seed 50 and `DAL_IND` seed 47 both report "field_goal_attempt ends the drive but play 59/131 follows"; `CLE_NO` seed 29 reports "overtime kickoff follows drive 23, which does not end regulation" |
| The audit's findings apply to the 50-seed pass too | yes: its manifest states `executed_code: same as slc-sunday-smoke-2026-11-08 (base 9667cbc1 + executed-code.patch)`, so it inherits the same false provenance |
| 200-seed pass | not started |

**Goal B: realistic scoring.** Diagnosis complete since October; no fix attempted.

| Known deficiency | How old | Status |
|---|---|---|
| Team-strength compression, G4 ratio 0.79 | 25 days | **open** |
| Sampler pass-through slope 0.723 | 25 days | **open**, remedy pre-registered and never landed |
| No defensive split connected | 10 days documented, longer in practice | **open** |
| Plays per drive +12% | 25 days | untouched in every arm |
| Yardage tails inverted | 25 days | untouched in every arm |
| Sacks at half the real rate | known | untouched |
| Giveaways -28% | known | unchanged |
| Named-player workload allocation | known | V2 made this **worse** than V1.5 |

Note the ordering. The one deficiency the last week optimised hardest — running back and receiver workload — is the one where V2 regressed.

Two additional hard failures, both cheap:
- **`2025_07_GB_ARI` cannot be simulated at all**: all 30 seeds in all three arms fail with `QB 00-0035228 has no eligible target roles on team ARI`. One matchup in 272 is unplayable for a roster-role data reason.
- **`prior_art.py` cannot find its own prior art.** It returned "no prior art" for `"points distribution too narrow"`, `"G4 gate"` and `"sampler shrinkage"`, all of which are in committed documents. That tool is supposed to prevent exactly this memo's opening failure and currently does not.

And one surface that must be withdrawn rather than repaired:
- **The V2 `snaps` field is not a snap count.** Team-seed sums average 333 against a theoretical minimum near 740, only 14 players per team-seed have any snaps, and the starting quarterbacks record zero snaps on 995 and 983 of 1,000 seeds while throwing on all 1,000. Every snap-based conclusion about V2 is invalid, including the 2025 report's RB1 snap-share row (0.613 simulated against 0.636 observed).

---

## 9. Decision

1. **Name the goal correctly.** The goal is not "implement all football" and not "run more seeds". It is: *make the engine's between-team spread and its extreme outcomes match the observed league, without breaking the mean.* One sentence, one gate.
2. **Work the two documented causes, in this order:**
   - a) Re-land the pre-registered G4b sampler pass-through experiment (fewer neighbours or a variance-restoring step), on the current build.
   - b) Connect the defensive split layer, or explicitly model opponent strength in the scoring process, so matchups can separate.
3. **Judge against the gate that already exists**, not a new one: G4 ratio >= 0.80 to pass, >= 0.90 to claim it is fixed, with G1 (outcome calibration, Brier), G2 (validity), G3 (totals), G5 (season odds) and G6 (ties) unchanged. Two extra diagnostic targets are worth adding because they name the mechanism: sacks as a share of pass plays (observed 8.0%), and team-games at 200 yards or fewer (observed 7.0%).
4. **Use a harness that can see the defect**: many games, at least 30 seeds each, paired against the current build. Three matchups and forty seeds cannot measure a variance change; the standard error of a standard deviation at n=40 is about 1.1 points on a true value of about 10.
5. **Stop for now:** RB/WR workload tuning (regressed), new field-bin keys, new validator rules beyond the four already named, and large raw exports into git.
6. **Sunday, corrected conclusion: the slate is executed and 50-seed sampled, not validated.** The independent audit (`sunday-repro-audit.md`) returns **5 pass, 2 fail** on the one-seed bundle and answers "can the slate be called validated?" with **no**. The 50-seed pass that arrived during this review does not change that verdict: 3 of 13 matchups fail legality, and two of those are the "adjacent-play state continuity" blocker that was declared closed. Before anything is published: fix those three seeds' defect, correct the provenance statement in the bundle's own manifest, record both the canonical and the on-disk patch hash, and state that the legality verdicts rest on self-reported flags with no shipped per-play evidence. Then publish it as an engineering smoke product with the spread caveat printed on it. Do not present any distribution from this build as a forecast: the measured predictive spread is 0.79 to 0.88 of reality, so a 200-seed band drawn from it will be confidently wrong.
7. **Fix `GB_ARI` and `prior_art.py`.** Both are small, both cost the program real time.

---

## 10. What is needed from the owner

1. **Confirm the priority move**: team spread and scoring shape above slate volume and rule breadth.
2. **Decide the evidence basis**: accept the committed 2025 backtest as the baseline, or commission a re-run on the current build. A full rerun is expensive; a 40-game stratified subset at 30 seeds is enough to test whether the blocker fixes moved the spread.
3. **A runner for G4b.** The simulator does not run from this workstation; the fast host is needed for the sampler experiment.
4. **Say where the "below 17 / above 27" impression came from.** The measurement says the bins are already right. If a specific screen or report gave that impression, the screen is the thing to check, because it may be hiding the spread behind medians — which is precisely how Thursday's review went wrong.

---

## 11. Provenance and limits

- **Primary source**: `docs/research/SLC-2025-REALISM-RESULTS-2026-11-05/` and its committed report. `seed_status.csv.gz` (24,480 rows) is the basis for every simulated distribution here; `observed/observed_team_game.csv` (544 rows) is the observed side.
- **Prior art cited, not re-derived**: the G4 spread ratio, the 0.80 floor and the 0.723 pass-through slope come from `docs/RESULTS-nfl-sim-g4-elo-2026-10-13.md` and `docs/RESULTS-nfl-sim-scores-2026-10-13.md`, measured on 2020-2025 with 20,000 simulations per season. My recomputation on the SLC engine confirms the direction and the order of magnitude; it is not an independent replication of that harness.
- **`valid_full_game` is 0 in every arm of the 2025 backtest.** Inputs are `exploratory_replay`, not verified snapshots. These are engine comparisons, not valid forecasts.
- **`development_exposed: true`.** The 2025 season was visible while the play-call layer was tuned. These numbers are in-sample and flattering; the out-of-sample gap is likely worse.
- **Build vintage.** The backtest was produced from a build dated 2026-11-05 10:52 CST, before the five blocker fixes, the identity fix and the validator work. The top two deficiencies are unchanged across three arms, so they are unlikely to be artifacts of that vintage, but this is inference, not measurement.
- **No per-play simulated records.** Field position and explosive plays cannot be attributed. The mechanism in section 5 is inferred from drive-level aggregates and needs a per-play run to confirm.
- **My noise-correction of the observed team spread is an estimate** (4.15 observed, 2.41 sampling noise, 3.38 implied true). The multi-season G4 figure of 4.571 is the better estimate of real spread and is why the G4 number is quoted first.

## 12. Reproduction

The analysis scripts are committed beside this memo in `scripts/`. They read only committed repository files, so nothing here needs the fast host or the database.

```
python scripts/scoring_analysis.py    # bin shares, KS, discrimination, blocked bias, Thursday percentiles
python scripts/scoring_part2.py       # game-level tails, noise-corrected team strength, efficiency ratios
python scripts/low_end.py             # the <=3 and <=10 cuts, exact low scores, game-clustered intervals
python scripts/emit_tables.py         # writes scoring-tables/*.csv and copies the workbook and figure here
python scripts/build_deliverable.py   # the xlsx workbook
python scripts/build_figure.py        # scoring_compression.png
```

They were written on Windows and carry absolute input and output paths in their header constants (`REPO`, `SCRATCH`, `OUT`); edit those three lines before running elsewhere. `build_deliverable.py` and `emit_tables.py` also copy the workbook and figure into this folder, so re-running them here is safe.

Outputs of record are the CSVs in `scoring-tables/`; the workbook and figure are derived from them.
