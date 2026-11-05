# News evidence development sample (2026-11-05)

This development-only slice came from a RotoWire NFL capture acquired at 2026-11-05T18:42:32Z. The raw capture SHA-256 is `73d845cbb3d8e2584707f8e0240937f1abb595fe73c1b375a737e12940a2ec7b` (284 feed updates). It contains the nine IDs absent from the earlier evaluation capture. All 275 shared IDs, including one with revised analysis, were excluded. Selection used update-ID novelty only, not classifier output.

The frozen parsed records and labels are in `sample.json` and `labels.csv`. They use the rubric in `../news-evidence-precision-2026-11/RUBRIC.md`. An independent reviewer labeled all nine records blind to these codes and found no label changes. The reviewer noted one field/text conflict: 646054 has `QUESTIONABLE` in the field while the text says Murray will not play Monday; `ID` follows the field-based rubric.

The current classifier emits the sole starter-positive item (646053) as both `starter_named` and `starter_expected`, matching its direct assignment and “in line” language. It emits all five game-week injury designations in this slice. The measured output is in `results.txt`.

This sample has only one starter-positive update. Its 1/1 precision and recall for `starter_named` and `starter_expected` are a targeted development check, not stable rate estimates. The sample contains a conditional start for a different player and a kicker-duty description without a starter decision; both are excluded by the subject and claim rules. Pronoun and clause-negation behavior is covered by focused unit cases because this nine-item slice has no positive pronoun-based starter claim.

Score it with:

```sh
/usr/bin/python3 scripts/nfl_sequence/measure_news_precision.py score \
  --sample docs/research/news-evidence-development-2026-11-05/sample.json \
  --labels docs/research/news-evidence-development-2026-11-05/labels.csv
```
