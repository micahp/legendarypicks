# SLC Week 8 ARI–DAL: 10,000-seed run

- **Matchup:** Arizona at Dallas (`2026_08_ARI_DAL`)
- **Report date:** 2026-10-30
- **Profile:** `v1_full_stack` (`SLC_v1_full_stack`)
- **Run scope:** one frozen matchup, 10,000 seed attempts across six workers

## Outcome coverage

| Outcome | Games | Share |
| --- | ---: | ---: |
| Complete in regulation | 9,479 | 94.79% |
| Complete in overtime | 515 | 5.15% |
| **Complete, including overtime ties** | **9,994** | **99.94%** |
| Blocked before regulation ended | 6 | 0.06% |
| Simulation or validation errors | 0 | 0.00% |

The six workers are nonoverlapping seed shards of the **same ARI–DAL matchup**:

| Worker | Seeds | Attempts |
| --- | ---: | ---: |
| 01 | 1–1,667 | 1,667 |
| 02 | 1,668–3,334 | 1,667 |
| 03 | 3,335–5,001 | 1,667 |
| 04 | 5,002–6,668 | 1,667 |
| 05 | 6,669–8,334 | 1,666 |
| 06 | 8,335–10,000 | 1,666 |

All 10,000 seed IDs are unique and present. All 10,000 seeds have an exported boxscore.
Every boxscore reconciliation passed; the records use `strict=false`. Team points in the
boxscores match the seed ledger for all games.

The original worker summary mislabeled 11 games that **finished tied after overtime** as
regulation ties and excluded them from its 9,983-game aggregate. The corrected audit
classifies them as completed final ties. This correction changes only the postrun
classification and aggregate denominator; the original seed outcomes and boxscores are
preserved. The corrected boxscore summary uses 9,994 completed games, including those 11
ties. See [postrun-audit.json](outputs/parallel-6-v5-lateral-filter-blocked-decision-2026-10-30/postrun-audit.json)
and [boxscore-summary.json](outputs/parallel-6-v5-lateral-filter-blocked-decision-2026-10-30/boxscore-summary.json).

## Scores and team output

Score distributions use all 9,994 completed games. Percentiles use linear interpolation.

| Measure | DAL | ARI | Total / DAL margin |
| --- | ---: | ---: | ---: |
| Mean points | 24.701 | 23.748 | 48.449 / +0.953 |
| Median | 24 | 24 | 48 / +1 |
| 10th–90th percentile | 14–35 | 13–34 | 33–65 / −13 to +15 |

DAL won 5,312 of 9,983 decisive games (53.21%); ARI won 4,671 (46.79%). Eleven completed
games ended tied.

Mean team output per completed game:

| Team | Plays | Drives | Pass att. | Completions | Rush att. | Pass yds | Rush yds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| DAL | 67.717 | 9.918 | 35.850 | 25.334 | 31.345 | 275.568 | 132.798 |
| ARI | 64.029 | 9.857 | 33.941 | 22.540 | 29.085 | 240.718 | 138.652 |

The boxscores contain player-level passing, rushing, receiving, and fumble-lost totals.
These are simulated allocations from the frozen participant inputs, not observed player
results. Player means include zero-stat games for each eligible player.

| Player | Team | Pass att. / yds / TD / INT | Targets / receptions / rec. yds | Rush att. / yds |
| --- | --- | ---: | ---: | ---: |
| Jacoby Brissett | ARI | 33.87 / 240.25 / 1.47 / 0.26 | — | 5.14 / 27.51 |
| Dak Prescott | DAL | 35.79 / 275.10 / 1.46 / 0.42 | — | 4.28 / 19.50 |
| Michael Wilson | ARI | — | 13.57 / 8.50 / 96.70 | — |
| George Pickens | DAL | — | 8.52 / 5.80 / 69.51 | — |
| Bam Knight | ARI | — | 2.52 / 1.78 / 16.02 | 12.11 / 54.37 |
| Javonte Williams | DAL | — | — | 20.51 / 84.39 |

## Blocked outcomes

| Blocker | Games |
| --- | ---: |
| Punt block with receiving-team return endpoint outside the field | 1 |
| Punt block with next snap outside the field | 4 |
| Field-goal block without a reconstructable legal next-snap spot, down, and distance | 1 |
| **Total** | **6** |

These outcomes remain explicitly blocked; none was converted into a completed game. The 101
field-goal period-transition blockers did not recur: this run recorded **zero** blockers in
that family. The remaining six blockers are blocked-kick geometry reconstruction cases.

## Model configuration and source windows

The run used 16 of 17 configured playcalling layers. `fixed_player_target_carry_shares` was
disabled.

| Layer or input | Source window used |
| --- | --- |
| Score/clock playcalling artifact | 2010–2025 |
| E1 outcomes and team offense/defense event mix | 2022–2025 |
| Formation/personnel priors | 2016–2025; outcomes conditioned on 2022–2025 |
| Defensive coverage priors | 2016–2025; outcomes conditioned on 2022–2025 |
| Fixed player target/carry shares | Disabled |
| Dirichlet player target/carry shares | 2025 |
| QB decisions | 2022–2025 |
| Player-conditioned outcomes | 2022–2025 |
| Target-role priors | 2016–2025 |
| FTN decision labels | Charted seasons 2022–2025; decision prior 2025; outcome pool 2022–2025 |
| Decision row filter | Not separately fitted; conditions the labeled source pool |
| Playbook priors | 2025 |
| Point splits | 2010–2025 |
| Team and league streak splits | 2010–2025 |
| Exact-yardline outcomes | E1 outcome pool, 2022–2025 |
| Current streak context | Separate pregame state file as of 2026-10-29, through Week 7 |

The simulation SQLite input used by the event-clock loader contains 188,282 `nfl_pbp` rows
from 2022–2025, so its earliest available season on this host is 2022. Event-clock Model D
is a separate research replay, not the clock used in this full-stack batch. That replay
fits 2022–2024 and evaluates on held-out 2025. Its stop-class short-share lookup was
corrected to use the simulated stop class.

Some profile-manifest `fit_seasons` fields are generic and do not describe each layer's
actual source range. The table above follows the layer loaders and source manifests. The
current-streak file labels itself “display only,” although the active profile consumes it
as a current-state input; it is reported here as state, not training data.

## Provenance and run resources

- Producer commit: `52c59c10` on `research/slc-decision-layer-2026-10-29`; the producer
  worktree was clean.
- Configuration hash: `52d3aff82223f8c877729f53cae6e5e6044831ce459b2205ea3ae2fd394de20c`
- Reference hash: `c13724b908475053e4aec2b7c9b6931c8e37b531d75beb6a104f4f7f730e943b`
- Pregame snapshot hash: `664c242e563bb9414a962e6a87fe539128f325e8e9b52d8d593d7d08cc198bc1`
- Playcall artifact hash: `27c02afd6d9f6f80a38b3bc7ae278b1efebcc7caa5664688c64c55bc0c698ac7`
- Input SQLite hash: `feb5179f1c6c2f8cd2265a25ff68f3552d6e68bbba00354e0688f22505aa028f`
- Information cutoff: `2026-10-29T00:02:21Z`; historical sources eligible only before 2026
  Week 1.
- Baseline v1: unavailable in all six worker summaries.

Recorded per-worker runtime before report writing ranged from 9,414 to 9,668 seconds (about
2h37m–2h41m); the six workers ran concurrently. The raw run directory is about 1.4 GiB.
The committed artifact copy is 139.4 MB, stored with gzip compression. During the run, six
workers used about 7.8 GiB RSS together; the observed minimum available memory was about
1.8 GiB, with no swap.

The raw worker JSON summaries, seed ledgers, boxscores, logs, launcher, corrected audit,
and aggregate boxscore summary are in
[outputs/parallel-6-v5-lateral-filter-blocked-decision-2026-10-30/](outputs/parallel-6-v5-lateral-filter-blocked-decision-2026-10-30/).
Verify stored files with `SHA256SUMS.txt`; `RAW-SHA256SUMS.txt` records the hashes of the
original uncompressed worker outputs.

## Interpretation

This is a descriptive 10,000-seed distribution for one frozen matchup. It does not measure
calibration or establish improvement over a baseline. The unavailable v1 baseline prevents
a paired comparison in this report.
