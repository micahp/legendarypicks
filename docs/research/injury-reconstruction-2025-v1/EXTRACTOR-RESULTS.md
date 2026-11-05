# Pregame status extractor v1: gold-set results

Research only. Nothing here feeds the 2025 realism run, the shadow simulation, or any eligibility rule.

## What was built

- `extract_status.py`: a rule-based extractor (no language model). For each player and article it reads the official status table row when one exists on an on-topic page, and otherwise sentences from the JSON-LD article body. It abstains on anything it cannot place. Each result keeps the exact span, the rule that fired, and the route.
- `evaluate_gold.py`: scores the extractor against `gold/labels.csv`, writes per-item provenance to `gold/extractions_<split>.csv`, and writes `gold/final-test-results.json` on the single test run.
- `audit_labels.py`: a scheme check on narrative labels (see "Label audit" below).
- `compare_nflverse.py`: diagnostic only, against nflverse `injuries_2025`.

Extractor version: `rules-v1:fb0f89ef454c1005`. It was tuned on dev only and frozen before the one test run.

## Sample

154 items from 97 article URLs, stratified by route and game status class (`gold/sample.csv`, seed 20260505): 77 dev and 77 test. Strata: table rows (54), narrative sentences (80), mention-only (20). All 97 articles are strict (modified before the cutoff, per `article_evidence.csv`).

The sample is stratified by design, so these rates are not population rates. A population estimate needs each stratum weighted by its share of the 3,400-pair pool.

## Results, test split (one run, frozen extractor)

| Class | Precision | Recall | Notes |
|---|---|---|---|
| OUT | 8 of 9 (88.9%; 95% CI 56.5 to 98.0%) | 8 of 9 (88.9%) | one false OUT (G120) |
| DOUBTFUL | 1 of 1 (100%; CI 20.7 to 100%) | 1 of 2 (50.0%; CI 9.5 to 90.5%) | G122 missed |
| QUESTIONABLE | 9 of 9 (100%; CI 70.1 to 100%) | 9 of 12 (75.0%; CI 46.8 to 91.1%) | three abstentions |

Abstention: 37 of 77 (48.1%). Most abstentions are gold NONE items where the player's name is not in the article body, or the page is about another week or game. Those are correct abstentions, but they raise the rate.

## Results, dev split (tuning split, not evidence of generalisation)

OUT 13 of 13 precision and recall; DOUBTFUL 3 of 3; QUESTIONABLE 14 of 14. Abstention 26 of 77 (33.8%). The rules were fit to these items, so treat them as an upper bound.

## Gate

The target is at least 98% precision before automatic eligibility exclusions. **It is not met.** OUT precision is 88.9% on test, and its 95% lower bound is 56.5%.

A zero-error run would still need about 190 predicted OUT items to show a 95% lower bound of 98% (Wilson, n / (n + 1.96²) ≥ 0.98). This sample has nine. Automatic OUT exclusions must stay off.

## Errors on test

- **G120, false OUT (gold UNKNOWN).** The matched sentence is a numbered item ("3: The Vikings on Friday ruled out ..."), and the gold basis marks the body as truncated, with another team's teaser in the same item. The extractor has no item-boundary rule. This is the failure that matters most for precision.
- **G123, missed OUT.** The designation is written as "- Out" at the end of a line. The OUT patterns do not match a dash-separated bare "Out".
- **G122, missed DOUBTFUL.** The sentence says "doubtful after missing last week". The recap filter matches "last week" and drops a current designation.
- **G131, G133, abstained QUESTIONABLE.** The article title names neither this week nor this opponent, so the on-topic check abstains. **G020 (table), abstained QUESTIONABLE.** The title names a different week, so the table is not used.

Fixing these would be tuning on the test split. The test split has now been used once, so any change must be evaluated on a new held-out split.

## Label audit

Narrative labels of OUT, DOUBTFUL or QUESTIONABLE stand only if the article body has a sentence that names the player and states a designation word. Otherwise the designation came from related content or a sidebar, and the scheme says NONE. This was applied identically to dev and test before the test run, and it does not depend on the extractor.

Four labels changed (`gold/label_audit.csv`; the original labels are in `gold/labels_before_audit.csv`):
- dev: G062 QUESTIONABLE to NONE; G079 OUT to NONE
- test: G102 QUESTIONABLE to NONE; G110 QUESTIONABLE to NONE

Labels were written by one reviewer (the assistant), with no second reviewer. Labels were not changed on the basis of extractor output, except through the scheme audit above.

## nflverse diagnostic (not used for scoring)

101 of 154 items join to `injuries_2025` on GSIS id, week and team. Where the extractor gives a designation, it agrees with the final nflverse designation on 26 of 30 dev items and 18 of 19 test items. The disagreements are G003, G004, G071 and G080 (dev) and G009 (test). Final designations can change after the cutoff, so these are not extractor errors.

## Provenance per status

Each row in `gold/extractions_<split>.csv` has: item id, game id, team, week, GSIS id, player, article URL, route, predicted status, rule, exact span, gold label, `published_utc`, `modified_utc`, `cutoff_utc`, content state, and the extractor version.

## Next

1. Build a new held-out split from different weeks, with a sample drawn before any extractor change.
2. Fix the test failure modes above on dev (item boundaries, dash "Out", recap filter, title matching).
3. Have a second reviewer check labels, starting with the OUT and DOUBTFUL labels.
4. Re-run the full gate on the new held-out split. Do not run the shadow simulation until it passes.
