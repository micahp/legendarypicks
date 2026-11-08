# Review: the validator fix for the six reproducible refusals (a5bd2161)

Reviewer: lead (PM review)
Subject: `a5bd21610` "Validator: blocked kicks are live, missed kicks can end the game, safety free kicks can expire the half"
Verdict: **the fix is correct and I reproduced the claims independently. One new coverage hole was introduced, and the fix changes what the published 200-seed distributions mean for two matchups.**

---

## 1. Claims verified independently, not taken on report

| Claim | Check I ran | Result |
|---|---|---|
| Validation only, simulation untouched | `git show --stat a5bd2161` | 3 files: `game_legality.py`, `test_game_legality.py`, `README.md`. No simulator file touched. **confirmed** |
| Unit tests pass | `python -m unittest test_game_legality -v` from `scripts/nfl_sequence` | **49 tests, OK** |
| All six saved records now pass | loaded each `refused-records/*.json.gz` and ran `game_legality.check()` | **6/6 PASS, 10 stages each** |

The rules as stated are also right on football: a blocked field goal does not end the drive because the ball is live; a fourth quarter that expires with the score untied ends the game whatever the last play was; a safety free kick that runs out the second quarter is followed by the second-half kickoff.

## 2. The changed test was wrong, and the change is legitimate

The old `test_the_game_ends_on_a_punt_before_the_clock_expires` asserted that a punt terminal on the last drive must be refused. I checked the fixture it operates on:

- last drive: `terminal=end_of_regulation`, `end_quarter=4`, `end_clock=0`, `points_scored_on_drive=None`
- final score: `A=20, B=26`, untied

A punt at 0:00 with the score untied does end the game, so the old test encoded a false rule and the replacement is correct. The companion test (`end_clock=12` must not end the game) keeps the guard honest, and I confirmed the real equivalent is still refused: setting GB-NE 96's last drive to `end_clock=30` is refused with "drive 20 ends at quarter 4 30, but its last play ends at quarter 4 0".

## 3. New coverage hole: a blocked kick's post-state is now completely unchecked

`_down_and_distance` gained `or outcome.get('field_goal_result') == 'blocked'` and returns before any progression check. The reason is clear — a blocked kick has `yards_gained = None`, which the check treats as a failure. But the exemption is too wide: it skips the whole down/distance check for that play, not just the missing-gain case.

Probe, on ARI-SEA 196 (which passes as saved):

```
blocked FG, drive 5 play 29
  state_before: down 4, yards_to_go 6,  yardline_100 29
  state_after : down 1, yards_to_go 10, yardline_100 63   (possession changed)
outcome: yards_gained=None, field_goal_result=blocked

set state_after.yards_to_go = 99        -> PASS (accepted)
```

Down 1 with 99 yards to go at `yardline_100` 63 is impossible — it must be `min(10, 63) = 10`. The old validator would never have reached this state, because it refused any blocked kick followed by a play. So the fix trades an over-refusal for an unchecked transition, in the exact region it just opened up.

Gross errors are still caught: setting `state_after.down = 5` is refused by the state-domain check. It is the progression that is unchecked.

**Recommended narrowing, before the next slate run.** Exempt only the condition that fails, not the check:

- if `gain is None` and the play is a kick (`field_goal_attempt`, `punt`, free kick), skip the gain comparison; or
- when possession changed on the play, require `down == 1` and `yards_to_go == min(10, yardline_100)` in the post-state; when it did not, run the normal progression against the recorded gain.

Either keeps the six records passing and closes the hole. A targeted test for each branch would satisfy the same standard the other three fixes met.

## 4. What this changes for the published Sunday numbers

Six of the fourteen refusals were **legal games wrongly refused**. That is the correct reading of this fix, and it has a consequence the batch does not yet reflect:

| Matchup | Refusals now known to be legal | Was excluded from |
|---|---|---|
| GB-NE | 4 of 200 | the GB-NE 200-seed table (196 used) |
| ARI-SEA | 2 of 200 | the ARI-SEA 200-seed table (198 used) |

So those two matchups' published medians and bands are computed over legal games that the validator threw away. The effect on a median is negligible, but the label "200 seeds" is wrong for them in a way this fix proves. Either re-admit those six records to a re-validated table, or mark GB-NE and ARI-SEA as 196 and 198 **validated** games. The other five affected matchups keep their refusals as unresolved.

Also note the fix is validator-only, so the host batches that already ran are unchanged. The 14 refusals stay recorded against the old validator; re-validating the saved records is what proves the six.

## 5. What is still open, unchanged

- **Four "overtime kickoff follows a drive that does not end regulation" refusals** (CLE-NO 29, DEN-CAR 198, DET-MIA 59 and 117). None reproduced, so there is no saved record to validate and no diagnosis. This is the fourth cluster and it is untouched by this fix.
- **Non-determinism.** Still the top item. It is why the eight non-reproducing failures cannot be attributed, and it still blocks freezing ablation A.
- **Ablation A freeze blockers** in `0bdeafef4` all still apply. This fix does not address any of them.
