# SLC penalty source and sack audit

Date: 2026-11-10. This is an offline data and model audit. It did not modify the pinned SQLite database or run game seeds.

## Historical penalty PBP extract

`penalty-opportunity-plays-1999-2026.csv.gz` contains 1,300,819 keyed play-by-play rows from nflverse's season files for 1999–2026. It retains no-play, deleted, aborted, special-teams, and unknown-status rows so later work can state and apply its own opportunity denominator. It does not infer that a null penalty value means no penalty, and it does not infer acceptance or enforcement from a penalty flag.

The source files contain 92,626 rows with `penalty=1`, 1,167,343 with `penalty=0`, and 40,850 with a null penalty field. `first_down_penalty=1` appears on 25,136 rows; 40,850 rows have a null first-down-penalty field. These counts describe the pinned PBP rows, not accepted penalties or unique enforcement events. Per-season counts and all source hashes are in `manifest.json`.

### Field coverage for team-level research

`penalty-field-coverage.json`, produced by `audit_coverage.py` in bounded chunks, reports every season separately and records the compressed input hash. Across the extract, all 92,626 flagged rows have a committing team matching one of the recorded sides, 92,451 have a penalty type, and 88,126 have a player ID. These are field-presence checks, not verification that the foul was accepted or enforced correctly. There are 117,634 `no_play` rows, of which 67,522 carry a penalty flag; removing all no-play rows would discard those flagged records. `no_play` alone does not identify the timing or acceptance of a foul.

Among run, pass and `no_play` rows with both teams, a valid down, distance, field position, and game clock, 988,198 of 989,457 have a known 0/1 penalty flag. This is a **candidate source-row cohort**, not yet a validated count of independent offensive opportunities; special-teams opportunities, multiple fouls, repeated administrative rows, and next-state reconstruction require separate handling. The extract does not contain play descriptions, acceptance/decline, enforcement details, or historical acquisition timestamps. Those must come from additional evidence before building or grading a legal enforcement model; missing fields must remain unknown. The 1999–2000 source remains exploratory as specified in the protocol.

### Description evidence in the full source

The full pinned parquet files include descriptions and `order_sequence`, unlike the compact extract. `audit_source_descriptions.py` checks every annual file against the original manifest hash and counts literal text markers in all rows, including rows whose penalty flag is zero or missing. The resulting per-season counts are in `penalty-description-coverage.json`.

The audit processes 32,768-row Arrow batches and uses vectorized Arrow string and count kernels, so memory stays bounded by one batch instead of the full 1.3-million-row corpus. Hash verification remains enabled. The optimized script reproduces the checked-in counts exactly; on this host, a full scan took 5.18 seconds and peaked at 165,428 KiB RSS.

Across 1999–2026, descriptions in 12,762 rows contain “declined”: 10,735 have `penalty=0`, 256 have an unknown penalty flag, and 1,771 have `penalty=1`. Descriptions in 1,705 rows contain an offsetting marker: 423 have `penalty=0`, 1,269 have unknown penalty status, and 13 have `penalty=1`. Thus a corpus selected only by `penalty=1` omits most descriptions with these markers. In 2025, 524 descriptions contain “declined,” including 437 with `penalty=0` and 10 with unknown status.

These are **text-marker counts**, not verified foul or adjudication totals. A description can discuss multiple fouls with different dispositions: 4,075 flagged rows mention a penalty more than once, and enforced and declined markers can coexist. All 92,626 flagged rows have a description, while 85,998 have a non-null `order_sequence`. Neither word matching nor the presence of an ordering field proves a legal enforcement spot, an official statistical result, or a reconstructed next state. Exact foul segmentation and independent validation against the official record remain necessary. The source files also do not establish when their contents were first available historically.

The script also triages descriptions containing exactly one penalty mention and exactly one disposition marker: 88,429 have an `enforced` marker, 10,774 have a `declined` marker, and 3 have an `offsetting` marker. It leaves multiple mentions, conflicting markers, and missing markers ambiguous. These counts cover all source rows, not just rows with `penalty=1`; they are candidates for manual and official-record validation, not training labels or proof that all fouls have been captured.

### Manual official-record cross-check

`official-sample-validation-2016-2025.json` checks ten plays against official GSIS gamebooks: [CAR–DEN in 2016](https://www.nflgsis.com/2016/REG/01/56901/Gamebook.pdf) and [TB–DET in 2025](https://www.nflgsis.com/2025/REG/07/59949/Gamebook.pdf). The sample contains twelve foul events: seven accepted, three declined, and two offsetting. It confirms three data issues that matter for labels: one play contains two fouls with different dispositions while scalar fields encode only one; declined-only fouls appear in descriptions with `penalty=0` and null scalar fields; and an offsetting-foul row has a null penalty flag. Selected accepted no-play rows have `play_deleted=0`, so that field cannot stand in for play status. The following effective source state agrees with the official sequence in all ten sampled cases, including first downs awarded on third and fourth down, a repeated false-start down, a nullified offensive pass-interference play, offsetting fouls, and enforcement after a punt.

This is a small manual sample from two games. It validates those source-row mappings and transitions, not field meaning or completeness across seasons. Do not use it as a representative training set. Reproduce the pinned-source check with:

```bash
backend/venv/bin/python docs/research/slc-v2-penalty-opportunities-2026-11-10/audit_official_sample.py \
  --manifest docs/research/slc-v2-penalty-opportunities-2026-11-10/manifest.json \
  --schedule /root/lp-snapshots/nfl-backfill-2026-10-27/raw/schedules/games.parquet \
  --output /tmp/official-sample-validation-2016-2025.json
```

The all-season `penalty-clause-coverage.json` audit separately parses literal foul clauses. It found 105,308 rows with at least one parseable clause and 109,352 clauses across 1999–2026. There were 3,864 rows with multiple parsed clauses and 95 penalty-word rows with no parsed clause. In 2025, scalar `penalty_team`/`penalty_type` fields match at least one parsed text clause on all 3,559 `penalty=1` rows; five match a later clause rather than the first text clause. In 2026, 1,764 of 1,765 flagged rows match some parsed clause. Across all years, 3,043 flagged rows do not match a parsed clause; most are in older sources where penalty type or team identity is incomplete or uses a different team code.

Do not compare `penalty_yards` with a foul's stated enforcement distance: the [nflfastR data dictionary](https://cloud.r-project.org/web/packages/nflfastR/refman/nflfastR.html) defines it as yards gained or lost by the offense from the penalty, while `penalty_type` is described as the first penalty in the play. These source fields do not encode every foul in a multi-foul play. The clause audit is source-internal and exploratory; it does not turn text into official training labels.

`audit_ordered_states.py` checks whether a flagged row has a unique within-game `order_sequence` and a following source row with team, down, distance, field position, period and clock present. Across all years, 85,878 of 92,626 flagged rows are in games with unambiguous recorded ordering and have a following source row; 81,225 also have all those fields on that following row. Eleven games contain duplicate order values and are excluded from these counts. In 2025, the counts are 3,559 and 3,371 of 3,559 flagged rows; in 2026, 1,765 and 1,694 of 1,765. Results and source hashes are in `penalty-adjacent-state-coverage.json`.

These are **adjacent-row coverage checks**, not reconstructed or validated enforcement transitions. The next source row can be administrative, begin a different possession, or follow a period boundary. The check does not establish whether a play counted, whether a first down was awarded, or which clock rule applied. Those cases need adjudication and independent validation before the model can use them as legal state transitions.

### False-start state consistency

`audit_false_start_states.py` checks a restricted case against the immediately following source row: a single explicitly enforced offensive false start, five yards, no play, away from the half-distance region. It excludes duplicate ordering, missing state, changes of possession, period or score, and multiple or declined fouls. For comparable rows, it checks that the down remains the same, yards to go and distance to the goal increase by five, and the clock does not move backward. The pinned 2025 data has 614 candidates, of which 578 have a complete comparable next row; all 578 match. The pinned 2026 data has 291 candidates, of which 269 have a complete comparable next row; all 269 match. The remaining rows are not classified as failures. Full counts and source hashes are in `false-start-state-audit-2025-2026.json`.

This is a source-internal consistency check, not independent verification of the official record, nor proof of correct clock enforcement. It does not establish legal outcomes for other foul types or for excluded false starts. The sources are current retrospective files, not proof of historical availability at kickoff.

## 2026 penalty-field repair

The original database remains byte-for-byte unchanged: `picks.dev.db` SHA-256 `1a775208bc6e38763ef59c38a6cc79bda3636007feb8c6dc44f085f668341daa`. Its 2026 `penalty` value is null on all 21,018 rows, and it has no `first_down_penalty` column.

`penalty-source-overlay-2026.csv.gz` is the separate, keyed source overlay. It uses the pinned 2026 parquet SHA-256 `5edd7c42ed3f116f7e8914594c536088c337052fa53552ba7947499ba0f9f1b5`, joined on season, week, game ID, and play ID. The source has 21,191 unique rows: all 21,018 database keys match, with no duplicate keys, database-only keys, or week mismatches. The source has 173 additional rows that are absent from the simulation database. Among matched rows, source `penalty` is 0 on 18,634, 1 on 1,750, and null on 634. The full source has 639 null penalty values.

The same-source 2026 walk-forward audit uses only source-confirmed `penalty=0` test rows. It excludes source `penalty=1` and null-status rows from test scoring. For current-season adaptation, it supplies known statuses to the existing E1 pool builder, which excludes confirmed penalties; it also removes null-status rows before adaptation. The 173 source-only rows remain outside the audit because they are absent from the database-backed model population.

| 2026 test audit | Corrected overlay | Old null-status input, same test cohort |
| --- | ---: | ---: |
| Supported event rows | 15,061 | 15,061 |
| League event log loss | 0.518545 | 0.518545 |
| Offense-only event log loss | 0.524845 | 0.524899 |
| Defense-only event log loss | 0.524872 | 0.524840 |
| Matchup event log loss | 0.531319 | 0.531340 |

Lower log loss is better. Correcting the penalty labels changes some 2026 adaptation rows, but this common-cohort evaluation shows almost no overall event-score change. The league baseline remains better than the team-adjusted alternatives. This does not show that the ingestion defect is harmless in other outcomes or subgroups. It shows that this 120-game event audit does not support a broad accuracy gain from the mapping correction alone.

The full corrected event, yardage, third-down, and fourth-down sensitivity results are in `conditional-audit-2026-overlay.json`. The audit script is `audit_2026_penalty_overlay.py`.

## Sack audit and the saved 10K run

The corrected 2026 walk-forward sack audit scores 8,200 source-confirmed dropbacks across the 120 target games. Actual sack rate was 6.622%; the league estimate was 6.555%, and the offense×defense estimate was 6.512%. The overall rate is close, but the team gaps remain:

| 2026 team context | Observed | Matchup estimate | Dropbacks |
| --- | ---: | ---: | ---: |
| Minnesota offense, sacks taken | 9.95% | 7.52% | 211 |
| Minnesota defense, sacks forced | 11.42% | 6.84% | 219 |
| Buffalo offense, sacks taken | 6.07% | 5.97% | 214 |
| Buffalo defense, sacks forced | 5.45% | 6.23% | 275 |

The 2026 source correction barely changes these same-cohort estimates. For Minnesota offense, matchup probability is 7.516% with the corrected overlay versus 7.508% under the old null-status adaptation; for Minnesota defense it is 6.836% versus 6.891%. So the missing penalty field is a real ingestion defect, but it does not explain the Minnesota sack gap in this audit.

I also rebuilt the cutoff-specific BUF–MIN Week 9 current-season team-outcome table. At the 90-minute cutoff (5:45 p.m. CT), the database supplied 21,018 rows from 135 completed games in its schedule window. The corrected adapter removes 634 unknown-status rows. Of the 20,384 remaining known-status rows, 1,750 are confirmed penalties and 18,634 are confirmed non-penalties. None of the penalty rows can enter the E1 sampling pool: 327 reach the classifier and are explicitly rejected there; the other 1,423 fail the earlier unsupported-play-type or invalid-down filter. The 18,634 non-penalty rows still pass through the other E1 eligibility filters. The old all-null path could treat penalty status as clean for rows that pass those filters.

Across 61 supported team/event/cell combinations for sacks, three situation cells had one penalty-tagged sack each that affected the old table. For example, Minnesota offense's sack multiplier in second-and-6–9 at the 30–49 yardline band is 1.046 with the corrected data and 1.531 under the old null input. Minnesota defense's multiplier in first-and-10+ at the 50–59 band is 0.750 versus 1.209. These are sparse, one-play cells. The maximum ratio change is not a final sack probability; after the other layers and normalized event draw, the effect depends on how often those cells occur. See `week9-sack-ratio-diff.json` and `audit_2026_week9_sack_ratio_diff.py`.

The saved run's box-score sidecars reveal a provenance issue. All 40 worker files were checked. Seeds 200001–201000 have configuration hash `1e494482…`; seeds 201001–210000 have `91118658…`. The first group used the clean committed runner. The later group records a dirty producer worktree, a different producer-file hash, reference hash, snapshot hash, and exact-yardline artifact hash. Enabled layer names match, but the two groups are not one identical model identity. The dirty producer file is not retained, so its exact code diff cannot be reconstructed from the saved artifacts.

| Saved-run worker group | Completed valid games | Minnesota sacks / dropbacks | Buffalo sacks / dropbacks |
| --- | ---: | ---: | ---: |
| Seeds 200001–201000, clean code hash | 1,000 | 1,554 / 39,963 = 3.89% | 697 / 39,430 = 1.77% |
| Seeds 201001–210000, dirty code hash | 8,991 | 13,190 / 362,097 = 3.64% | 6,506 / 359,766 = 1.81% |

The overall 9,991-valid-game mean is still approximately 3.67% for Minnesota and 1.80% for Buffalo, but it combines those two identities. Do not use it as a single frozen-configuration result. The per-configuration calculation reads the saved box-score rows; it did not replay or regenerate seeds. See `saved-10k-sacks-by-config.json`, `saved-10k-layer-manifest.json`, and the copied run manifest/summary.

### Engine probability funnel and support

The exact SLC-v2 profile for the first worker confirms that these layers were enabled: score-clock play calling; team offense/defense outcome weights; formation/personnel; coverage; player-conditioned outcomes; decision labels and row filtering; exact-yardline outcomes; team/league streaks; playbook priors; quarterback decisions; player-share sampling; and D1 workload. The machine-readable layer and input hashes are in `saved-10k-layer-manifest.json`.

The sampler selects a run or dropback first. Within a dropback, its situation-cell event counts supply the starting sack and incompletion weights. It multiplies available formation, coverage, streak, decision-label, team, and player event ratios, then normalizes and chooses an event. Missing support can leave a multiplier at 1.0, use a backoff pool, or restore the base event distribution when all conditioned weights are zero. The saved run reports 5,143,725 aggregate fallback counts; 4,581,028 were missing decision categories. It also reports 195,575 exact-yardline source misses, 101,471 streak misses, 18,655 coverage source misses, 1,485 passer no-history cases, and 5,997 rusher no-history cases. These are fallback counter instances, not failed games.

For sack-specific team support, missing prior cell/event evidence caused the offense or defense multiplier to fall back for sacks 8 times for Minnesota's offense, 9 times for Minnesota's defense, 38 times for Buffalo's offense, and 8 times for Buffalo's defense. The 10K run did not enable `restore_sack_mass`. As described above, that correction is conditional on an incomplete being selected, skips the backoff path, and computes its substitution probability from base cell shares rather than the already weighted shares. Enabling it is not a validated fix.

The saved run contains box scores and aggregate counters, not ordered play transitions or each normalized event-weight vector. Therefore it cannot tell us how much each active modifier moved the sack probability on every dropback. The corrected historical audit establishes the model probabilities on observed 2026 situations; the saved simulation establishes final outcome rates. The gap between them may also reflect the simulator's generated situation mix. Exact per-stage attribution needs play-level trace output in a future run; no seeds were rerun for this audit.

## Sack probability path

In `scripts/nfl_sequence/slc_playcall.py`, the engine first chooses run or dropback from the score-clock play-call model. Conditional on a dropback, the historical situation-cell event counts provide the starting sack/incompletion mass. The event weights can then be changed by formation, coverage, streak, decision labels, team offense/defense ratios, joint transition ratios, and player event ratios. The normalized weights select the event. Candidate-row filters and player row weights run after that event choice; for sacks, the player row weight changes sack-yardage selection, not the already selected event class.

Sparse-support behavior matters. Outcome backoff can replace the exact-cell candidate pool; missing team/event evidence uses ratio 1 and records a fallback; if all conditioned weights are zero, the sampler returns to its base event counts. The 10K worker records include many decision-category, coverage, streak, exact-yardline, and player-support fallbacks. They do not preserve ordered play transitions or every pre-normalization event weight, so they cannot identify an exact per-game probability drop at each stage without replaying seeds.

`restore_sack_mass` was **off** in the saved 10K BUF–MIN run. It only runs after an incomplete-pass event was drawn, only when the exact-cell path is used, and only when that cell has sack candidates. It replaces the incomplete with a sack using

```text
q = max(0, (observed_cell_sack_rate - base_cell_sack_share) / base_cell_incomplete_share)
```

The pinned table has 115 cells, 40 shrunk cells, 76,195 pooled dropbacks, and 5,267 sacks. This is not a team-specific adjustment. Also, `q` is computed from the unmodified base event shares. With other event weights active, the final sack share is not guaranteed to equal the table target; this correction must be evaluated in the full weighted distribution before enabling it.

The earlier 2025 holdout audit found 6.544% observed versus 6.580% matchup-predicted league sack rate, while Minnesota's offense was 10.86% observed versus 7.08% predicted and Buffalo's defense allowed 9.67% versus 7.03% predicted. The saved 9,991-game D1 run had Minnesota at 3.667% sacks per dropback and Buffalo at 1.804%. These samples differ and are not a direct paired comparison. See `sack_context_2026_penalty_overlay.json` for the corrected 2026 cutoff-safe sack audit and its same-cohort legacy-input comparison.

## Reproduction and limits

1. Run `scripts/nfl_sequence/build_penalty_opportunity_extract.py` with the pinned archive, 2026 source, read-only database, and a new output directory. It refuses changed pinned inputs and refuses to overwrite existing outputs.
2. The offline audits use the code pin recorded in the original conditional outcome report, the unchanged database SHA above, and the generated 2026 overlay. They do not change the original 2025 audit or saved 10K artifacts.
3. The extract covers published PBP rows. It does not yet classify every row into an NFL-statistical penalty opportunity, accepted/declined penalty, first down awarded by penalty, or enforcement result. The missing 173 database rows and 634 matched null penalty statuses remain explicit coverage limits.

## Files

- `penalty-opportunity-plays-1999-2026.csv.gz`: compressed row-level historical extract.
- `penalty-source-overlay-2026.csv.gz`: separate 2026 source overlay.
- `manifest.json`: source and output hashes, per-season status counts, and 2026 reconciliation.
- `audit_official_sample.py` and `official-sample-validation-2016-2025.json`: ten pinned manual GSIS gamebook cross-checks.
- `audit_penalty_clauses.py` and `penalty-clause-coverage.json`: per-season literal clause parsing and scalar-field alignment audit.
- `conditional-audit-2026-overlay.json`: corrected walk-forward outcomes and common-cohort comparison.
- `sack_context_2026_penalty_overlay.json`: corrected sack rates by team and context, plus same-cohort ingestion comparison.
- `audit_2026_penalty_overlay.py`: corrected 2026 conditional audit.
- `sack_context_2026_penalty_overlay.py`: corrected 2026 sack audit.
- `audit_2026_week9_sack_ratio_diff.py`: cutoff-specific penalty input effect on sack multipliers.
- `week9-sack-ratio-diff.json`: cutoff-specific source coverage and sack multiplier comparison.
- `saved-10k-configuration-groups.json`: saved-run configuration identity split and per-group sack rates.
- `saved-10k-sacks-by-config.json`: extracted sack totals by configuration group.
- `saved-10k-layer-manifest.json`, `saved-10k-run-manifest.json`, and `saved-10k-run-summary.json`: saved run identities, enabled layers, and aggregate counters.

### Source-faithful research rows

`scripts/nfl_sequence/penalty_corpus.py` builds a separate, compressed Parquet dataset from the manifest-pinned annual sources. It retains every source row, including administrative and special-teams rows and declined-penalty text on rows with `penalty=0`. It carries the original description, game state, penalty fields, play outcomes, and literal disposition markers. A single marker is text evidence only; mixed or multiple fouls remain unresolved. Rows are not yet independently verified opportunities or adjudicated fouls, and the extract does not assert historical acquisition time or reconstruct the post-enforcement state.

A local run processed all 28 seasons, 1999–2026, preserving 1,300,819 rows in 43 MB. The output is at `/tmp/slc-penalty-corpus-20261110/` on this host; it is temporary and is not committed. `penalty-source-rows-manifest.json` records each source and resulting file hash. To reproduce it in a new directory:

```bash
backend/venv/bin/python scripts/nfl_sequence/penalty_corpus.py \
  --manifest docs/research/slc-v2-penalty-opportunities-2026-11-10/manifest.json \
  --output /path/to/new-directory --seasons $(seq 1999 2026)
```

The builder checks every source hash before creating the output directory, reads one bounded batch at a time, and refuses an existing output directory. These rows are a foundation for corpus-wide official-record validation, opportunity and foul classification, enforcement reconstruction, and held-out model tests; they do not enable penalties in the simulator.
