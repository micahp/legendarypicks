# SLC V1.5 walk-forward protocol for the 2026 season, 2026-11-03

Status: proposed, not yet approved. Nothing in this file has been run. No 2026 forecast or result has been produced under it.
Branch: `slc-v1.5` (created from `slc-v1` at `6895c2e3`). Not pushed.

## 1. Owner rule

The 2026 holdout (`HOLDOUT-EXPOSURE-RECORD-2026.md`) allows a forward projection only under an explicit prospective protocol. The owner has chosen a week-by-week walk-forward:

- Predict week W with every game in that week locked before its result is read.
- Read the week W results, score them, and record them.
- Use only what is known as of each game's cutoff to predict week W+1, and repeat.

No week is scored in one batch after the fact, and no forecast is changed after its results are known.

## 2. Arms

- **V1**: `v1_full_stack` at its current committed code hash, frozen before week 1.
- **V1.5**: the mega version built on `slc-v1.5`. Each historical layer's prior is blended with the 2026 current season using the fixed N0/(N0+k) weight from `temporal_predeclaration.md`. Frozen before week 1.
- **Other arms**: the owner names them. The research plan lists P1 (coaching tendencies), P2 (player usage) and PBV1 (package sampler). Only arms that are integrated and frozen can run.

Every arm uses the same game list, the same cutoffs and the same seed list.

## 3. Per-game cutoff and availability

- **Cutoff:** kickoff minus 90 minutes (section 8).
- **Availability:** a 2026 result or box score counts as known only 10 hours after its kickoff (the availability lag assumed in `SLC-V2-M6-FREEZE-2026-11-02.md`). A game's own result is never an input to its own forecast.
- **As-of rule:** every input has a timestamp. An input is used only if its timestamp is before the target game's cutoff. An input that cannot be dated is excluded and listed in the manifest.

## 4. Weekly loop (run for W = 1 to 18)

1. **Freeze.** Record the SHA-256 of every code file each arm uses, the config, and the seed list, in a committed file, before the week starts.
2. **As-of extract.** Build one extract per game from the database, containing only inputs passing section 3. Write the extract to disk with its SHA-256. A full copy of the database is not used, because the disk cannot hold one per week.
3. **Forecast.** Run each arm on each game. Record outputs with their seeds.
4. **Lock.** Write the week's manifest (game id, cutoff, extract hash, code hashes, seed list, arm outputs, output hashes) and commit it. Results are not read before this commit.
5. **Reveal.** After every game in the week has ended and the availability lag has passed, read the results and score them against the locked outputs.
6. **Record.** Write the scores, referencing the manifest commit, and move to week W+1.

Weeks 1 to 8 are already played (the last game is Sunday 2026-11-01 or Monday 2026-11-02). Their results are already in the database and recorded in `HOLDOUT-EXPOSURE-RECORD-2026.md`, so their walk-forward is labelled retrospective-exposure in every report.

Week 9 is the first prospective week. Its games run from Thursday 2026-11-05 to Monday 2026-11-09. The first game is JAX at BAL, kickoff 20:15, so the week 9 cutoff for that game is 18:45 on 2026-11-05. The week 9 lock must be committed before that time.

Schedule source: `nfl_schedule` in `picks.dev.db` (kickoff `gametime` and `gameday`, season 2026, regular season). The protocol assumes `gametime` is Eastern Time. That has not been checked against the source.

## 5. Freeze rules

- Thresholds, metrics, arm definitions, cutoffs, the blend weights and the code are fixed before week 1.
- After any week's results are seen, no threshold, metric, arm, cutoff or code changes for the rest of the season.
- A change needed after results are seen is a new arm, reported separately, and not counted as the frozen comparison.

## 6. Metrics

From `research/SLC-V2-RESEARCH-PLAN-2026-11-02.md` section 8:

- Game winner: Brier score and log loss, with calibration by probability bucket.
- Points: distribution score (CRPS) for team points and total points, where the arm produces a distribution.
- Comparison with timestamp-valid market probabilities, where a market price existed before the cutoff.
- Intervals: game-clustered, reported season to date and per week.

Advance rule (owner, 2026-11-03): an arm advances over V1 only if its game-winner log loss and its Brier score are both lower than V1's over the scored games, and the game-clustered 95% interval for the log-loss difference is below zero. Weekly results are reported; the rule is applied to the season total, once, after week 18 (or after the last scored week if the season is cut short).

## 7. Known limits

- The database cannot be copied whole on this box (about 3.6 GB per copy). Reproducibility depends on the as-of extracts and their hashes.
- The Week 10 lock tooling (manifests, extracts, the streak-file rebuild) is not built. The context doc lists it as the schedule risk.
- V1.5 is not implemented yet. Only the branch exists.

## 8. Owner decisions (2026-11-03)

1. **Cutoff:** kickoff minus 90 minutes.
2. **Weeks 1 to 8:** run as labelled retrospective-exposure. Weeks 9 onward are prospective (the owner's answer was "run as labeled retrospective"; the schedule shows that weeks 1 to 8 are the only played weeks, so weeks 9 onward are not retrospective).
3. **Arms:** all arms: V1, V1.5, P1, P2 and PBV1. Not yet buildable on this branch: P1 and P2 hooks are not written, and the PBV1 hook exists only on `pbv1-integration-2026-11-02`. Each has to be ported and frozen before week 1.
4. **Advance rule:** section 6.
5. **Schedule:** week 9 first kickoff Thursday 2026-11-05 20:15 (JAX at BAL), so the week 9 lock is due by 18:45 that day. Week 10 first kickoff Thursday 2026-11-12 20:15 (WAS at NYG). Source: `nfl_schedule` in `picks.dev.db`. The Eastern Time assumption is still unchecked.
