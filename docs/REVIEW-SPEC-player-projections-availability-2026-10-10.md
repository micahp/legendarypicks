# Spec B review: NFL availability, shares, and splits

**Reviewed:** 2026-10-10
**Candidate:** feat/player-projections-availability at eb6b443
**Base:** ac869832
**Verdict:** Hold before promotion or tagging. This is a read-only review; no code or database changes were made.

After the review, the local dev branch was reset to the base commit ac869832. The candidate remains on its feature branch. No tag or push was made. This review document is being added to the feature branch and is not committed.

## Scope reviewed

The candidate adds the B1 availability table/builder, B2 per-game shares, B3 splits, identity repair and writer guards, and a DEV daily share build. B0 schedule/date, snap-count, and injury-ingest inputs already exist in the base; the weekly availability refresh includes injury ingestion, so a missing injury table is not a finding in this review. Full publisher reconciliation for those B0 inputs was not re-run here.

B4–B8 are not implemented in this candidate: there is no “without” props API or UI, projection v2, projection job/grading, or projection record/API surface. The candidate is a foundation slice, not completion of Spec B.

## Findings

### P1 — A partially observed game can be treated as a complete snap feed

The availability builder considers a game complete when it sees at least one snap row for each scheduled team, then assigns played=0 to a candidate without a snap row in a final game. It does not establish that the game’s full publisher snap population was resolved. The snap ingest accounts for unresolved source rows, but those rows do not make this builder’s two-team test fail. A player whose snap identity was unresolved or whose row is missing can therefore be classified as not having played.

This violates the B1 rule that absence is zero only when the game’s snap file is complete; otherwise it is unknown. The fixture test covers a game with one entire team absent, but not a partial feed with at least one row from both teams.

Evidence: [availability completeness and classification](../backend/migrate_player_game_availability.py#L190), [snap ingest reconciliation](../backend/ingest_nfl_snap_counts.py#L377), [current incomplete-game test](../backend/test_player_game_availability.py#L90), [B1 contract](SPEC-player-projections-availability-2026-10-09.md#L67).

**Required before promotion:** establish and enforce per-game publisher completeness, including unresolved rows. Keep played=NULL for any game that fails that proof; add a fixture with incomplete rows on both teams.

### P1 — The recurring availability refresh never rebuilds the derived table

The weekly refresh ingests weekly stats, snap counts, and injuries, then exits. It does not run the availability builder with --build, and no other recurring invocation was found in the candidate. As those inputs change, player_game_availability can remain stale.

Evidence: [weekly input refresh](../scripts/nfl-availability.sh#L52), [availability builder entry point](../backend/migrate_player_game_availability.py#L270).

**Required before promotion:** run the build after all its inputs refresh in the same scheduled workflow, and make a build failure fail that workflow visibly.

### P1 — B1 omits log-only player-games

The candidate set is the union of snap rows and injury reports, but the spec requires an availability row for players appearing in snaps, logs, or injury reports. A log-only player-game is absent from the table rather than represented with unknown availability.

This should not turn a log into proof that a player played: the existing contract says snaps alone determine played. Include log-only candidates with played=NULL unless snap evidence proves otherwise.

Evidence: [candidate construction](../backend/migrate_player_game_availability.py#L180), [B1 row population](SPEC-player-projections-availability-2026-10-09.md#L56), [logs are not presence](SPEC-player-projections-availability-2026-10-09.md#L33).

### P1 — B3 uses recorded stat logs as the player-game universe

splits() starts from player_game_logs. The spec explicitly notes that a log means the player recorded a stat, not that the player appeared; a player who played but recorded no logged stat may have no row. Such games cannot appear in the matched, contradicted, or unknown counts, and prop history for a no-stat game may be omitted from the shared filtering logic.

Evidence: [splits game selection](../backend/player_splits.py#L23), [presence contract](SPEC-player-projections-availability-2026-10-09.md#L33), [B3 behavior](SPEC-player-projections-availability-2026-10-09.md#L83).

**Required before B4 consumes this helper:** define a complete game universe for the player/prop sample, and preserve missing availability as unknown rather than silently dropping the game.

### P2 — The team-week publisher cache can be stale indefinitely

fetch_team_file() downloads only when the cache path does not exist. The DEV daily job invokes the share builder, but a cached file is not refreshed or expiry-checked, so newer weekly publisher data can be missed. The focused cache test currently codifies reuse of any existing file.

Evidence: [cache behavior](../backend/build_player_game_shares.py#L48), [daily invocation](../scripts/nfl-daily.sh#L57), [cache test](../backend/test_player_game_shares.py#L109).

**Required before relying on the recurring build:** add a bounded freshness/revalidation policy or otherwise ensure each run uses the current published artifact and records its checksum.

## Data and acceptance evidence

- Focused tests previously run against the merged candidate tree: 38 passed. Command: /root/legendarypicks/backend/venv/bin/python -m pytest -q backend/test_player_game_availability.py backend/test_player_game_shares.py backend/test_player_splits.py backend/test_nfl_identity.py backend/test_nfl_identity_repair.py. This is fixture/code evidence, not a publisher-population proof.
- Read-only inspection of /root/legendarypicks/backend/data/picks.dev.db found 355/355 2026 air_yards season rows whose team_value differs from the sum of persisted nfl_team_game_totals for that team and metric. For ARI, the season-row denominator is 935 while the team-game totals sum to 944, with 9 unassigned air yards. The equivalent check found zero mismatches for 2026 targets/carries and all three metrics in 2025. This is a DEV data/rebuild acceptance gap, not by itself proof of a defect in the new calculation. Production was not inspected.
- Spec B3 requires a real 2025 WR1-out example; the candidate has fixture tests but no such API/output evidence.
- No disposable-clone publication, direct API check, browser/UI check, or fresh publisher-file reconciliation was performed as part of this review.

## Identity repair

No blocking defect was found in the reviewed repair path. It plans from publisher ID bridges rather than names, applies only to a disposable path under /tmp, and checks protected-table and player-reference fingerprints. Focused identity repair tests passed in the suite above.

The initial historical writer that created the malformed IDs remains unidentified. The candidate adds checks to the writer paths it found; this review did not independently enumerate or exercise every production writer. Do not describe the historical origin as resolved.

## Recommendation

Keep the candidate isolated until the P1 findings are fixed and covered by failure-oriented tests. Then rebuild DEV shares from a fresh publisher artifact and satisfy the B2 denominator reconciliation, produce the real B3 example, and review B4–B8 as separate slices. The identity repair may be reviewed independently, but a tag at eb6b443 would also include the preceding B1–B3 candidate work.

## B2 air-yards denominator, measured 2026-10-12 (no code changed, no rebuild run)

Read-only, dev DB. For five teams: the season row (`player_team_shares`, metric `air_yards`, 2026),
the sum of `nfl_team_game_totals.air_yards`, its `air_yards_unassigned` sum, and the per-game player
sum (`player_game_shares`, metric `air_yards`, `player_value`).

| Team | Season row team_value (team_games) | Team-game totals (games) | Unassigned sum | Per-game player sum |
|---|---|---|---|---|
| ARI | 1402 (5) | 944 (4) | 9 | 935 |
| KC | 844 (4) | 891 (4) | 47 | 844 |
| BUF | 1134 (4) | 1164 (4) | 30 | 1134 |
| DAL | 1385 (5) | 1441 (5) | 56 | 1385 |
| SEA | 1017 (5) | 828 (4) | -1 | 829 |

Cause, per team-game: the residual `air_yards_unassigned` equals the sum of `air_yards` on 2026 pass
plays with no `receiver_player_id` in `nfl_pbp`, exactly, in every team-game where it is non-zero
(for example KC 2026_01_DEN_KC 16 = 16, BUF 2026_02_DET_BUF -13 = -13, DAL 2026_01_DAL_NYG 67 = 67,
SEA 2026_04_LAC_SEA -1 = -1). For KC, BUF and DAL the season row equals the team-game total minus the
unassigned sum exactly. This is the no-receiver residual that spec line 232 describes.

ARI and SEA do not fit that cause. Their season rows count five team games, but the publisher team file
in the local cache (fetched 2026-10-09) and `nfl_team_game_totals` hold four. The extra game is week 5
(2026_05_DET_ARI and 2026_05_SF_SEA, both 2026-10-11). Those games are in `player_game_logs`
(`nflverse_weekly`) and not in `nfl_pbp` or the team file. The gap is the logged air yards of those
games: ARI 1402 - 935 = 467, SEA 1017 - 829 = 188. So the 2026 team file is one week behind the logs
for these two teams. The rebuild with a fresh publisher file is the fix, and it has not been run.

Also measured: 378 `air_yards` season rows for 2026 in the dev DB now (32 teams), not the 355 cited above.

## B3 real WR1-out example, 2025 (measured 2026-10-12)

Candidate search (read-only): for each 2025 team, the WR with the highest `targets` season share in
`player_team_shares`, his REG games in `player_game_logs` (`nflverse_weekly`) against the team's REG
games in `nfl_team_game_totals`, and `nfl_hist_injuries` for the missed weeks. Example chosen: Puka
Nacua (player_id 16247, LAR), target share 0.286. He logged 16 of 17 LAR team games. He missed
2025_07_LA_JAX (week 7), and the injury report lists him Out for week 7. Other candidates with one
missed game were not chosen (for example BUF Khalil Shakir, CIN Ja'Marr Chase, GB Romeo Doubs, with no
injury listing for the missed week).

Player split: Matthew Stafford (QB, player_id 21030, LAR, 17 of 17 games logged in 2025). Each run is
one game, so the sample is one game, not a measured effect.

Command: `LP_DB_PATH=.../picks.dev.db python3 backend/player_splits.py --player-id 21030 --without 16247 --season 2025`

```
player 21030, without [16247], with [], season 2025
matched 1, not matched 16, excluded unknown 0, excluded not-teammate 0
  matched     2025 w07 2025_07_LA_JAX LAR {"air_yards_share": 0, "air_yds": 363, "att": 33, "carries": 2, "cmp": 21, "cpoe": 4.221847292148706, "def_pct": 0, "def_snaps": 0, "dropbacks": 33, "fpts": 27.380000000000003, "fpts_ppr": 27.380000000000003, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 0.96, "off_snaps": 67, "pass_2pt": 0, "pass_epa": 8.782921106321737, "pass_td": 5, "pass_yds": 182, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 1, "sacks_taken": 0, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 23.61}
  not_matched 2025 w01 2025_01_HOU_LA LAR {"air_yards_share": 0, "air_yds": 226, "att": 29, "carries": 4, "cmp": 21, "cpoe": 5.381516899381365, "def_pct": 0, "def_snaps": 0, "dropbacks": 32, "fpts": 13.600000000000001, "fpts_ppr": 13.600000000000001, "fum": 1, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 60, "pass_2pt": 0, "pass_epa": 6.090108856966253, "pass_td": 1, "pass_yds": 245, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -2, "sacks_taken": 3, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 16.16}
  not_matched 2025 w02 2025_02_LA_TEN LAR {"air_yards_share": 0, "air_yds": 262, "att": 33, "carries": 2, "cmp": 23, "cpoe": 10.765356570482254, "def_pct": 0, "def_snaps": 0, "dropbacks": 34, "fpts": 17.32, "fpts_ppr": 17.32, "fum": 1, "fum_lost": 0, "fum_rec_td": 0, "intc": 1, "off_pct": 1, "off_snaps": 61, "pass_2pt": 0, "pass_epa": 9.779970589626963, "pass_td": 2, "pass_yds": 298, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -6, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 21.31}
  not_matched 2025 w03 2025_03_LA_PHI LAR {"air_yards_share": 0, "air_yds": 268, "att": 33, "carries": 0, "cmp": 19, "cpoe": -5.462000586769798, "def_pct": 0, "def_snaps": 0, "dropbacks": 34, "fpts": 13.84, "fpts_ppr": 13.84, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 1, "off_pct": 1, "off_snaps": 66, "pass_2pt": 0, "pass_epa": -2.479092506006727, "pass_td": 2, "pass_yds": 196, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 10.92}
  not_matched 2025 w04 2025_04_IND_LA LAR {"air_yards_share": 0, "air_yds": 342, "att": 41, "carries": 4, "cmp": 29, "cpoe": 5.447497591376305, "def_pct": 0, "def_snaps": 0, "dropbacks": 44, "fpts": 27.4, "fpts_ppr": 27.4, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 75, "pass_2pt": 0, "pass_epa": 14.293764206603946, "pass_td": 3, "pass_yds": 375, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 4, "sacks_taken": 3, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 15.53}
  not_matched 2025 w05 2025_05_SF_LA LAR {"air_yards_share": 0, "air_yds": 528, "att": 47, "carries": 1, "cmp": 30, "cpoe": -3.2675007763116257, "def_pct": 0, "def_snaps": 0, "dropbacks": 48, "fpts": 25.560000000000002, "fpts_ppr": 25.560000000000002, "fum": 1, "fum_lost": 1, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 68, "pass_2pt": 0, "pass_epa": 15.072453184221198, "pass_td": 3, "pass_yds": 389, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 0, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 22.35}
  not_matched 2025 w06 2025_06_LA_BAL LAR {"air_yards_share": 0, "air_yds": 229, "att": 26, "carries": 4, "cmp": 17, "cpoe": 0.7012727168890146, "def_pct": 0, "def_snaps": 0, "dropbacks": 28, "fpts": 9.34, "fpts_ppr": 9.34, "fum": 2, "fum_lost": 1, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 53, "pass_2pt": 0, "pass_epa": 0.9594451738590664, "pass_td": 1, "pass_yds": 181, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 1, "sacks_taken": 2, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 17.29}
  not_matched 2025 w09 2025_09_NO_LA LAR {"air_yards_share": 0, "air_yds": 319, "att": 32, "carries": 4, "cmp": 24, "cpoe": 12.67982307941683, "def_pct": 0, "def_snaps": 0, "dropbacks": 34, "fpts": 26.840000000000003, "fpts_ppr": 26.840000000000003, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 80, "pass_2pt": 0, "pass_epa": 11.838741028613722, "pass_td": 4, "pass_yds": 281, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -4, "sacks_taken": 2, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 25.99}
  not_matched 2025 w10 2025_10_LA_SF LAR {"air_yards_share": 0, "air_yds": 332, "att": 36, "carries": 3, "cmp": 24, "cpoe": 10.5948607711231, "def_pct": 0, "def_snaps": 0, "dropbacks": 37, "fpts": 26.900000000000002, "fpts_ppr": 26.900000000000002, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 69, "pass_2pt": 0, "pass_epa": 22.63015853331308, "pass_td": 4, "pass_yds": 280, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -3, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 22.53}
  not_matched 2025 w11 2025_11_SEA_LA LAR {"air_yards_share": 0, "air_yds": 146, "att": 28, "carries": 0, "cmp": 15, "cpoe": -16.569474449864142, "def_pct": 0, "def_snaps": 0, "dropbacks": 28, "fpts": 13.2, "fpts_ppr": 13.2, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 51, "pass_2pt": 0, "pass_epa": -4.049926161009353, "pass_td": 2, "pass_yds": 130, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 0, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 17.01}
  not_matched 2025 w12 2025_12_TB_LA LAR {"air_yards_share": 0, "air_yds": 249, "att": 35, "carries": 0, "cmp": 25, "cpoe": 4.716209366041071, "def_pct": 0, "def_snaps": 0, "dropbacks": 36, "fpts": 22.92, "fpts_ppr": 22.92, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 56, "pass_2pt": 0, "pass_epa": 8.219429925997625, "pass_td": 3, "pass_yds": 273, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 23.12}
  not_matched 2025 w13 2025_13_LA_CAR LAR {"air_yards_share": 0, "air_yds": 221, "att": 28, "carries": 1, "cmp": 18, "cpoe": 3.4452046509142273, "def_pct": 0, "def_snaps": 0, "dropbacks": 30, "fpts": 11.62, "fpts_ppr": 11.62, "fum": 1, "fum_lost": 1, "fum_rec_td": 0, "intc": 2, "off_pct": 1, "off_snaps": 52, "pass_2pt": 0, "pass_epa": -3.512069752730895, "pass_td": 2, "pass_yds": 243, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -1, "sacks_taken": 2, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 18.82}
  not_matched 2025 w14 2025_14_LA_ARI LAR {"air_yards_share": 0, "air_yds": 223, "att": 31, "carries": 0, "cmp": 22, "cpoe": 4.055153458349166, "def_pct": 0, "def_snaps": 0, "dropbacks": 31, "fpts": 23.240000000000002, "fpts_ppr": 23.240000000000002, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 0.83, "off_snaps": 58, "pass_2pt": 0, "pass_epa": 15.409675605792277, "pass_td": 3, "pass_yds": 281, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 0, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 21.04}
  not_matched 2025 w15 2025_15_DET_LA LAR {"air_yards_share": 0, "air_yds": 471, "att": 38, "carries": 1, "cmp": 24, "cpoe": -0.5515403653445997, "def_pct": 0, "def_snaps": 0, "dropbacks": 40, "fpts": 20.919999999999998, "fpts_ppr": 20.919999999999998, "fum": 1, "fum_lost": 0, "fum_rec_td": 0, "intc": 1, "off_pct": 1, "off_snaps": 72, "pass_2pt": 0, "pass_epa": 8.236465174336454, "pass_td": 2, "pass_yds": 368, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 2, "sacks_taken": 2, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 24.81}
  not_matched 2025 w16 2025_16_LA_SEA LAR {"air_yards_share": 0, "air_yds": 477, "att": 49, "carries": 2, "cmp": 29, "cpoe": -2.744625757137934, "def_pct": 0, "def_snaps": 0, "dropbacks": 49, "fpts": 30.880000000000003, "fpts_ppr": 30.880000000000003, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 92, "pass_2pt": 0, "pass_epa": 26.139787061895962, "pass_td": 3, "pass_yds": 457, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 6, "sacks_taken": 0, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 24.25}
  not_matched 2025 w17 2025_17_LA_ATL LAR {"air_yards_share": 0, "air_yds": 513, "att": 38, "carries": 0, "cmp": 22, "cpoe": -3.0521249605549707, "def_pct": 0, "def_snaps": 0, "dropbacks": 41, "fpts": 12.759999999999998, "fpts_ppr": 12.759999999999998, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 3, "off_pct": 1, "off_snaps": 65, "pass_2pt": 0, "pass_epa": -2.7485058022918993, "pass_td": 2, "pass_yds": 269, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 3, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 17.22}
  not_matched 2025 w18 2025_18_ARI_LA LAR {"air_yards_share": 0, "air_yds": 359, "att": 40, "carries": 1, "cmp": 25, "cpoe": -1.8891859698939968, "def_pct": 0, "def_snaps": 0, "dropbacks": 41, "fpts": 26.66, "fpts_ppr": 26.66, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 0.96, "off_snaps": 72, "pass_2pt": 0, "pass_epa": 15.790981256604955, "pass_td": 4, "pass_yds": 259, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 3, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 26.96}
```

Command: `LP_DB_PATH=.../picks.dev.db python3 backend/player_splits.py --player-id 21030 --with 16247 --season 2025`

```
player 21030, without [], with [16247], season 2025
matched 16, not matched 1, excluded unknown 0, excluded not-teammate 0
  matched     2025 w01 2025_01_HOU_LA LAR {"air_yards_share": 0, "air_yds": 226, "att": 29, "carries": 4, "cmp": 21, "cpoe": 5.381516899381365, "def_pct": 0, "def_snaps": 0, "dropbacks": 32, "fpts": 13.600000000000001, "fpts_ppr": 13.600000000000001, "fum": 1, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 60, "pass_2pt": 0, "pass_epa": 6.090108856966253, "pass_td": 1, "pass_yds": 245, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -2, "sacks_taken": 3, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 16.16}
  matched     2025 w02 2025_02_LA_TEN LAR {"air_yards_share": 0, "air_yds": 262, "att": 33, "carries": 2, "cmp": 23, "cpoe": 10.765356570482254, "def_pct": 0, "def_snaps": 0, "dropbacks": 34, "fpts": 17.32, "fpts_ppr": 17.32, "fum": 1, "fum_lost": 0, "fum_rec_td": 0, "intc": 1, "off_pct": 1, "off_snaps": 61, "pass_2pt": 0, "pass_epa": 9.779970589626963, "pass_td": 2, "pass_yds": 298, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -6, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 21.31}
  matched     2025 w03 2025_03_LA_PHI LAR {"air_yards_share": 0, "air_yds": 268, "att": 33, "carries": 0, "cmp": 19, "cpoe": -5.462000586769798, "def_pct": 0, "def_snaps": 0, "dropbacks": 34, "fpts": 13.84, "fpts_ppr": 13.84, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 1, "off_pct": 1, "off_snaps": 66, "pass_2pt": 0, "pass_epa": -2.479092506006727, "pass_td": 2, "pass_yds": 196, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 10.92}
  matched     2025 w04 2025_04_IND_LA LAR {"air_yards_share": 0, "air_yds": 342, "att": 41, "carries": 4, "cmp": 29, "cpoe": 5.447497591376305, "def_pct": 0, "def_snaps": 0, "dropbacks": 44, "fpts": 27.4, "fpts_ppr": 27.4, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 75, "pass_2pt": 0, "pass_epa": 14.293764206603946, "pass_td": 3, "pass_yds": 375, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 4, "sacks_taken": 3, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 15.53}
  matched     2025 w05 2025_05_SF_LA LAR {"air_yards_share": 0, "air_yds": 528, "att": 47, "carries": 1, "cmp": 30, "cpoe": -3.2675007763116257, "def_pct": 0, "def_snaps": 0, "dropbacks": 48, "fpts": 25.560000000000002, "fpts_ppr": 25.560000000000002, "fum": 1, "fum_lost": 1, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 68, "pass_2pt": 0, "pass_epa": 15.072453184221198, "pass_td": 3, "pass_yds": 389, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 0, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 22.35}
  matched     2025 w06 2025_06_LA_BAL LAR {"air_yards_share": 0, "air_yds": 229, "att": 26, "carries": 4, "cmp": 17, "cpoe": 0.7012727168890146, "def_pct": 0, "def_snaps": 0, "dropbacks": 28, "fpts": 9.34, "fpts_ppr": 9.34, "fum": 2, "fum_lost": 1, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 53, "pass_2pt": 0, "pass_epa": 0.9594451738590664, "pass_td": 1, "pass_yds": 181, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 1, "sacks_taken": 2, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 17.29}
  matched     2025 w09 2025_09_NO_LA LAR {"air_yards_share": 0, "air_yds": 319, "att": 32, "carries": 4, "cmp": 24, "cpoe": 12.67982307941683, "def_pct": 0, "def_snaps": 0, "dropbacks": 34, "fpts": 26.840000000000003, "fpts_ppr": 26.840000000000003, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 80, "pass_2pt": 0, "pass_epa": 11.838741028613722, "pass_td": 4, "pass_yds": 281, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -4, "sacks_taken": 2, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 25.99}
  matched     2025 w10 2025_10_LA_SF LAR {"air_yards_share": 0, "air_yds": 332, "att": 36, "carries": 3, "cmp": 24, "cpoe": 10.5948607711231, "def_pct": 0, "def_snaps": 0, "dropbacks": 37, "fpts": 26.900000000000002, "fpts_ppr": 26.900000000000002, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 69, "pass_2pt": 0, "pass_epa": 22.63015853331308, "pass_td": 4, "pass_yds": 280, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -3, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 22.53}
  matched     2025 w11 2025_11_SEA_LA LAR {"air_yards_share": 0, "air_yds": 146, "att": 28, "carries": 0, "cmp": 15, "cpoe": -16.569474449864142, "def_pct": 0, "def_snaps": 0, "dropbacks": 28, "fpts": 13.2, "fpts_ppr": 13.2, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 51, "pass_2pt": 0, "pass_epa": -4.049926161009353, "pass_td": 2, "pass_yds": 130, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 0, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 17.01}
  matched     2025 w12 2025_12_TB_LA LAR {"air_yards_share": 0, "air_yds": 249, "att": 35, "carries": 0, "cmp": 25, "cpoe": 4.716209366041071, "def_pct": 0, "def_snaps": 0, "dropbacks": 36, "fpts": 22.92, "fpts_ppr": 22.92, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 56, "pass_2pt": 0, "pass_epa": 8.219429925997625, "pass_td": 3, "pass_yds": 273, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 23.12}
  matched     2025 w13 2025_13_LA_CAR LAR {"air_yards_share": 0, "air_yds": 221, "att": 28, "carries": 1, "cmp": 18, "cpoe": 3.4452046509142273, "def_pct": 0, "def_snaps": 0, "dropbacks": 30, "fpts": 11.62, "fpts_ppr": 11.62, "fum": 1, "fum_lost": 1, "fum_rec_td": 0, "intc": 2, "off_pct": 1, "off_snaps": 52, "pass_2pt": 0, "pass_epa": -3.512069752730895, "pass_td": 2, "pass_yds": 243, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": -1, "sacks_taken": 2, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 18.82}
  matched     2025 w14 2025_14_LA_ARI LAR {"air_yards_share": 0, "air_yds": 223, "att": 31, "carries": 0, "cmp": 22, "cpoe": 4.055153458349166, "def_pct": 0, "def_snaps": 0, "dropbacks": 31, "fpts": 23.240000000000002, "fpts_ppr": 23.240000000000002, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 0.83, "off_snaps": 58, "pass_2pt": 0, "pass_epa": 15.409675605792277, "pass_td": 3, "pass_yds": 281, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 0, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 21.04}
  matched     2025 w15 2025_15_DET_LA LAR {"air_yards_share": 0, "air_yds": 471, "att": 38, "carries": 1, "cmp": 24, "cpoe": -0.5515403653445997, "def_pct": 0, "def_snaps": 0, "dropbacks": 40, "fpts": 20.919999999999998, "fpts_ppr": 20.919999999999998, "fum": 1, "fum_lost": 0, "fum_rec_td": 0, "intc": 1, "off_pct": 1, "off_snaps": 72, "pass_2pt": 0, "pass_epa": 8.236465174336454, "pass_td": 2, "pass_yds": 368, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 2, "sacks_taken": 2, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 24.81}
  matched     2025 w16 2025_16_LA_SEA LAR {"air_yards_share": 0, "air_yds": 477, "att": 49, "carries": 2, "cmp": 29, "cpoe": -2.744625757137934, "def_pct": 0, "def_snaps": 0, "dropbacks": 49, "fpts": 30.880000000000003, "fpts_ppr": 30.880000000000003, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 1, "off_snaps": 92, "pass_2pt": 0, "pass_epa": 26.139787061895962, "pass_td": 3, "pass_yds": 457, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 6, "sacks_taken": 0, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 24.25}
  matched     2025 w17 2025_17_LA_ATL LAR {"air_yards_share": 0, "air_yds": 513, "att": 38, "carries": 0, "cmp": 22, "cpoe": -3.0521249605549707, "def_pct": 0, "def_snaps": 0, "dropbacks": 41, "fpts": 12.759999999999998, "fpts_ppr": 12.759999999999998, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 3, "off_pct": 1, "off_snaps": 65, "pass_2pt": 0, "pass_epa": -2.7485058022918993, "pass_td": 2, "pass_yds": 269, "rec_2pt": 0, "rush_2pt": 0, "sacks_taken": 3, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 17.22}
  matched     2025 w18 2025_18_ARI_LA LAR {"air_yards_share": 0, "air_yds": 359, "att": 40, "carries": 1, "cmp": 25, "cpoe": -1.8891859698939968, "def_pct": 0, "def_snaps": 0, "dropbacks": 41, "fpts": 26.66, "fpts_ppr": 26.66, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 0.96, "off_snaps": 72, "pass_2pt": 0, "pass_epa": 15.790981256604955, "pass_td": 4, "pass_yds": 259, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 3, "sacks_taken": 1, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 26.96}
  not_matched 2025 w07 2025_07_LA_JAX LAR {"air_yards_share": 0, "air_yds": 363, "att": 33, "carries": 2, "cmp": 21, "cpoe": 4.221847292148706, "def_pct": 0, "def_snaps": 0, "dropbacks": 33, "fpts": 27.380000000000003, "fpts_ppr": 27.380000000000003, "fum": 0, "fum_lost": 0, "fum_rec_td": 0, "intc": 0, "off_pct": 0.96, "off_snaps": 67, "pass_2pt": 0, "pass_epa": 8.782921106321737, "pass_td": 5, "pass_yds": 182, "rec_2pt": 0, "rush_2pt": 0, "rush_td": 0, "rush_yds": 1, "sacks_taken": 0, "st_pct": 0, "st_snaps": 0, "st_td": 0, "target_share": 0, "targets": 0, "wopr": 0, "xfpts_ppr": 23.61}
```
