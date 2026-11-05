# News evidence classifier: measured precision and recall (2026-11)

Research only. Nothing here changes `classify()`, the evidence it produces, or any workload input.

## What was measured

- **Instrument:** `news_evidence.classify` (commit `db89bd22`) applied to all 277 updates in one RotoWire NFL capture. The capture's sha256 is `56de86d0...`, acquired 2026-11-05T17:21:01Z, feed dates Nov 3 to Nov 5 2026. The raw XML is not in the repo; `sample.json` holds the parsed text the classifier saw, with the other-player surnames `build()` would have used, and the capture's sha256.
- **Labels:** `labels.csv`, one row per update, written by hand from the text following `RUBRIC.md`. Labels were written before `classify` was run on the sample.
- **Scoring:** a (update, class) pair counts as emitted when `classify` returns the class, and as gold when the labels include it. Precision = TP / emitted. Recall = TP / gold. Intervals are Wilson 95%.

## Limits

- **One capture, about two days of feed.** RotoWire's NFL feed holds roughly 48 hours. No archive of RotoWire NFL items exists on this box: `backend/data/rotowire-archive` holds props and market data, and `news_items` has no RotoWire NFL rows. This is one point in time, Week 9 only.
- **One reviewer, who also wrote the rules.** The labels are not independent. Before any number here is used as a gate, a second reviewer should label the 17 items with a starter or coach code and the 11 borderline items.
- **Two items were seen before labelling.** The classifier output for update 645952 (Fagnano, "still in line to start") and 645777 (Fagnano, "named Week 9 starter") appeared in the earlier smoke run. `results-excluding-smoke-seen.txt` leaves them out.
- **The starter classes have 1 to 9 gold positives.** Treat those rows as counts, not rates.

## Results: main set (borderline items excluded, labels as frozen)

266 items scored. Full output: `results.txt`.

| class | gold | emitted | TP | FP | FN | precision (95% CI) | recall (95% CI) |
|---|---|---|---|---|---|---|---|
| starter_named | 3 | 1 | 1 | 0 | 2 | 1/1, 100% (20.7-100) | 1/3, 33.3% (6.1-79.2) |
| starter_expected | 9 | 3 | 3 | 0 | 6 | 3/3, 100% (43.8-100) | 3/9, 33.3% (12.1-64.6) |
| coach_confirmation_reported | 2 | 1 | 1 | 0 | 1 | 1/1, 100% (20.7-100) | 1/2, 50% (9.5-90.5) |
| injury_designation | 105 | 107 | 105 | 2 | 0 | 105/107, 98.1% (93.4-99.5) | 105/105, 100% (96.5-100) |
| injury_status_other | 54 | 54 | 54 | 0 | 0 | 54/54, 100% (93.4-100) | 54/54, 100% (93.4-100) |

**Sensitivity.**
- Borderline included (277 items): starter_named recall 1/8; starter_expected precision 3/3, recall 3/10; injury_designation precision 105/110 (95.5%), recall 105/106 (99.1%); injury_status_other recall 55/56 (98.2%).
- Excluding the two Fagnano items seen before labelling (264 items, `results-excluding-smoke-seen.txt`): starter_named has no emitted positive, so precision is undefined and recall is 0/1; starter_expected precision 2/2, recall 2/8; coach_confirmation_reported has no gold positive left. **The 100% starter precision in the main table rests on one item.**

## Label correction found after scoring (not applied to `labels.csv`)

The two false injury positives in the main set are both my labelling error. Items 645994 and 645892 (Drew Lock, field `QUESTIONABLE`) were labelled SE only. `RUBRIC.md` says a QUESTIONABLE field is an injury designation (ID), and every other QUESTIONABLE-field item in the main set was labelled that way. The frozen labels were kept so the table above is what the labels said. With the rubric applied, injury_designation is 107/107 precision and 107/107 recall in the main set. The starter rows do not change.

## Why the starter claims are missed

The main set has 9 starter or coach misses. Each comes from one of three design rules or a lexical gap. The disagreement list in `results.txt` has the spans.

1. **Last-name guard (4 misses).** Notes and analysis sentences are attributed only when they contain the player's surname. Sentences that refer to the player as "he", "the 26-year-old" or "the 2022 second-round pick" are dropped: Holland 645978, Pitre 646008, Boettcher 645970, Ioane 645835.
2. **Multi-name guard (4 misses).** A sentence that names another player on either team is dropped, because it may carry that player's status. This dropped the coach-named Fagnano sentence (645952: starter_named and coach_confirmation_reported), Fagnano 645771 ("the favorite to start", which also names Jackson and Huntley) and Lock 645994 (which also names Darnold).
3. **Sentence-level negation (1 miss).** Antonio Johnson 645965 reads "he may not be back to 100 percent, but Johnson should be back in his starting role". The "not" in the first clause suppresses the second.
4. **Lexical gaps.** The expectation words are `expected`, `projected`, `likely`, `set`, `slated`, `should`, `favored` and `in line`. Holland's "will be back in his starting role" has no such word and no "named", so it would be missed even with the guard relaxed. "Favorite to start" is not matched.

These guards are conservative on purpose. A miss is safer than a status attributed to the wrong player, which is the rule the paste sets. But the evidence layer under-reports starter claims that were published. Any relaxation should be measured on a new labelled sample, not tuned on this one.

## Injury designations: a defect in the status field

Three items carry an injury designation for players who are not on the active roster. The classifier emits `injury_designation` for each because it reads the status field alone:

- 645834, Tre Brown: QUESTIONABLE after being removed from IR and becoming a free agent.
- 645810, Bub Means: QUESTIONABLE while on the practice-squad injured list.
- 645791, Kenny Yeboah: OUT while on the practice-squad injured list. Text says practice-squad IR, unavailable four games.

These are borderline items, so they are excluded from the main table and counted in the borderline-included row. Before any use beyond logging, `injury_designation` should be gated on active-roster membership.

## Injury text is not measured

The classifier reads injury designations only from the status field. The sample has one text-only designation, 645969 (Randall: field IR-R, text "officially listed as questionable"), and it is borderline. Recall for designations written in text is therefore not measured.

## Borderline items (11)

Kicker role (645928, 645796, 645885); "lead back" (645802); "continue to lead the offense" (645958); "will resume his role as one of its starting cornerbacks" (646006); the field cases (645969 Randall, 645834, 645810, 645791); and a depth-chart listing (645807). They are excluded from the main table. The rubric says "could start" is not a claim, so hypothetical sentences are not borderline; they are simply not gold.

## Reproduce

```
cd scripts/nfl_sequence
python3 measure_news_precision.py sample --capture-xml <capture>.xml --db <picks.dev.db>   # writes sample.json
python3 measure_news_precision.py score                                                    # results.txt
python3 measure_news_precision.py score --exclude 645952 --exclude 645777                  # results-excluding-smoke-seen.txt
```

`score` reads only `sample.json` and `labels.csv`. It stops if a label has no sample item or a sample item has no label.

## Next

1. Second reviewer on the 17 starter or coach items and the 11 borderline items, then rescore.
2. A labelled series, not a snapshot. The feed holds about 48 hours, so captures have to be taken regularly to build one. Nothing in this folder schedules them.
3. Gate `injury_designation` on active-roster membership before any use beyond logging.
4. Decide the guards only on a new labelled sample.
