# Decision model v1: reuse as a research input, 2026-10-29

Status: research candidate. Not approved. Its 2026 test result stands as recorded and is not used to tune, select or retrain any model.
The 2026 test stage was not rerun.

## Reproduced

- Code: `scripts/nfl_sequence/splits/decision_model.py` at commit `fd2a5aea` on `research/nfl-historical-splits-2026-10-27`.
- Stage run: `validate2025` only, in a scratch copy with the results directory redirected. It uses 2025 data only.
- Frozen 2025 prior, rebuilt: sha256 `ed70a4af286fc5f0...`. The recorded value in `validate2025.json` is the same, so the prior reproduces
  exactly.
- Validation table, rebuilt: team prior at k = 5, 20, 80 (chosen k = 20) and the league prior. Headline mean total-variation distance
  over categories A to N: k = 80 0.0511, league 0.0612. These match the recorded table.

## Reused as research inputs

- Category and cell definitions (`CAT_ROLES`, `cell_of`, role mapping, `label_row`), and the frozen 2025 prior with its hash.
- The participation categories of version 2 (formation, personnel, coverage, pressure, time to throw), frozen before any version 2
  result, with no 2026 data. Formation and coverage are already used in SLC as cutoff-safe priors (`formation_layer.py`,
  `defense_layer.py`), built from the same participation release.

## Not done

- Integrating the frozen decision-category prior into SLC's pre-event decisions. Its categories (target role, QB alignment, run gap, box
  count and others) are not yet mapped onto SLC's decision points. That mapping is a design step, and it needs a cutoff audit per
  evaluation season.
- Any use of the 2026 test result. It remains a single headline: a team prior with a difference of -0.0022 against the league prior,
  confidence interval -0.0056 to +0.0012, which does not establish an improvement.
