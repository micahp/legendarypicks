# NFL sequence generator, LP E0 inventory and handoff (2026-10-24)

Plan: `docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md` (Gridiron repo, main).

**Status: partial E0.** LP has one reproducible, reducer-checked single-play record. The Gridiron adapter and the
agreed payload are **not** done; they are owned by the Gridiron agent (`hermes2`). E1 has not started and must not start
until both agents agree on this handoff (see "Interface and missing-field policy").

This record is a **retrospective demonstration**, not an as-of-time simulation (see "Temporal eligibility"). It is not
evidence that sampled outcomes reproduce real football. The reducer legality check below is a transition test, not a
football-validity test.

## Sources (exact commits)

| Artifact | Commit | Role |
| --- | --- | --- |
| `docs/GRIDIRON-CONTRACT-v1.md` (on `dev`) | 0b70548d | v1 payload. Byte-identical to the Gridiron mirror (sha256 `ae7b8a30…21b7`) |
| `docs/SPEC-nfl-pregame-play-sequence-generator-v1.md` (on `dev`) | bbd4d57a | Generator spec; status "proposed, not implemented" |
| `backend/nfl_sim.py`, `nfl_sim_scores.py`, `nfl_score_dist.py` (on `dev`) | 19092c69, 1e5fce62, 64bb93e8 | Season-level score simulators. Not play generators |
| `backend/ingest_nfl_pbp_logs.py` (on `dev`) | ad8f264f | Defines the curated `nfl_pbp` table |
| `scripts/nfl_sequence/e0_single_play.py` | this branch | E0 generator |
| `docs/fixtures/nfl-seq-e0-play-record-seed1042.json` | this branch | Pinned E0 record |

Branch `feat/nfl-sequence-e0-2026-10-24` is based on `dev` at cef6f987.

## Data source

- `nfl_pbp` is in `/root/legendarypicks/backend/data/picks.dev.db`, opened read-only. The production-named
  `backend/data/picks.db` has **no** `nfl_pbp` table.
- Season counts at the time of the check: 2010 44,991; 2011 45,455; … ; 2025 46,452; 2026 16,551 (partial).
- The file is still being written (3.23 GB at 02:08, up from 02:00). The 2022–2025 pool rows did not change: the
  pool digest below matched on rerun.
- The table has no score, timeout or pregame-roster columns, which matches the spec's warning.
- Regular season is `week <= 18`. `season_type` is not in the table, so playoff exclusion is approximate.

## Reproduction

```
cd /root/lp-nfl-sequence-e0
python3 scripts/nfl_sequence/e0_single_play.py --seed 1042 --out docs/fixtures/nfl-seq-e0-play-record-seed1042.json
python3 scripts/nfl_sequence/e0_single_play.py --seed 1042 --out /tmp/e0_rerun.json
cmp docs/fixtures/nfl-seq-e0-play-record-seed1042.json /tmp/e0_rerun.json && echo DETERMINISTIC
```

Expected output (seed 1042, dev database as checked):

```
pool validation: 125309 rows legal, illegal {}
  "cell": [1, "7-10", "80-99"], "cell_size": 5572
  "start": ["2025_05_LV_IND", 1638.0]
  "excluded_from_pool": {"penalty": 1962, "qb_scramble (E1)": 3860, "fumble_lost (E1)": 950, "interception (E1)": 1555}
  "pool_sha256": "fe2ed7d0f3354959e4f316c2c501765e47c697f0b9dbcc2d305f47c5917beade"
```

The rerun is byte-identical. Reproduction requires the same 2022–2025 rows in `picks.dev.db`. The `pool_sha256` digest
lets a consumer verify that.

## Reducer legality check

The script applies the reducer to **every** pool row before writing anything. It counts illegal down, yardline and
touchdown-flag results, and it refuses to write the record if any row is illegal.

- Result at the time of the check: **125,309 rows legal, 0 illegal**.
- What this shows: the reducer's transitions are legal for all reference rows (down 1–4, yardline 1–99 after the play,
  touchdown flag consistent with yards).
- What this does **not** show: that the sampled outcomes reproduce actual NFL results. The reducer is not an independent
  oracle, and no score, clock or participant is validated.

## Temporal eligibility (retrospective, not as-of)

The outcome pool is **not restricted to games before the start state**. Measured for seed 1042:

- Start state: `2025_05_LV_IND` play 1638, game date 2025-10-05, week 5.
- Cell (down 1, 7–10 yards, yardline 80–99): 5,572 plays from 2022–2025 regular season, start game excluded.
- Cell rows dated **after** the start game: **1,016 (18.2%)**. Of these, 1,008 are 2025 plays from weeks 6–18.
- The sampled outcome is from `2022_05_IND_DEN` (2022-10-06), which is before the start state. That draw is not
  evidence of as-of eligibility, because the pool as a whole contains future games.

**Conclusion:** seed 1042 is a **retrospective fixture**. The record marks this in
`outcome_pool.temporal_eligibility` (`status: "retrospective"`, `as_of_date: null`, counts above). Gridiron must not
present it as a pregame or forecast simulation. A genuine as-of run needs the pool restricted to games dated before the
as-of date, which is not implemented.

## Interface and missing-field policy (proposed, pending hermes2 agreement)

Top level (all required): `schema_version` ("1.0"), `mode` (`single_play_statistical_demo`), `valid_full_game` (false),
`simulation_id`, `game_id`, `model_version`, `rules_version`, `seed`, `teams` {home, away}, `plays`, `provenance`,
`summary`, `start_state_source`, `gaps`, `excluded_from_pool`, `outcome_pool`.

`provenance`: `outcomes` ("sampled_empirical_nfl_pbp"), `lineups`, `routes`, `motion` (all null in E0),
`sources_as_of_verified` (false), `as_of_utc` (null), `snapshot_hash` (null).

`outcome_pool`: `seasons`, `cell`, `cell_size`, `event_shares`, `start_game_excluded`, `pool_sha256`,
`temporal_eligibility` (`status`, `as_of_date`, `start_game_date`, `cell_rows_dated_after_start`, `cell_rows_total`,
`note`).

Per play (E0 has one play): `sequence` (int), `id` (`<simulation_id>:<sequence>`), `event_type` (one of `run`,
`pass_complete`, `pass_incomplete`, `sack`), `state_before` and `state_after`, `decision` {type, concept, coverage},
`outcome` {passer_id, receiver_id, rusher_id, yards_gained, touchdown, turnover, safety, clock_runoff_seconds,
sampled_from {game_id, play_id, game_date}}.

State fields: `quarter`, `clock_seconds`, `offense_team`, `defense_team`, `home_score`, `away_score`, `down`,
`yards_to_go`, `yardline_100` (offense-relative), `home_timeouts`, `away_timeouts`, `drive_index`. `state_after` may also
carry `end_of_drive` ∈ {`touchdown`, `safety`} and then has null down, distance and yardline.

**Missing-field policy (proposed):**

1. `null` means "not modelled, or not published by the source". It is never a default, and a consumer must not infer
   a value from it.
2. A consumer shows absent clock, score, timeouts, participants and `clock_runoff_seconds` as "not modelled". It must
   not fill them with zeros, guesses or a participant from another game.
3. `event_type` outside the E0 vocabulary is a hard error, not a run.
4. `temporal_eligibility.status` of `retrospective` must be displayed or the record refused. It is never shown as a
   pregame simulation.
5. `end_of_drive` non-null means the drive ends, and the kickoff or next possession is not generated. Consumers show it as
   a title card, not a replayed event.
6. Consumers must not alter `outcome`, `state_before` or `state_after`. Field conversion (for example
   `los = 100 - yardline_100` for `dir=+1`) is applied to a copy.
7. The record is `valid_full_game: false`. A consumer must reject any record that claims full-game validity without the
   E1/E2 fields.

**Open for hermes2 to confirm or change:** the field names above, the `null` policy, the refusal rules, and the
direction mapping (the contract says "from the versioned field/end-zone mapping" but no version is pinned yet).

## Gaps against the v1 contract (explicit, not invented)

- **Clock:** runoff not modelled. `clock_seconds` after is null, and `clock_runoff_seconds` is null. Period clock before
  is derived from `game_seconds_remaining`.
- **Score and timeouts:** null. The table does not carry them.
- **Participants:** null. No pregame roster, so `passer_id`, `receiver_id`, `rusher_id` are null.
- **Provenance:** `as_of_utc`, `snapshot_hash`, `sources_as_of_verified` are null or false.
- **Mode:** `single_play_statistical_demo`, not `pregame_full_game`.
- **Retrospective pool:** see "Temporal eligibility".
- **Event families not modelled:** punt, field goal, extra point, two-point try, kickoff, kneel, spike, fumble,
  penalty, interception, safety (as sampled event), qb_scramble, period end, game end, overtime. Interceptions,
  fumbles, penalties, scrambles and two-point tries are excluded from the pool and counted.
- **Pregame snapshot:** not built. The spec's M0 (schedule, as-of time, roster, availability) does not exist.
- **Direction mapping:** no versioned field/end-zone mapping is pinned for the Gridiron conversion.

## Gate E0 status (LP side)

| Requirement | Status |
| --- | --- |
| One legal synthetic play-result record, not a recorded outcome | **Done** for one play. Outcome sampled from other games; the start row's outcome is not read. Retrospective, not as-of |
| Game ID, simulation/sequence IDs, pre-state, decision, terminal event, yards, elapsed time, stats, possession and clock effects, provenance | ID, pre-state, decision, event, yards and provenance **present**. Elapsed time, clock effect and stats **absent** |
| Reproducible from seed | **Done**. Byte-identical rerun; pool digest verified |
| Reducer legality over reference rows | **Done**. 125,309 legal, 0 illegal (transition test only) |
| Pinned v1 payload agreed with Gridiron | **Not done.** Pending hermes2 agreement on the interface above |
| Gridiron adapter accepts the record without changing it | **Not done.** Gridiron agent's role |

## Not started

E1 (clock runoff, drive state machine, excluded event families) is **not** started. Per the agreed sequencing it waits
for the interface agreement above.
