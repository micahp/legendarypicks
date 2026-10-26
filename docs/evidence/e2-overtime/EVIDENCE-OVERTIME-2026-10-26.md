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

- Overtime games: 12. Eleven were decided (home 5, away 6). One ended in a tie after the period.
- Blocked, by name: `thin_kick_cell:field_goal:50+` 3, `blocked_kick_receiving_return_outside_field` 2,
  `blocked_kick_kicking_return_outside_field` 1, `blocked_kick_outcome_unresolved:punt:guarded_penalty_fumble_or_review` 1.

Wilson 95%: treatment 293/300 = 0.953 to 0.989; control 285/300 = 0.919 to 0.969.

**This is not a paired comparison.** The overtime table is part of the reference fingerprint when present, so every
non-tied seed is re-keyed (288 of them). The 12 control ties are the only seeds whose path is directly affected. Read
the difference as independent Monte Carlo.

## Development history

- The first treatment run ended with 11 failed seeds. Causes: observed drives have no plays, so the stats reconciliation,
  the missed-field-goal return check, and the field-goal points check all failed on them; and the try tally indexed the
  last play of every drive. Each was fixed by treating observed drives explicitly. An earlier try-tally crash also lost a
  full run; it is fixed the same way.
- The earlier output files in this directory are superseded and are not committed:
  `validity-300-observed-overtime.*` (11 failures) and `validity-300-control-no-overtime-table.*` (superseded by `-r2`).

## Files

- `validity-300-control-r2.csv` and `.json`: table off. Identical to the blocked-kick arm.
- `validity-300-observed-overtime-r2.csv` and `.json`: table on.
- `docs/fixtures/e2/overtime_drives_2022_2025.csv` and `.manifest.json`: the observed drive pool.
