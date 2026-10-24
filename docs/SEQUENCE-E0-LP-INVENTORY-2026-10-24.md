# NFL sequence generator, LP E0 inventory (2026-10-24)

Plan: `docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md` (Gridiron repo, main). This is the LP
sequence/game-state agent's first step, the implementation map and minimal payload for gate E0. It is not a claim
that the generator is built, and it is not a Gridiron result.

## Sources (exact commits, on `dev` at cef6f987)

| Artifact | Commit | Role |
| --- | --- | --- |
| `docs/GRIDIRON-CONTRACT-v1.md` | 0b70548d | v1 payload. Byte-identical to the Gridiron mirror (sha256 `ae7b8a30…21b7`) |
| `docs/SPEC-nfl-pregame-play-sequence-generator-v1.md` | bbd4d57a | Generator spec; status "proposed, not implemented" |
| `backend/nfl_sim.py` | 19092c69 | Season-level final-score simulation. Not a play generator |
| `backend/nfl_sim_scores.py` | 1e5fce62 | Score distributions and history sampler. Not a play generator |
| `backend/nfl_score_dist.py` | 64bb93e8 | Score distributions. Not a play generator |
| `backend/ingest_nfl_pbp_logs.py` | ad8f264f | Defines the curated `nfl_pbp` table |
| New: `scripts/nfl_sequence/e0_single_play.py` | uncommitted, on `feat/nfl-sequence-e0-2026-10-24` | E0 single-play record |
| New: `docs/fixtures/nfl-seq-e0-play-record-seed1042.json` | uncommitted | Pinned E0 record |

## Data source

- `nfl_pbp` lives in `/root/legendarypicks/backend/data/picks.dev.db`, read-only. Per-season rows: 2010 44,991;
  2011 45,455; … ; 2025 46,452; 2026 16,551 (partial season). These are counts taken at 02:00 CT. The file was modified
  at 02:00, so the 2026 count is not stable and the file is not hashed (3.2 GB).
- The production-named `backend/data/picks.db` has **no** `nfl_pbp` table (checked read-only).
- The dev database has no score, timeout or pregame-roster columns. This matches the spec's warning in the "Existing
  inputs" section.
- Columns relevant to E0: `game_id`, `play_id`, `season`, `week`, `posteam`, `defteam`, `home_team`, `away_team`, `qtr`,
  `down`, `ydstogo`, `yardline_100`, `game_seconds_remaining`, `play_type`, `yards_gained`, `touchdown`, `interception`,
  `fumble_lost`, `sack`, `complete_pass`, `qb_scramble`, `penalty`, `two_point_attempt`, `drive`.
- Season and week are the only regular-season filter (`week <= 18`). `season_type` is not in the table, so playoff
  exclusion is an approximation.

## What E0 does

1. Picks one real 2025 regular-season pre-play state with a seed (1042): `2025_05_LV_IND` play 1638.
2. Samples the play from other games in the same down, distance bucket and field-position bucket, using 2022–2025
   regular-season plays. The start game is excluded. The start row's recorded outcome is not read.
3. Samples the event from `run`, `pass_complete`, `pass_incomplete` and `sack` in proportion to the cell's shares, then
   samples one row of that event.
4. Applies a minimal down/distance/field reducer to get `state_after`. Touchdowns, turnovers on downs and safeties are
   handled explicitly.

**Exclusions (printed, with counts, and not silent):** penalty 1,962; quarterback scramble 3,860; fumble lost 950;
interception 1,555. All four are deferred to E1. Two-point tries are also excluded. The cell for the seed-1042 start
is 5,572 plays. The E0 pool validation ran the reducer over all 125,309 eligible plays: 0 illegal downs, yardlines or
touchdown mismatches.

**What the validation does and does not show.** It checks that the reducer's own transitions are legal for every pool
row. It does not check that the reducer reproduces real NFL outcomes, and it is not an independent oracle.

## Determinism

Two clean runs with seed 1042 are byte-identical (`cmp`). The pool digest is
`fe2ed7d0f3354959e4f316c2c501765e47c697f0b9dbcc2d305f47c5917beade`.

## Gaps against the v1 contract (explicit, not invented)

- **Clock:** runoff is not modelled. `clock_seconds` after is null, and `clock_runoff_seconds` is null. Period clock
  before is derived from `game_seconds_remaining`.
- **Score and timeouts:** null. The table does not carry them.
- **Participants:** null. There is no pregame roster, so `passer_id`, `receiver_id` and `rusher_id` are null.
  Sampling real player IDs from other games would be a fabricated roster.
- **Provenance:** `as_of_utc`, `snapshot_hash` and `sources_as_of_verified` are null or false. The record is
  `mode: single_play_statistical_demo` with `valid_full_game: false`, not `pregame_full_game`.
- **Event families not modelled in E0:** punt, field goal, extra point, two-point try, kickoff, kneel, spike, fumble,
  penalty, interception, safety (as a sampled event), period end, game end, overtime.
- **Pregame snapshot:** none exists yet. The spec's M0 snapshot (schedule, as-of time, roster, availability) is not
  built.

## Gate E0 status (LP side)

| Requirement | Status |
| --- | --- |
| One legal synthetic play-result record, not a recorded outcome | **Done** for one play (seed 1042). Outcome sampled from other games, start row's outcome unused |
| Game ID, simulation/sequence IDs, pre-state, decision, terminal event, yards, elapsed time, stats, possession and clock effects, provenance | ID, pre-state, decision, event, yards and provenance **present**. Elapsed time, clock effect and stats **absent** (gaps above) |
| Reproducible from seed | **Done** (byte-identical rerun) |
| Pinned v1 payload agreed with Gridiron | **Not done.** Needs the Gridiron adapter side (hermes2 role in the plan) |
| Gridiron adapter accepts the record without changing it | **Not done.** Owned by the Gridiron agent |

## Smallest integration change proposed

1. The Gridiron adapter reads `plays[].state_before` and `state_after` and treats null clock, score, participants and
   `end_of_drive` as absent, with an explicit label. It must not fill them with defaults.
2. The E0 fixture is the pinned payload until the pregame snapshot exists. Its `mode` must not be displayed as a
   pregame full game.
3. E1 begins with the clock runoff model and the drive state machine. E0 does not cover those.

## Limits

- The start state comes from one 2025 historical play. The record is a demonstration, not a forecast.
- Outcomes come from the empirical distribution of other games in the same cell. There is no conditioning on score,
  clock, team, opponent, personnel or roster.
- The dev database is changing (modified at 02:00), so the counts above are a snapshot.
