# M5 freeze amendment 7, 2026-11-04: refit lineup table and the current-season snap-count update

Status: owner-authorized (2026-11-04: "refit the lineup table and wire in snap counts"). Research only, behind
`--participation-field` and the new `--participation-snap-counts`, both off by default. No pinned layer file
(`slc_config.LAYER_CODE_FILES`) changes. No SLC default changes. Earlier freeze documents and amendments are not edited.

## The change

- New lineup table `participation-model-2026-11-02/outputs/field_v4_decay075_2020_2025.json` (for 2026 games) and
  `field_v4_decay075_2019_2024.json` (for 2025 checks): season weights 0.75 ** age over six seasons (grouping backtest,
  `WEEKLY-BACKTEST-RESULTS-2026-11-04.md`) and a player-dependent leave hazard, `leave_power` 1.5
  (`WEEKLY-PLAYER-BACKTEST-RESULTS-2026-11-04.md`).
- `--participation-snap-counts <json> --participation-snap-counts-sha256 <hash>` (needs `--participation-field`): the
  game season's published snap counts from weeks before the game tilt each team's grouping draw (N0 8) and weight each
  player's on-field rate (N0 1) (`snap_update.py`). The file is built by `build_snap_counts.py`. The engine refuses
  another season's file and a team with no earlier game when the file has earlier weeks, and records the tilt and
  weights in the ledger's `research_integration.participation_snap_counts`.
- The per-seed replay command carries the research table flags (`--participation-field`,
  `--participation-snap-counts`, `--playcall-fg-kicker` with their hashes); it omitted them before.

## Changed files (none pinned)

| File | SHA-256 prefix | Change |
|---|---|---|
| `scripts/nfl_sequence/participation_field.py` | `ce0d3733370a7939` | `group_tilt`, `player_weight`, `leave_power`, `leave_reference_rate` (empty or zero by default) |
| `scripts/nfl_sequence/snap_update.py` | `b88983dd6392b27f` | new |
| `scripts/nfl_sequence/slc_engine.py` | `f3e8acf6450ca7ed` | `load_reference(participation_snap_counts=...)` |
| `scripts/nfl_sequence/simulate_pregame_batch.py` | `983ec81d16f3dc78` | the flag, its checks, the ledger entry, the replay command |
| `docs/research/participation-model-2026-11-02/export_field.py` | `4c913bd8773772a8` | `--decay`, `--leave-power`; without them the committed v4 table is rewritten byte for byte (`b53b2566...`) |
| `docs/research/participation-model-2026-11-02/build_snap_counts.py` | `bfbe87eb8c562fc3` | new |

## Verification

- Tests: 61 passed (`test_snap_update` 13, `test_participation_field`, `test_participation_field_hook`,
  `test_kicker_field_goals`).
- Flags-off regression (frozen extract, Week 8 `2026_08_KC_DEN`, RNG v2, seeds 1 to 3): 0 of 3 seeds differ from the
  amendment 6 run.
- `--participation-field field_v4_2022_2025.json` without snap counts: 0 of 3 seeds differ from the amendment 5 run.
- Smoke, refit table plus 2026 snap counts through week 7 (`fc409bce...`, 214 team-games; read as forecast input only,
  not scored): 3 of 3 valid games, no short lineups. KC used 6 earlier games and DEN 7, both through week 7.

## Known limits

- Published snap counts total about 4.91 skill players per team snap against the table's 4.98 (team snaps include plays
  the table leaves out), so the tilt also shifts slightly toward six-lineman groupings. The backtest had the same offset.
- The lineup layer's player snap shares still trail the published share to date (0.155 against 0.127 per player-game).
