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
decision, so the overtime try policy has no overtime-specific estimate yet. The fallback above is the regulation try rate, and
it is labelled as such. A conditional fallback from score-conditioned regulation tries, with shrinkage, is not built yet.

**Long field goals: audit.** Observed 2022-2025 regular-season field-goal attempts from 67 or more yards (yardline_100 of 50 or
more): 4 in total, 3 on second down and 1 on third. None on fourth down, where the decision is made. Fourth-down plays at that
distance: 2,464 (punt 1,823, go for it 460, other 181, field goal 0). The engine reaches these attempts by sampling observed
events from sparse state cells, not from a decision model. The three thin-cell seeds stay blocked by name. Attempt-decision and
distance-based outcome models are not built yet.

**Toss.** The first possession is a seeded uniform draw, and the toss winner receives. Play-by-play does not record the toss or
the kick-or-receive choice, so the choice cannot be estimated from it. The external figure (10 kick, 4 receive, 2025
overtime) is not used as a probability in the engine.

**Files.** `validity-300-overtime-rules.{csv,json}` (treatment), `validity-300-sensitivity-forced-{A,B}.{csv,json}`,
`validity-300-control-rules.{csv,json}`, `validity-300-paired-rules-on-teamfix-inputs.{csv,json}`, `teamfix-model-inputs.json`.
