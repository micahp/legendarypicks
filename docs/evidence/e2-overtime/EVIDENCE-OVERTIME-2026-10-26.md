# Overtime from observed drives: evidence (2026-10-26)

## What changed

A regulation tie used to block the game as `overtime_not_modelled`. Now the game goes to Rule 16 (regular season): one
10-minute period, both teams possess once, then a leader wins, a tie is sudden death until the period ends, and a tie at
the end of the period is a tie.

Overtime drives come from observed data, the same way blocked kicks do. `docs/fixtures/e2/overtime_drives_2022_2025.csv`
(built by `scripts/nfl_sequence/build_overtime_drives.py`, checked against its manifest) holds 150 regular-season overtime
drives from 63 games, 2022-2025. 140 are usable:

| observed ending | usable drives |
|---|---|
| punt | 48 |
| field goal made | 37 |
| touchdown (six points; see below) | 26 |
| turnover | 9 |
| field goal missed | 8 |
| turnover on downs | 7 |
| defense touchdown | 4 |
| period end | 1 |

The other 10 drives are the last drive of a game, so no next start is observed. They are kept in the file and never drawn.

The engine draws one usable drive for the state. A drive fits when its observed time is within the clock. A period end fits
when its observed time reaches the clock. The Rule 16 logic then decides whether the game continues or ends.

## Assumptions and limits

- **Toss.** The toss winner receives. The toss itself is a seeded 50/50 draw. Deferral is not modelled. The observed
  kickoffs do not identify the toss, so this choice is not measured.
- **Kickoffs.** Kickoffs after a score come from the regulation kickoff pool.
- **Rule regime.** Walk-off first-drive touchdowns occurred in 2022-2024: a first-possession touchdown ended the game with
  no second drive (9 games). In 2025 the four first-possession touchdowns were each followed by a second drive, which fits
  Rule 16 as written. Each touchdown is recorded at six points, and its point after is drawn from the regulation try rates,
  the same as any touchdown in the engine. Of 30 scoring drives in the pool, 7 show a point after in their own drive rows.
  The other 23 are drawn as six points plus a regulation try. The rule text (Article 3(a)-(c)) decides what follows.
- **Not modelled in overtime.** The two-minute warning and Article 5(a) (a down that runs out after a score). Overtime
  drives are not split by situation; they are drawn from the same observed table.
- **Player stats.** Observed overtime drives carry no plays, so they have no player-level lines. Their touchdowns are
  counted on the team line and excluded from the player reconciliation (`observed_overtime_touchdowns`).

## Control: the new code changes nothing when the table is absent

Run with `--no-overtime-table`, on the same code. All 300 rows are identical to the blocked-kick arm
(`docs/evidence/e2-blocked-kick/`). Reference and run-snapshot digests are identical too.
Result: valid 285, tied 12, blocked 3, failed 0.

## Treatment: observed overtime table on

Result (300 pinned seeds, unconditional try policy):

| outcome | count |
|---|---|
| valid | 293 |
| blocked before regulation end | 7 |
| failed | 0 |

- Overtime games: 12. Eleven were decided (home 7, away 4). One ended in a tie after the period.
- These are the results of the team-label fix (`1260efd8`, cherry-picked from `6a372169`). The earlier run had
  overtime handoffs carrying club codes instead of simulated team labels, so its overtime paths were wrong.
- Blocked, by name: `thin_kick_cell:field_goal:50+` 3, `blocked_kick_receiving_return_outside_field` 2,
  `blocked_kick_kicking_return_outside_field` 1, `blocked_kick_outcome_unresolved:punt:guarded_penalty_fumble_or_review` 1.

Wilson 95%: treatment 293/300 = 0.953 to 0.989; control 285/300 = 0.919 to 0.969.

**This is not a paired comparison.** The overtime table is part of the reference fingerprint when present, so every
non-tied seed is re-keyed (288 of them). The 12 control ties are the only seeds whose path is directly affected. Read
the difference as independent Monte Carlo.

## Development history

- **Team-label correction.** Overtime handoffs used the historical club code as the team label. `other()` then mapped
  every label other than `A` to `A`, so drives after a non-scoring overtime ending were attributed to the wrong team.
  The fix hands the ball to the other simulated team and keeps the club code as source provenance. The corrected runs
  are `validity-300-observed-overtime-teamfix` and `validity-300-control-teamfix`. The earlier `-r2` files are superseded.

- The first treatment run ended with 11 failed seeds. Causes: observed drives have no plays, so the stats reconciliation,
  the missed-field-goal return check, and the field-goal points check all failed on them; and the try tally indexed the
  last play of every drive. Each was fixed by treating observed drives explicitly. An earlier try-tally crash also lost a
  full run; it is fixed the same way.
- The earlier output files in this directory are superseded and are not committed:
  `validity-300-observed-overtime.*` (11 failures) and `validity-300-control-no-overtime-table.*` (superseded by `-r2`).

## Files

- `validity-300-control-teamfix.csv` and `.json`: table off, after the team-label fix. Identical to the blocked-kick arm.
- `validity-300-observed-overtime-teamfix.csv` and `.json`: table on, after the team-label fix. The current result.
- `validity-300-control-r2.csv` and `.json`, `validity-300-observed-overtime-r2.csv` and `.json`: superseded by the
  team-label fix. Kept for the record.
- `docs/fixtures/e2/overtime_drives_2022_2025.csv` and `.manifest.json`: the observed drive pool.

## Completed overtime rules (`70d26aad`)

This round implements the rules Micah and Hermes2 approved, and reruns the pinned cohort.

**Engine changes.** A touchdown takes a try only where the game goes on. Sudden death from a tie is decided by the touchdown
(`not_attempted_game_ends`), so it takes none. An answering touchdown that leaves the score level takes one. The try is the
observed point after when the drive shows one (`observed_point_after`), otherwise a labelled draw from the regulation try
rates (`regulation_try_rates_fallback`). Article 5(a): after the first team scores, an interception or fumble by the second
team ends the game on the down, and a return touchdown on that down still takes its try. The overtime record names the turnover
kind and the leader before the down. `--overtime-toss A|B` forces the first possession for the sensitivity arms.

**Results (300 pinned seeds, unconditional policy, overtime table on unless stated).**

| arm | valid | blocked | failed | overtime games | ties | home wins | away wins |
|---|---|---|---|---|---|---|---|
| treatment (seeded toss) | 297 | 3 | 0 | 12 | 0 | 4 | 8 |
| sensitivity: first possession forced to A | 295 | 5 | 0 | 13 | 0 | 8 | 5 |
| sensitivity: first possession forced to B | 295 | 5 | 0 | 8 | 0 | 6 | 2 |
| control (table off) | 285 | 12 tied, 3 blocked | 0 | - | - | - | - |

The control matches the blocked-kick arm on all 300 rows, with the same reference and snapshot digests. The forced-possession
arms show that the first possession changes overtime results (13 against 8 overtime games, and home against away wins), so the
seeded baseline is a sensitivity, not a neutral fact.

**Paired rules-only comparison.** The overtime table is part of the reference fingerprint, so the completed-rules treatment is
re-keyed against the team-label-fix run. To attribute changes, the completed rules were rerun with the team-label-fix
fingerprint pinned (`teamfix-model-inputs.json`, verified to reproduce `5b0fcd07...`; driver `run_paired_rules_check.py`).
Under identical inputs, 3 of 300 seeds change: 65, 98 and 99. All remain valid, and each cause is the same. The decisive
overtime touchdown no longer takes a try (for example 27-20 becomes 26-20), so the margin changes by one point and the winner
does not. Changed seeds: 65, 98, 99.

**Labels on the 12 overtime games of the treatment.** Overtime touchdowns: observed point after 4, labelled regulation fallback 5,
no try because the touchdown decided the game 6. Article 5(a) resolved once (seed 16, fumble, no return touchdown). No
touchdown skipped its try while the game went on.

**Overtime try data.** The play-by-play holds 7 overtime try attempts in 2022-2025: 4 extra points made, 3 two-point tries
with 1 success, all in 2025 regular season. No postseason overtime try is recorded. A seven-attempt sample cannot estimate a
decision, so overtime tries use the conditional fallback table built from observed regulation tries (section "Conditional try
fallback" below). The regulation try rate is used only when a reference is loaded without that table.

**Long field goals: audit.** Observed 2022-2025 regular-season field-goal attempts from 67 or more yards (yardline_100 of 50 or
more): 4 in total, 3 on second down and 1 on third. None on fourth down, where the decision is made. Fourth-down plays at that
distance: 2,464 (punt 1,823, go for it 460, other 181, field goal 0). The engine reaches these attempts by sampling observed
events from sparse state cells, not from a decision model. The three thin-cell seeds stay blocked by name. Attempt-decision and
distance-based outcome models are not built yet.

**Toss and first possession (superseded for the choice; see "Overtime kick-or-receive decision" below).** The toss winner is a
seeded uniform draw. Play-by-play does not record the toss or the choice, so the choice is taken from the observed coin-toss
table instead, and the external figure is not used as a probability.

**Files.** `validity-300-overtime-rules.{csv,json}` (treatment), `validity-300-sensitivity-forced-{A,B}.{csv,json}`,
`validity-300-control-rules.{csv,json}`, `validity-300-paired-rules-on-teamfix-inputs.{csv,json}`, `teamfix-model-inputs.json`.

## Later on 2026-10-26: research variants, kept separate from the default

Nothing in the sections above is changed by this section. The default engine, its reference fingerprint (`e3032125`) and
its published inputs are the same as before this round. The variants below are opt-in research runs, and none of the findings
was used to change a default.

**Decisions, explicit.**

1. Default unchanged: the 2022-2025 kickoff pool, the observed overtime table, the observed kick-or-receive model (p_kick
   0.6875) and the conditional overtime try table.
2. The 2026 kickoff regime is a research variant (`--kickoff-regime --kickoff-before 2026-10-25`), not a default.
3. The 2022-2024 and 2025 overtime drive difference is reported, not applied. The drive pool stays pooled 2022-2025 until
   Micah decides on a 2025-only sensitivity run.
4. The 2026 two-point holdout is not read.

**Default fingerprint, verified.** With no flags, `e2_reference.load()` reproduces `e3032125`. Commit `3f6fbe2b` had made the
2026 kickoff regime the default and changed the fingerprint to `87334592`, because the reference hashes every kickoff sample
and the season field was on each sample. Commit `704c67f9` restored the default and made the regime pool opt-in. The runs
labelled `kickoff-2026-*` were made with the regime pool on, under `3f6fbe2b`. They reproduce from the flags (fingerprint
`76e46e0e`, 874 kickoffs).

**Conditional try fallback.** Table `docs/fixtures/e2/try_fallback_2022_2025.csv` (manifest alongside), from
`build_try_fallback.py`. The shrinkage strength k was chosen from {0, 2, 5, 10, 20, 50, 100} by 2025 log-loss after fitting on
2022-2024: k = 50, log-loss 0.2562, against 0.3015 for one unconditional rate. The 2026 tries are not read.

- `validity-300-conditional-try` (table on, fingerprint `ae3bbb2c`): 291 valid, 9 blocked. Its 9 overtime games recorded no
  overtime try, so the table is not exercised in that run.
- `validity-300-paired-conditional-try-on-rules-baseline` (fingerprint `46b4797e` pinned): 297 valid, 3 blocked. Against the
  rules baseline, 0 of the 297 seeds valid in both change. The unpinned treatment shows 9 blocked against 3 for the baseline.
  That difference comes from re-keyed seeds, not from the table. The paired check is the attribution.
- The working notes said five fallback tries were all extra points. The saved records carry no source field, so that count
  cannot be reproduced from them, and it is not cited. The paired run's 9 overtime tries are 8 extra points and 1 two-point
  try made, with no source label.

**Overtime kick-or-receive decision.** Table `overtime_choice_model_2025.csv`: 2025 regular season, 10 kicks in 14 games,
posterior mean 0.6875 (Beta(1,1)). The 2026 check (4 kicks in 6 games) scores 0.638 log-loss, against 0.693 for 50/50. The
2026 rows are not used to fit.

- Model arm `validity-300-overtime-choice-model`: 292 valid, 8 blocked, 17 overtime games.
- Forced arms, paired on the model fingerprint (`e3032125`): `validity-300-paired-decision-receive-on-prekickoff-inputs` and
  `validity-300-paired-decision-kick-on-prekickoff-inputs`, 292 valid each. Outside overtime, all 283 seeds that finished
  regulation in all three arms are identical, so the decision does not reach regulation. The arms differ on 12 seeds (model
  against receive), 15 (model against kick) and 15 (receive against kick), all inside the 17 overtime games.
- Overtime winners: model B 11, A 5, tie 1; receive B 11, A 4, tie 2; kick A 11, B 4, tie 2. Team A wins overall: model 146,
  receive 145, kick 152.
- The earlier unpaired controls (`validity-300-control-choice-receive` and `-kick`, fingerprints `d3a192c2` and `408512ce`)
  showed team A 165 against 128. That is not a decision effect. Their fingerprints differ from the model's, so their seeds are
  re-keyed; 259 of 259 non-overtime seeds differ between the two. Compare decisions only through the paired files.
- Reading: under a seeded fair toss the winner's first-possession probability is 0.5 for any kick rate, so the marginal is
  unchanged by design. The decision matters for joint or team-specific models, and those are not built.

**Overtime drive pool by era.** Script `scripts/nfl_sequence/overtime_era_test.py`, output
`docs/evidence/e2-overtime/overtime-drive-era-test.json`. The eras come from the registry: 2022-2024 (`2017-REG-OT-10`,
`2018-OT-RETURN-CONT`) and 2025 (`2025-REG-OT-BOTH`). The 63 regular-season overtime games split 49 and 14. Drives: 119 (113
usable) and 31 (27 usable).

- Outcome categories (touchdown, field goal made or missed, punt, turnover, other): chi-square 7.27, permutation p 0.209.
  No evidence of a difference.
- Points per drive: 1.56 and 2.61. The difference is +1.05 points, two-sided permutation p 0.026.
- Decision: the pool is not changed. The points difference is an open question. A 2025-only sensitivity run would rest on 27
  usable drives, so it would have little power. It needs a decision from Micah before it is run.

**2026 kickoff regime (research variant).** The pool holds the 874 kickoffs from 2026 before the cutoff. The registry gives
2025 and 2026 different kickoff rules (`2025-KO-PERM-TB35` against `2026-KO-50-TB` and `2026-KO-SETUP`). Disclosure: the
Kolmogorov-Smirnov test on kickoff spot does not separate 2025 from 2026 (D = 0.0385, p = 0.24). The split is a rule argument
from the registry, not a measured one, and the test does not reject pooling the two seasons.

- `validity-300-kickoff-2026-treatment` (regime pool on, new fingerprint): 295 valid, 5 blocked.
- `validity-300-kickoff-2026-control-no-overtime-table`: 290 valid, 3 blocked, and 7 ties blocked as `overtime_not_modelled`.
- `validity-300-paired-kickoff-2026-on-prekickoff-inputs` (pinned to the pre-kickoff fingerprint, so seeds match the model
  arm): 292 valid. The pool changes the score in 284 of the 289 seeds valid in both, because every game draws kickoffs. The
  mean total moves by -0.67 points (paired standard error 0.68), which is not distinguishable from zero.

**Not committed.** `validity-300-observed-overtime.*` and `validity-300-control-no-overtime-table.*` are superseded (see the
section above) and stay out of the repository.

**The 2026 registry on the hermes2 branch.** The 124-record inventory reported at commit `634757e7` is not in this clone. The
code reads the 39-record registry from `dev` (`1239e3ca`). It is not integrated here. A rule-regime resolver that uses it is a
separate phase.
