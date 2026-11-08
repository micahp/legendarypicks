# Ablation A freeze blockers, 2026-11-08

Reviewer: lead (PM review)
Subject: `SPEC.md` revision at `d0b613dc7`; determinism finding at `1b2a14d6a`
Verdict: **the spec revision is accepted. Two things block the freeze: rule 5 fails by construction, and the batch non-determinism breaks the paired design that the whole ablation rests on.**

---

## The revision is accepted

All four corrections landed, and landed well:

| Correction | What changed | Status |
|---|---|---|
| Code contradicted the spec | per-cell `obs(cell)` with shrinkage to the pooled rate, pseudo-count 100, stored in `obs_sack_cells.json` with query and sha256 | **accepted** |
| A confounded with C | substitution restricted to `pass_incomplete`, so no completion changes yardage | **accepted** |
| Bootstrap at the wrong level | 13 matchups resampled, then games within the drawn matchup; percentile intervals, 2,000 draws | **accepted** |
| Target band tighter than the observation | 2.5–3.0% band dropped; directional with an interval that must exclude zero | **accepted** |
| Turnover definition | gated on 1.098, raw-PBP figure demoted to a cross-check | **accepted** |

The substitution algebra is also right: with `q(cell) = max(0, (obs − r)/inc)`, the new sack share is `r + q·inc = obs` when `obs > r`, and nothing else moves.

---

## Blocker 1: rule 5 fails by construction

Rule 5 invalidates the run if "yards per team-game change by less than 1%". That cannot happen, because an incompletion gains 0 yards and a sack loses about 7, so the substitution has to reduce yardage:

| Quantity | Value |
|---|---|
| engine sack rate on dropbacks | 2.39% (1,697 sacks / 70,958 dropbacks, V2 team rows) |
| observed target | 6.88% |
| gap | 4.49 points of dropbacks |
| dropbacks per team-game | 35.5 |
| **extra sacks per team-game** | **1.59** |
| yardage lost at 7 yards per sack | **11.1 yards per team-game** |
| as a share of 384.6 scrimmage yards | **2.9%** (range 2.5–3.3% at 6–8 yards per sack) |

So the run will be declared invalid by rule 5 for a reason that is arithmetic, not a confounding defect. Note the direction: that 11 yards moves the engine *toward* the observed 327.8, so it is a useful side effect, not contamination.

**Fix before freeze.** Rule 5 should gate the thing that actually matters for non-confounding with ablation C, which is that the *non-sack* passing outcomes did not move:

- completions per dropback: unchanged (this is the real control)
- yards per completion: unchanged
- yards per pass attempt excluding sack yardage: unchanged
- sacks per dropback: rises to 6.9% (rule 1, restated)

Keep a team-game yardage diagnostic, but widen the tolerance to 4% and state that ~2.9% is expected arithmetic. Otherwise a correct implementation is guaranteed to report "invalid".

---

## Blocker 2: non-determinism breaks the paired design

`1b2a14d6a` records 14 refusals, 6 reproduced and 8 not, and — far more importantly — that **an exact rerun of the same 50-seed CIN-ATL command changed which seed failed**: seed 50 passed and seed 17 failed with a new error.

That is the serious finding, and it is established by the right experiment (same command, same tree, twice). It is not a Sunday-slate problem. It invalidates the ablation design, because a paired baseline-versus-ablation comparison assumes the same seed produces the same game in both arms. If the batch is not deterministic, any difference between arms is treatment plus run-to-run noise, and rules 2, 3 and 4 cannot be interpreted.

**Ablation A must not be frozen or run until determinism is settled.** Order of work: determinism, then freeze, then baseline.

### Two things to pin down before diagnosing

1. **Record the run identity for both identical-command runs.** The conclusion "same command, different result" is only as good as the claim that the tree, snapshot, artifact and inputs were identical. Save `git rev-parse HEAD`, the patch sha256, the snapshot sha256, the play-call artifact sha256, and the streak file sha256 for each run. If the extension was still running against the tree, the two runs may not have been the same build.

2. **The single-seed reruns are not a fair reproduction test** while the batch is non-deterministic. `run_failures.sh` invokes the simulator with `--games 1 --seed-start $s`, which is a different invocation from the batch's `--games 200 --seed-start 1`. So "did not reproduce alone" conflates two effects: batch non-determinism, and single-seed-versus-batch harness difference. The 8/14 figure should not be read as a cause until they are separated.

### The cheapest discriminating test

Take **ten seeds that passed** in the batch, rerun each alone with the same flags, and compare the rerun's final score, drive count and play count against the row the batch wrote for that seed. 

- If they all match, the single-seed harness is equivalent, and the 8/14 non-reproductions are batch non-determinism. That is a strong, clean result.
- If any differ, the harness is inequivalent and the reproduction test is void — fix the harness first.

Then attack the root cause. Ranked by how cheap they are to test:

1. **Hash randomization.** Run the same command twice with `PYTHONHASHSEED=0` in both. If the failure set becomes stable, the cause is iteration over a `set` or `dict` of strings somewhere in the sampler or the pool. One line to test, and a one-line fix (fix the seed, and sort iterations).
2. **State carried between seeds in one process.** Run the batch with `--games 1` repeatedly across the same seed range and compare to a single `--games 200` run. If the single-game loop is stable and the batch is not, the defect is cross-seed state.
3. **Caches keyed by something run-dependent.** The manifest already records an on-disk cache fingerprint; check whether any cache write is keyed by wall-clock, PID or process path.

Of the three, my prediction is hash randomization or cross-seed state, in that order. Both are testable in minutes and neither requires new data.

---

## Blocker 3: the spec's own input artifact is not committed

`SPEC.md` defines the observed sack rate "stored in `obs_sack_cells.json` with its sha256 and the query". No such file exists in the repo — `d0b613dc7` changed only `SPEC.md`. The ablation's primary input therefore cannot be pinned at freeze, and a reader cannot reproduce the per-cell rates the switch depends on.

Produce and commit it before the freeze: the per-cell query, the counts per cell, the shrunk rate used, and its sha256. Without it the freeze commit pins the code but not the input the code reads, which is the same class of gap as the uncommitted host tree.

---

## Sunday refusals: the mapping, and what it changes

Fourteen refusals over 2,600 games is 0.54%, up from 3 in 650 (0.46%), so the rate is stable and the extension did not make it worse. But the affected set is wider than the 50-seed pass suggested: **7 of 13 matchups** now carry at least one unresolved refusal.

| Matchup | Refusals | Reproduced |
|---|---|---|
| GB-NE | 4 (64, 96, 100, 190) | all 4 |
| ARI-SEA | 2 (196, 197) | both |
| DEN-CAR | 2 (186, 198) | none |
| DET-MIA | 2 (59, 117) | none |
| CIN-ATL | 2 (50, 69) | none |
| CLE-NO | 1 (29) | none |
| DAL-IND | 1 (47) | none |

Under the owner's rule — any unresolved legality failure blocks calling that matchup validated — **only 6 matchups are clean** (HOU-LAC, LA-WAS, LV-SF, NYG-PHI, NYJ-KC, TB-CHI), not all 13 and not the 10 implied by the earlier statement.

### The failures are two clusters, not fourteen bugs

| Signature | Count | Assertion |
|---|---|---|
| `field_goal_attempt` ends the drive but a play follows | 4 | `_play_chain`, `game_legality.py:82` |
| last drive ends with `field_goal_attempt` in Q4 at 0, which does not end the game | 3 | game-ending check |
| `field_goal_attempt` ends with no kickoff able to follow | 1 | kickoff-after-score check |
| overtime kickoff follows a drive that does not end regulation | 4 | `game_legality.py:398` |
| leaves down 1 but carries no yards gained | 1 | `_down_and_distance` |
| two kickoffs follow one drive | 1 | kickoff-after-score check |

**Eight of the fourteen involve `field_goal_attempt`**, and **five of the six reproduced failures are in that cluster** (ARI-SEA 196, 197; GB-NE 64, 96, 190). So the field-goal drive-ending and kickoff-after-score path is the single highest-value repair: it explains 8 of 14 refusals and 5 of the 6 records you can actually debug.

Start there, with the reproduced records. The `_play_chain` penalty-exemption asymmetry from the earlier handoff is still worth testing first on the four "play follows" cases, because it is a two-line change plus a test and it matches every previous validator fix.

The four "overtime kickoff follows a drive that does not end regulation" cases are a second, separate bug — none of them reproduced, so they should wait for determinism.
