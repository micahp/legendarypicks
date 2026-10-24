# Clock replay of the six 2022 games behind this weekend's repeat matchups (2026-10-24)

Script: `scripts/bdb/bdb2022_six_games.py`. Output: `bdb2022-six-games-clock-replay-2026-10-24.json` (same folder).

## What was replayed

Each 2022 game keeps its real play sequence. Runoffs on run, pass, sack and similar plays are drawn from each clock model
(A, B, C as defined in `BDB2022-CLOCK-MODELS-WEEKS6-9-2026-10-24.md`). Kickoffs, punts, field goals and quarter-end markers
keep their observed runoff. Each model's pools are fitted on every matched play outside these six games. 100 draws per
quarter.

For each quarter, the clock the draws consume is compared with the clock the observed plays consumed. That total is exact
from the play-by-play: the first play's clock minus the quarter-end marker's clock. Every observed quarter lasts 900 s.

Nothing here simulates team strength, scoring or the 2026 teams. The sequences and team identities are the 2022 games'.

| 2022 game | 2026 pairing | quarters used |
| --- | --- | ---: |
| 2022_05_CIN_BAL | CIN @ BAL (Oct 25) | 4 |
| 2022_05_MIA_NYJ | MIA @ NYJ (Oct 25) | 4 |
| 2022_06_DAL_PHI | DAL @ PHI (Oct 26) | 4 |
| 2022_06_SF_ATL | SF @ ATL (Oct 25) | 3 (Q2 skipped: an unresolved runoff inside the quarter) |
| 2022_07_TB_CAR | TB @ CAR (Oct 25) | 4 |
| 2022_09_GB_DET | GB @ DET (Oct 25) | 4 |

## Results

"Error" is the model's clock consumed in a quarter minus the observed clock consumed (positive: the draws would run the clock
out early, which is the engine's clamp). "Overshoot" is the share of draws with a positive error.

| model | median error per quarter (s) | mean absolute error per quarter (s) | overshoot | undershoot | p10–p90 width per quarter (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| A, current engine rule | −16.5 | 88.7 | 44.6% | 55.0% | 148.7 |
| B, PBP-only conditional | −23.0 | 61.6 | 37.9% | 61.7% | 127.0 |
| C, tracking-informed | −23.4 | 61.8 | 37.9% | 62.1% | 131.8 |

Game totals (median error over the four quarters, seconds):

| 2022 game | A | B | C |
| --- | ---: | ---: | ---: |
| CIN @ BAL | +18.0 | −66.0 | −70.9 |
| MIA @ NYJ | −176.5 | −222.5 | −206.0 |
| DAL @ PHI | +59.5 | +90.5 | +80.6 |
| TB @ CAR | −271.5 | −200.0 | −212.7 |
| GB @ DET | −2.5 | −71.5 | −75.5 |

Plays drawn: 703 (A), 701 (B), 701 (C), with 155 keeping their observed runoff in every model. Plays whose conditioning pool
was too thin for the model fell back to their observed runoff and are counted in the JSON (58 for A, 60 for B and C).

## What the replay shows

- None of the three models keeps a quarter at 900 s. A quarter has 32 to 52 plays, each drawn independently. The p10–p90
  width of the error is 127–149 s per quarter, far larger than the median bias.
- The sign of the error changes from game to game. TB @ CAR is between −3.3 and −4.5 minutes across the models, and DAL @
  PHI is between +1.0 and +1.5 minutes. Over a whole game, the error is minutes, not seconds.
- Model B and C reduce the mean absolute error from 89 s to 62 s compared with A. Their tables are nearly the same, so the
  tracking split adds nothing to the clock total.
- Around 40% of draws would run a quarter's clock out before the observed last play. That is the clamp the engine applies
  when a draw exceeds the remaining time, and it is structural here: independent per-play draws cannot end at 900 s.

## Implication for the design

The gap is in how the clock is assembled, not in which runoff pool is used. Each play's time is drawn independently, so the
sum drifts. Fixing the pool (B or C over A) narrows the error a little. The period boundary has to be built in: the last
play of a quarter should end at the remaining time, and the other plays should be scaled or conditioned to fit. That is the
legal-transition step in the design, and this replay is the test for it.

## Limits

- One SF @ ATL quarter (Q2) is skipped. Overtime does not occur in these games.
- Quarter-level totals only. Drive durations and the play-level end-of-quarter behaviour are in the comparison report.
- The replay is per-play, conditioned on each play's observed outcome. Timeouts and penalty stoppages are not modelled, and
  the audit reports they cannot be resolved from these sources.
- 23 quarters and 6 games. Medians across 100 draws per quarter describe the replay's spread, not an estimate of the NFL
  distribution.
