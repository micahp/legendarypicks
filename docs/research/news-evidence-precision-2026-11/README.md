# News evidence classifier: reviewed labels and measurements (2026-11)

Research and regression evidence for `news_evidence.classify`; no production inputs or workload files were changed. Scores use the modified classifier in the current working tree, based on local commit `72186cdb`. Review edits remain unstaged and uncommitted.

## Data and review

- `sample.json` contains 277 parsed updates from a RotoWire NFL capture acquired 2026-11-05T17:21:01Z. Capture SHA-256: `56de86d072e40edb3d3750d1cc0c179e1c7b74405d25af9c9f35cf8125b5807d`. The raw XML is not stored here.
- `labels.csv` was first labeled against `RUBRIC.md`, before the initial classifier run. An independent reviewer then labeled the 17 starter/coach-coded items and 11 borderline items blind to those codes, compared them with the file, and checked injury status scope. The reviewer made no file changes.
- A separate nine-item development slice is in `docs/research/news-evidence-development-2026-11-05/`. It contains only IDs absent from the evaluation capture; the independent reviewer found no label changes there.
- Two evaluation items (645952 and 645777) were seen in the earlier smoke run. The leave-two-out results are retained separately.

## Adjudications

The independent review found these starter-label changes:

- 645958: `SN` to no code. “Continue to lead the offense” describes a role but does not state a start decision.
- 645807: no code to `SE`. The unofficial depth chart lists Fehoko as a starting receiver for Sunday, which supports an expected start, not a confirmed decision.
- 645802: `SE` to no code. “No. 1 running back” describes a role; the text does not say he will start.
- 645928, 645885, and 645796: `SN` to no code. Assigning or planning kicking duties does not itself say the player is a starter.
- The other starter/coach codes were retained. 646006 is `SN`: “will resume” states a definite upcoming starting role, so its former `SN`/`SE` borderline flag was removed.

The injury-label corrections and scope decisions are:

- Add `ID` to 645994 and 645892. Both have `QUESTIONABLE` in the Injury Status field as well as a starter expectation.
- 645969 remains borderline with `ID;IO`: the field says `IR-R`, while the text says he is questionable for Thursday and still on IR pending activation.
- 645834 and 645810 remain borderline with no gold code. Their `QUESTIONABLE` fields conflict with roster transactions, and neither record has a team or upcoming game.
- 645791 remains borderline with `IO`. The field says `OUT`, but the item is about practice-squad IR and has no upcoming game, so the field is out of scope for `ID`.

The four retained borderline records are 645969, 645834, 645810, and 645791. The other seven reviewed borderline cases were resolved as described above.

## Results

Main scores exclude the four retained borderline records (273 updates). Precision and recall intervals are Wilson 95% intervals.

| Class | Gold | Emitted | TP | FP | FN | Precision (95% CI) | Recall (95% CI) |
|---|---:|---:|---:|---:|---:|---|---|
| starter_named | 4 | 4 | 4 | 0 | 0 | 4/4, 100% (51.0–100) | 4/4, 100% (51.0–100) |
| starter_expected | 10 | 9 | 9 | 0 | 1 | 9/9, 100% (70.1–100) | 9/10, 90% (59.6–98.2) |
| coach_confirmation_reported | 2 | 2 | 2 | 0 | 0 | 2/2, 100% (34.2–100) | 2/2, 100% (34.2–100) |
| injury_designation | 107 | 107 | 107 | 0 | 0 | 107/107, 100% (96.5–100) | 107/107, 100% (96.5–100) |
| injury_status_other | 54 | 54 | 54 | 0 | 0 | 54/54, 100% (93.4–100) | 54/54, 100% (93.4–100) |

With all 277 items included, `starter_named` is 4/4 precision and recall; `starter_expected` is 9/9 precision and 9/10 recall. Injury designation is 107/110 precision and 107/108 recall, and other injury status is 55/55 precision and 55/56 recall. The three injury-designation false positives are off-scope status fields on 645834, 645810, and 645791. Item 645969 is the text-only `ID` miss, with `IR-R` in its field. These four cases remain borderline because the first three have no upcoming game and the fourth has conflicting game-eligibility information.

The leave-two-out results are in `results-excluding-smoke-seen.txt`. The development-slice scores are in `docs/research/news-evidence-development-2026-11-05/results.txt`. The development slice has only one starter-positive update, so its 1/1 starter scores are a targeted check, not a stable precision estimate.

The one non-borderline starter miss is 645807: the current extractor does not yet recognize an unofficial depth-chart listing as an expected start. No pattern was added for this held-out wording. The held-out scores also exposed and then verified a narrow correction for “DNP to start Week 9,” where “start” refers to the beginning of the week, not a player starting role.

## Classifier changes

Starter claims are matched locally and attributed to the update subject using surname mentions and nearby pronoun/position references. A teammate mention no longer suppresses an explicit claim about the subject; a pronoun after a competing player remains attributed to that player. Contrastive clauses are split before negation is checked, so a negation in one clause does not hide a positive claim in another. Negation and hypothetical modals still suppress the claim they govern. “Might be named starter” remains hypothetical, while a coach-confirmed “would start” is treated as a reported decision. The phrase “DNP to start Week N” is treated as practice-status timing rather than a starter claim.

The classifier still reads injury codes from the structured status field; it does not extract a text-only `QUESTIONABLE` designation. The borderline-inclusive results expose that limitation and the stale/out-of-scope fields above. The labels now apply the rubric's upcoming-game scope, while the scorer reports the classifier's raw status-field output.

## Reproduce

```sh
/usr/bin/python3 scripts/nfl_sequence/measure_news_precision.py score
/usr/bin/python3 scripts/nfl_sequence/measure_news_precision.py score --exclude 645952 --exclude 645777
/usr/bin/python3 scripts/nfl_sequence/measure_news_precision.py score \
  --sample docs/research/news-evidence-development-2026-11-05/sample.json \
  --labels docs/research/news-evidence-development-2026-11-05/labels.csv
```

`score` reads frozen samples and labels only. `sample.json` is not regenerated by these commands.

The focused classifier suite passed 40 tests after these changes. The CRLF-aware `git diff --check` was clean.
