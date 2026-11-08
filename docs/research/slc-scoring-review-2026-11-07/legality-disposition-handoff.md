# Handoff: the four legality issues, the three Sunday refusals, and the uncommitted host tree

Date: 2026-11-07
From: lead (PM review)
For: the server agent working the Sunday pass and the simulator host
Status: answers the two questions you have asked twice; gives each refusal a disposition path

This file exists because you have asked twice for "the four legality issues from the review" and twice been sent a status message instead of a source. Everything below is traced to a file, a line or a commit in this repo.

---

## 1. The four release blockers

These are the four the owner named. They are not four unrelated bugs: **three of them are the same class** — what happens at a period, drive or possession boundary when the clock expires or a score changes. Treat them as one contract, one property test, and four assertions.

| # | Blocker | Where the check lives | Evidence of state | Status |
|---|---|---|---|---|
| 1 | **Overtime winning-touchdown try.** A touchdown on the first overtime possession ends the game; no try is attempted. | `test_game_state.py` line 1312 `class OvertimeCompletedRules`, line 1335 `test_a_winning_touchdown_from_a_tie_takes_no_try` | The regression test is inside `9667cbc1` and passing (audited) | **CLOSED**, but it must be re-run on the frozen build |
| 2 | **Adjacent-play state continuity.** Each play must start from the exact state the previous play left: same possession, same scores and timeouts, the clock continuing, and no play after a drive-ending outcome. | `game_legality.py` `_play_chain`, lines 77-102; failing assertion line 82 | Base check is in `9667cbc1` and is the one catching the Sunday refusals | **OPEN — live, 2 failures** |
| 3 | **Clocks between possessions.** The clock continues across a change of possession; a period only changes when the previous play ends the period; the next period opens at its full length. | `game_legality.py` lines 90-100 (change of ends) and the overtime/regulation boundary at lines 397-398 | Base checks in `9667cbc1`; the release-blocker fixes for this and item 4 sit **after** `9667cbc1` and exist only inside `executed-code.patch` | **OPEN — live, 1 failure** |
| 4 | **Final-clock reconciliation.** The final clock, the final score and the regulation ending must agree with the drives. | `game_legality.py` line 475 onward, `_game_ending` | Core check inside `9667cbc1`; later fixes only in the patch | **OPEN, instrument not yet settled** |

Fixed so far, all validator-side (games that were legal and the validator refused): `c0cb16a5`, `d93b0b4e`, `47707c33`, `0febeff7`, rolled up into `9667cbc1`.

### The one thing to do first on items 2 and 3

`_play_chain` is the **only** one of the three play-level checks with no penalty exemption:

- `_play_chain`, line 80: checks `DRIVE_ENDING_OUTCOMES` flags on the previous play with no guard.
- `_down_and_distance`, line 108: `if outcome.get('penalty') ... return`.
- `_play_clock`, line 134: `if outcome.get('penalty') ... return`.

If either field-goal play carries `outcome.penalty`, the drive legitimately continues and the validator is wrong — the fix is a two-line guard plus a regression test. **Check that before anything else**; it is the single cheapest resolution available for two of the three refusals, and it matches the pattern of all four previous validator fixes.

---

## 2. The three Sunday refusals: disposition

None of the three is in the distributions, and none was blocked. That is correct handling. But "refused by the validator" is not the same claim as "illegal game", and right now the bundle does not say which. The refusal rate is 3 of 650 seeds (0.46%), which is negligible for medians and bands and therefore **not** a reason to hold the slate — but two of the three sharing a signature makes it a pattern, not noise.

Map them to the assertions:

| Refusal | Assertion | Signature |
|---|---|---|
| CIN-ATL seed 50 | `_play_chain` line 82 | drive 6: `field_goal_attempt` ends the drive, play 59 follows |
| DAL-IND seed 47 | `_play_chain` line 82 | drive 19: `field_goal_attempt` ends the drive, play 131 follows |
| CLE-NO seed 29 | line 397-398 | overtime kickoff follows drive 23, which does not end regulation |

### Disposition protocol

For each of the three seeds, export the offending drive with every play's `sequence`, `state_before`, `state_after`, and `outcome` (including `penalty`, `clock_runoff_seconds`, `quarter`, and each drive-ending flag). That is a small dump: three drives. Then classify each into exactly one of:

1. **Legal game, validator too strict.** Fix the validator, add a regression test naming the seed and drive, and re-admit the seed to the distribution under a new batch label. Do not silently re-admit it into `n50`.
2. **Illegal game, engine defect.** Fix the engine, add a regression test, and record the seeds as permanently failed. The validator is doing its job.
3. **Recording-convention mismatch.** The engine appends something to a drive that the validator treats as a play in that drive (a post-score kickoff is the obvious candidate). Fix the export contract, not either behaviour, and say so in the bundle.

Each refusal ends with one of those three lines written down. That is the disposition.

### Predicted outcome, stated so it can be falsified

My prediction: CIN-ATL 50 and DAL-IND 47 are case 1 or 3, not case 2, and CLE-NO 29 is case 2. If both field-goal refusals turn out to be case 2 (a genuinely illegal play after a made field goal), that is a real scoring-mechanism bug and it should be escalated above the slate.

---

## 3. The uncommitted host tree

This is the blocker that invalidates every batch until it is fixed. The audit of the smoke bundle established:

- `executed-code.patch` in the bundle is **byte-identical to the committed `9667cbc1`→`2f87d817` diff**, so labelling it "uncommitted" is wrong.
- Applying that patch to `9667cbc1` **cannot reproduce the recorded tree**, because every seed header pins `pregame_snapshot.py` to its HEAD hash while the patch leaves that file at its 9667 version.
- The patch hash in the manifest only matches after CRLF→LF normalisation; the shipped file hashes differently on a normal Windows checkout.

Two acceptable fixes, in order of preference:

**Preferred — commit and push the host tree.** On the host:

```
cd /root/lp-slc-v2-sim
git rev-parse HEAD                      # record this
git status --porcelain=v1               # record this
git checkout -b research/slc-v2-host-freeze-2026-11-07
git add -A                              # this is the host's own checkout, not a shared one
git commit -m "Freeze the Sunday simulator tree as executed"
git push origin research/slc-v2-host-freeze-2026-11-07
```

Then every batch records that branch and that commit instead of a patch.

**If the host must not branch**, export a tree-reproducing patch:

```
cd /root/lp-slc-v2-sim
BASE=$(git rev-parse HEAD)
git add -N .                            # intent-to-add, so new files enter the diff
git diff --binary HEAD > /tmp/host-tree.patch
git reset                               # undo intent-to-add; working tree untouched
sha256sum /tmp/host-tree.patch
echo "$BASE"
```

Commit four artifacts together: `BASE`, `git status --porcelain`, `/tmp/host-tree.patch`, and its sha256. A reader must be able to run `git checkout $BASE && git apply host-tree.patch` and get the executed bytes. The current bundle fails that test.

Also record the **play-call artifact hash** explicitly. The bundle cites `27c02afd…`, which matches no file in this repo (the repo copy hashes `6ba495f1` raw). Either the host artifact differs from the committed one, which is a second reproducibility gap, or the hash is wrong.

---

## 4. The seeds 51-200 extension: one time-sensitive risk

The extension is running against the **currently uncommitted host tree**. Two consequences:

1. **Do not change the host tree until the extension finishes.** If the host code is edited — including to fix any of the three refusals — seeds 51-200 would come from a different build than seeds 1-50, and the combined 200-seed distribution would be a mixture of two engines. That is not an extension; it is two batches.
2. **Capture the tree identity for the extension now**, not afterwards. If the run finishes and the tree has since changed, you can no longer state what produced it.

If a refusal fix is needed before the extension completes, let the extension finish on the current tree, then start a new labelled batch from the fixed build. Do not splice.

Finally: when the 200-seed table is published, print the build identity and the measured spread caveat on it. The engine's predictive spread is 0.79 to 0.88 of observed, so the bands are real bands around a narrower process than real football. A 200-seed band from this build is an engineering measurement, not a forecast.
