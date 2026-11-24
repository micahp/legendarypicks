# SLC-CEG Phase 3: clock and timeouts

Date: 2026-11-24. Pre-registration: `PHASE3-PREREGISTRATION.md` (`4bcd54aa`, before any score). Code:
`scripts/nfl_sequence/ceg_clock.py` (components, Model D benchmark), `ceg_harness.py` (generated drives through
`e1_drive.simulate`), `e1_drive.py` (`generates_events` switch). Results: `phase3/tune_2024.json`,
`phase3/final_2025_2026.json`, `phase3/harness_2025.json`, `phase3/harness_2026.json`.

## Result

1. **C beats B on every clock component in 2025** (intervals below zero): total runoff -0.093 per snap (median error
   2 s against 3 s), live-play seconds -0.045, first timeout -0.054, further timeout -0.011, out of bounds -0.002.
   2026 points the same way.
2. **The CEG clock ties Model D on total runoff:** 3.051 against 3.036 per snap (C minus D +0.016, -0.153 to +0.166).
   CEG does this while separating live time, dead-ball time and timeout decisions, and with the overtime rules Model D
   lacks.
3. **Timeouts are under-predicted:** 1,253 expected first timeouts in 2025 against 1,433 observed (673 against 790 in
   the last 2:00 of Q2 and Q4). Backlog E12.
4. **The generated drives run through the real loop:** 0 `check_drive` failures; see the harness section.

## Two corrections made before this report

- **Timeouts left.** nflverse's count on a snap already subtracts the timeouts taken after that snap (Timeout #1's own
  row reads 2 left). Read as-is, 1,132 of 6,673 timeouts looked illegal. The count at the decision is the snap value plus
  that team's timeouts in the interval; 1.2% of offense callers would then read 4 and are capped at 3. After the fix, 0
  conflicts.
- **Out-of-bounds window.** The first build computed the late-window mask before a merge that reset the index, so the
  mask landed on the wrong rows: 250 of 280 out-of-bounds runs counted as clock-stopping were mid-quarter runs. Found
  by the pre-registered sensitivity check (their median live time was 36 s; correct in-window runs are 6 s). Every
  Phase 3 number here is from the corrected code; the tuning, scoring and harness were rerun.

## Rules, measured in the 2025 play-by-play

- Two-minute warning in Q2, Q4 and overtime: plays crossing 2:00 have their next snap at exactly 2:00 in 1,073 of 1,204
  (Q2), 1,019 of 1,244 (Q4) and 22 of 23 (overtime).
- Out of bounds stops the clock to the snap inside the last 2:00 of Q2 and the last 5:00 of Q4 and of overtime (median
  runoff 6 to 7 s); otherwise it restarts on the ready signal (33.5 to 36 s).
- Model D applies both rules to Q2 and Q4 only (backlog E7). CEG applies them to overtime too.

## 2025 confirmation (log loss per opportunity)

| component | n | B | C | C minus B (95%) |
|---|---|---|---|---|
| total runoff (censored at the two-minute warning and quarter ends) | 32,816 | 3.125 | 3.032 | -0.093 (-0.099 to -0.087) |
| live-play seconds (stopped-clock snaps) | 9,119 | 2.121 | 2.076 | -0.045 (-0.053 to -0.037) |
| first timeout at the opportunity | 31,014 | 0.218 | 0.164 | -0.054 (-0.058 to -0.050) |
| further timeout | 1,464 | 0.115 | 0.104 | -0.011 (-0.017 to -0.004) |
| out of bounds | 23,532 | 0.363 | 0.361 | -0.002 (-0.003 to -0.001) |
| total runoff, Model D refit | 32,304 | D 3.036 | C 3.051 | C minus D +0.016 (-0.153 to +0.166) |

k: live 300, dead 100, out of bounds 300, both timeout stages 300.

**Identification.** Live time is observed only on snaps after which the clock stops at the whistle (43,350 of 153,589);
for in-bounds runs and completions with a running clock it is assumed to follow the same distribution given event,
yards bucket and out of bounds. The sensitivity check supports this for runs: median live time 6 s on in-window
out-of-bounds runs, 5 s on touchdown runs, 8 s on runs followed by a timeout (which adds the seconds until it is
called). Dead-ball time is never observed; it is recovered by EM on 110,239 running-clock snaps.

## Harness: generated drives through `e1_drive.simulate`

2,000 regular-season 2025 drive starts, one generated drive each, every drive checked with `check_drive`. Observed
drives from the same starts. Filled from `phase3/harness_2025.json` and `phase3/harness_2026.json`:

Per drive, from the same starts. 0 halts and 0 `check_drive` failures in every configuration (the runs use the
generator with the field-goal ceiling aligned to the drive loop; an earlier run had 1 halt per configuration there).

| season | configuration | plays | duration (s) | plays per 60 s | TD | FG attempts | punts | turnovers | downs |
|---|---|---|---|---|---|---|---|---|---|
| 2025 | observed | 6.33 | 169.6 | 2.24 | 472 | 384 | 659 | 186 | 133 |
| 2025 | C, CEG clock | 6.16 | 175.4 | 2.11 | 474 | 307 | 706 | 233 | 105 |
| 2025 | C, Model D clock | 6.11 | 168.8 | 2.17 | 470 | 300 | 692 | 236 | 99 |
| 2025 | B, CEG clock | 5.30 | 152.7 | 2.08 | 327 | 155 | 552 | 182 | 605 |
| 2025 | BC-selective, CEG clock | 6.15 | 175.1 | 2.11 | 480 | 315 | 697 | 228 | 103 |
| 2026 | observed | 6.19 | 162.4 | 2.29 | 472 | 382 | 688 | 199 | 104 |
| 2026 | C, CEG clock | 6.10 | 173.0 | 2.12 | 428 | 344 | 751 | 205 | 109 |
| 2026 | BC-selective, CEG clock | 6.08 | 172.8 | 2.11 | 436 | 331 | 746 | 208 | 117 |
| 2026 | B, CEG clock | 5.40 | 157.3 | 2.06 | 326 | 149 | 553 | 185 | 624 |

Reading it:

- Plays per drive match within 3% for C and BC-selective. B ends five to six times as many drives on downs as observed:
  without the situation it goes for it on 4th down far too often.
- The CEG clock runs 3% to 7% long per drive (175 s against 170 s in 2025; 173 s against 162 s in 2026); Model D's clock,
  drawn from observed runoffs, is closer (169 s). The local scores tie; at drive level Model D is closer on duration.
- Field-goal attempts are 20% short (307 against 384 in 2025), turnovers 25% high, punts 7% high: drive endings to
  check in Phase 7 at game level.
- BC-selective and C are within noise of each other on every measure, in both seasons. Its aggregate check (2026, not
  used to choose it) shows no gain and no harm from the selective composition.
- Timeouts per drive: 445 in 2,000 generated 2025 drives. The observed count from the same starts was not computed (a
  pre-registered measure left out; the local timeout scores above cover timeouts).

The selective composition (BC-selective) is checked on the 2026 starts because it was chosen from the 2025 results.
