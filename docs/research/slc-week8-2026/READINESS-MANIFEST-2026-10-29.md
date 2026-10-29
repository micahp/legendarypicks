# SLC v1 Week 8 2026: forecast readiness manifest

Locked model: `slc_v1_incomplete` at commit `ad7e26d9`. Play-call artifact sha256 `27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7`.
Evaluation class: `prospective_forecast`. Forecast seeds: 500 per game, 0 errors. Output hashes are in `forecast-lock.json`.

| Game | Kickoff (UTC) | Cutoff (UTC) | Schedule verified | Inputs verified | Injury rows (away/home) | Model | Evaluation class | Home win P (500 seeds, ±SE) | Mean home / away points | Locked |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026_08_ARI_DAL | 2026-11-01 18:00:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.498 ± 0.022 | 20.2 / 20.8 | at push, before kickoff |
| 2026_08_ATL_TB | 2026-11-01 18:00:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.532 ± 0.022 | 20.7 / 19.6 | at push, before kickoff |
| 2026_08_BAL_BUF | 2026-11-01 18:00:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.512 ± 0.022 | 20.8 / 19.9 | at push, before kickoff |
| 2026_08_CAR_GB | 2026-10-30 00:15:00 | 2026-10-29 00:02:21 | yes | yes | 7/9 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.510 ± 0.022 | 20.0 / 19.9 | at push, before kickoff |
| 2026_08_CHI_SEA | 2026-11-03 01:15:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.516 ± 0.022 | 20.0 / 19.6 | at push, before kickoff |
| 2026_08_CLE_PIT | 2026-11-01 18:00:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.484 ± 0.022 | 19.7 / 19.9 | at push, before kickoff |
| 2026_08_IND_JAX | 2026-11-01 18:00:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.472 ± 0.022 | 20.1 / 20.4 | at push, before kickoff |
| 2026_08_KC_DEN | 2026-11-01 21:25:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.486 ± 0.022 | 20.9 / 21.6 | at push, before kickoff |
| 2026_08_LAC_LA | 2026-11-01 21:05:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.528 ± 0.022 | 20.7 / 20.0 | at push, before kickoff |
| 2026_08_LV_NYJ | 2026-11-01 18:00:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.508 ± 0.022 | 20.6 / 20.6 | at push, before kickoff |
| 2026_08_MIN_DET | 2026-11-01 18:00:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.482 ± 0.022 | 20.6 / 20.9 | at push, before kickoff |
| 2026_08_NE_MIA | 2026-11-01 21:25:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.466 ± 0.022 | 19.8 / 20.7 | at push, before kickoff |
| 2026_08_PHI_WAS | 2026-11-02 01:20:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.540 ± 0.022 | 20.6 / 19.8 | at push, before kickoff |
| 2026_08_TEN_CIN | 2026-11-01 18:00:00 | 2026-10-29 00:02:21 | yes | yes | 0/0 | slc_v1_incomplete @ ad7e26d9 | prospective_forecast | 0.512 ± 0.022 | 20.5 / 19.9 | at push, before kickoff |

## Connected and missing layers (all games)

Connected: the play-call layer (score-clock), the drive engine and legal reducer, the pregame depth roster used for participant usage,
and post-event statistics as allocations.

Missing: team offense and defense splits, team playbooks, QB and role decision models, pre-event participant selection (not on this
commit; it is on `research/slc-preevent-2026-10-29`), injury report effects (the report is captured but not used), and kick decisions
(historical-share fallback).

## Caveats that bear on reading the forecasts

- The home win probabilities sit between 0.47 and 0.54 for every game. The locked model has no team-strength term beyond the
  team-by-down play-call effect, so these forecasts carry almost no game-specific signal. They are a record, not a claim of skill.
- Mean points are about 20 per team, below the 2024 average of 22.9. That is the scoring gap in `SLC-SCORING-CALIBRATION-2024-2026-10-29.md`.
- Injury reports exist for CAR–GB only. The other 13 games have no injury rows at capture.
- Inputs are verified by hash, acquisition time, publisher time and cutoff. The raw files are outside the repository.
- The paired-seed check (20 of 20 seeds identical between this commit and the pre-event branch with its layers off) was run on
  CAR–GB only. It is recorded here, not in a separate note.
