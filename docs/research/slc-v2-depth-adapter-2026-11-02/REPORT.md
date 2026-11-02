# 2025 depth-chart adapter report (SLC v2, owner ruling B), 2026-11-02

Status: research loader and coverage. No database write. No SLC default change. No 2026 outcome read. The file's 2026 `dt` values exist, but the cutoff rule excludes every one of them from a 2025 state.

## Source

- File: nflverse `depth_charts_2025.parquet`, copied to `gridiron-playbooks-research/data/raw/depth_charts_2025.parquet`.
- SHA-256: `14f74185b3c2c48df234ced284ba3596bda3333d0b2a8df40841f68cd34539fa`.
- Rows: 554,215. Columns: `dt`, `team`, `player_name`, `espn_id`, `gsis_id`, `pos_grp_id`, `pos_grp`, `pos_id`, `pos_name`, `pos_abb`, `pos_slot`, `pos_rank`.
- Snapshots: 221, from 2025-08-03 10:09:07 UTC to 2026-03-14 07:32:09 UTC. Every team carries every snapshot.
- Cadence: loads fall at about 07:15 UTC (measured: 07:13 to 07:16 for most). Median gap 24 hours, minimum 11.5 hours, maximum 97.8 hours.
- Depth groups in the file: `3WR 1TE` (244,084 rows), `Base 4-3 D`, `Base 3-4 D`, `Special Teams`. Offense appears only as `3WR 1TE`. Other offense groups (2TE, 1RB and similar) are absent from this file.
- Slots: `pos_slot` is a depth order from 1 to 12 within a group. `pos_rank` runs from 1 to 15.

## Rules implemented (`depth_adapter.py`)

1. **Temporal selection.** The state for a team and cutoff is the latest snapshot whose `dt` is at or before the cutoff. A later snapshot is never read.
2. **Series guard.** If the team's latest snapshot is earlier than the league's latest snapshot at or before the cutoff, the state is withheld (`team_snapshot_behind_series`). The team's old roster is not presented as current.
3. **Identity.** GSIS when present and in `players.csv`. ESPN only when it maps to exactly one verified GSIS. No name matching. Statuses are reported separately: `gsis`, `gsis_unverified`, `espn_unique`, `ambiguous`, `unmatched`.
4. **Roles.** Blank group or slot is kept as `UNKNOWN`. Duplicate slots and duplicate identities are flagged, not dropped.
5. **Staleness.** Cutoff minus snapshot, in seconds. Never negative.
6. **Horizons.** Early: the most recent Tuesday before the game day at 12:00 Eastern. Final: kickoff minus one hour. Eastern time follows the US daylight rule.
7. **Provenance.** Every state carries the source SHA-256, the snapshot time, and the staleness.

## Tests

`test_depth_adapter.py`: 25 passing. Covers temporal selection, the March snapshot case, team changes, staleness, GSIS and ESPN identity including ambiguity and no-name matching, duplicate slots and identities, `UNKNOWN` roles, horizons, a missing kickoff time, the series guard, and five integration checks on the real file (32 teams, 221 shared snapshots, every non-null GSIS in the index, null-GSIS partition, no later snapshot used).

Test red step: the first run failed on the missing module. Seven later failures were a fixture defect (missing `source_sha256` in the synthetic row), fixed in the fixture. One failure exposed the series-behind case, and the guard was added.

## 2025 coverage (`build_coverage.py`, output `outputs/depth_coverage_2025.csv`)

- Games: 272 regular-season games from the 2025 schedule.
- Team codes: the schedule uses `LAR` and `WSH`, the depth file uses `LA` and `WAS`. Mapped with the repo's `scripts/nfl_team_codes.py`, not a copy. Before the mapping, the build stopped on the two missing teams.
- States: 1,088 (272 games, two teams, two horizons). All 1,088 are `ok`. None is `team_snapshot_behind_series` or `no_snapshot_before_cutoff`. All 1,088 snapshots are at or before their cutoffs.
- Staleness (hours): early median 9.7, final median 9.8, final maximum 17.7. Because loads fall at about 07:15 UTC, a Sunday afternoon game uses the same morning's snapshot, about ten hours old.

Identity and duplicates over all states:

| Horizon | Entries | GSIS | Unmatched | Ambiguous | ESPN unique | Duplicate identity | Duplicate slot | Unknown role |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Early | 38,439 | 38,366 | 73 | 0 | 0 | 7,983 | 0 | 0 |
| Final | 39,260 | 39,191 | 69 | 0 | 0 | 8,165 | 0 | 0 |

Reading:
- Duplicate identity is common by design: one player is listed in several depth roles. In the 2025-09-07 17:00 UTC snapshot, 158 of 1,956 identified players appear more than once: 119 across depth groups (for example offense and special teams), and 39 in one group at different slots. These are flagged, not errors.
- Unmatched entries (73 and 69) are rows with no GSIS and no ESPN ID that resolves uniquely. The 5,577 null-GSIS rows in the whole file are mostly outside the selected states.
- No ambiguous ESPN ID appears in any selected state.

## What this does not establish

- **`dt` semantics are not verified.** The nflreadr `load_depth_charts` reference page does not document `dt`. The working assumption is that `dt` is the load time, so using it is conservative: a snapshot published earlier than its `dt` is only ever excluded, never read early. This is an assumption, not a verified fact.
- **Depth is not injury status.** A depth change may be a role change, a roster change, or an injury. The adapter does not infer injuries from depth changes (ruling C).
- **Offense is one group.** The file has `3WR 1TE` only. Any offense feature from this source covers that grouping, and nothing else.
- **Snapshot age.** Final-horizon states are roughly ten hours old, so late roster news after the morning load is missed. Report the staleness with every use.

## Open items

1. Verify `dt` against a publisher statement, or keep the conservative assumption and say so in every manifest.
2. Decide whether the 73 early and 69 final unmatched entries need a second identity source.
3. A coverage check on 2025 playoff games (not in this run, which uses regular-season games only).
