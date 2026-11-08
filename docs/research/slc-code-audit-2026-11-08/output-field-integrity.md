# SLC reported output fields: aliases, allocations and non-reconciling stats

Audit of the SLC engine's reported team-boxscore and player-record fields. Scope, data and limits are
stated before any finding. Every empirical claim below is a count over a named CSV; "they look similar"
is never used as evidence.

- Repo: `C:\Users\micah\OneDrive\Documents\deepseek-harness\default-workspace\slc`, branch `slc-v2`, HEAD `d490757e6`.
- Code audited: the files that write the fields (`game_stats.py`, `slc_outputs.py`, `game_state.py`,
  `slc_engine.py`, `participant_field.py`, `player_shares.py`, `simulate_pregame_batch.py`, `e1_drive.py`)
  at HEAD, cross-checked against the commit that produced the data.
- Data audited: `docs/research/slc-scoring-review-2026-11-07/team-drive-tables/`
  `team-stats-{v1,v15,v2}.csv` (2,000 team-rows per arm) and `player-usage-{v1,v15,v2}.csv.gz`
  (124,000 player-rows per arm), plus `seed-outcomes/JAX-BAL-corrected-{v1,v15,v2}.csv`.
- Prior art: `scripts/prior_art.py` searched module docstrings, skills, `AGENTS.md`, `docs/` and code
  comments; no prior art found for snap/target/possession field semantics.

## 0. Provenance limits that bound every conclusion

1. **The bundle was produced by `9b5a1e43`, not HEAD `d490757e6`.** `game_stats.py` is byte-identical
   across the two commits, and `slc_outputs.py`/`game_state.py` differ only in the additions noted in
   §7.2 and §7.10. All field *definitions* audited below are the definitions that produced the CSVs.
2. **All 2,000 team-rows are `status = incomplete`.** The seed files say `complete_game = True` in
   1,000/1,000 seeds per arm and `valid_full_game = False` in 1,000/1,000; statuses are
   `complete_regulation` (962/956/965) and `complete_overtime` (38/44/35). So stats are end-of-game
   totals from games that finished but failed input-provenance validation — not partial blocked games
   (`blocker` is null in 2,000/2,000 rows).
3. **The CSV exporter is not in the repo.** Column names map 1:1 onto `slc_outputs.TEAM_FIELDS` /
   `PLAYER_FIELDS` (38 team columns = 9 identity/context + 22 team stats + 7 red-zone; 15 player
   columns = 9 identity + 6 player stats), and the manifest records the source as the boxscore sidecar.
   Mapping is inferred from names; `snaps` and `starter` are the only columns whose source needs code
   to establish (§5.2).
4. **3 of 3 arms have the same defects on the same fields**, with counts differing only where the arms
   differ in model layers (V2 is quoted as primary; V1/V1.5 counts are given where they differ).

Class definitions used in the census: **counted** = incremented per realized play/event;
**sampled** = drawn from a distribution; **allocated** = a counted team total redistributed to
individuals by a pre-outcome draw; **aliased** = equal to another reported field by construction;
**placeholder** = present but absent/constant because the producing path never ran.

## 1. Census of every reported team field

Producer function unless noted: `game_stats.team_stats()` (`scripts/nfl_sequence/game_stats.py:22`),
packaged by `slc_outputs.TEAM_FIELDS` (`slc_outputs.py:11-20`) and written by
`slc_outputs.build_boxscore()` (`slc_outputs.py:418-427`).

| Field | Class | Writer (file:line) | Verdict |
|---|---|---|---|
| `points` | counted (ledger), injected | `game_stats.py:106-107`; ledger from `game_state.py:1533,1556,1576,1581`, re-verified `game_state.py:1998-2002` | Correct total, but its scoring components are not exported (§3.4) |
| `touchdowns` | counted | `game_stats.py:91-94` | Includes return/defensive TDs; differs from `offensive_touchdowns` in 18/2000 rows (V1, V2) and 27/2000 (V1.5) |
| `offensive_touchdowns` | counted | `game_stats.py:95-102` | Correct; near-alias of `touchdowns` (r=0.997) |
| `observed_overtime_touchdowns` | counted, arm-dependent | `game_stats.py:98-105` | Constant 0 in V1 (2,000/2,000 rows); 21/2,000 non-zero in V1.5, 14/2,000 in V2 — placeholder in one arm (§5.3) |
| `drives` | counted | `game_stats.py:29-33` | Correct count; terminal classes are not reported, so it cannot be reconciled from the boxscore (§3.3) |
| `possession_seconds` | counted from clock states, **not a partition** | `game_stats.py:34-35` | Not possession time: 957/962 complete-regulation games sum below 3,600 s (§3.2) |
| `plays` | counted (scrimmage events only) | `game_stats.py:14,38-39` | Excludes punts/FGs/kickoffs (documented `slc_outputs.py:372-375`); **not equal to pass+rush+sacks** in 357/2,000 rows V1, 191/2,000 V1.5, 192/2,000 V2 (§3.1) |
| `rush_attempts` | counted | `game_stats.py:43-45` | Correct; reconciles to player carries 2,000/2,000 |
| `rushing_yards` | counted, goal-line capped | `game_stats.py:45,111-117` | Correct for its definition; capped on TDs by design, so it is not the sampled play's yardage (docstring `game_stats.py:6-8`) |
| `pass_attempts` | counted | `game_stats.py:46-51` | Correct (sacks excluded, as in the NFL convention); reconciles to player 2,000/2,000 |
| `completions` | counted | `game_stats.py:52-53` | Correct; reconciles 2,000/2,000 |
| `passing_yards` | counted, goal-line capped | `game_stats.py:54` | Equals sum of player receiving yards 2,000/2,000 |
| `interceptions` | counted | `game_stats.py:59-60` | Correct (== player sum in the engine's own check) |
| `targets` | counted, **aliased** | `game_stats.py:40-41` | **Equals `pass_attempts` in 2,000/2,000 rows** (§2.1) |
| `sacks_taken` | counted | `game_stats.py:47-49` | Only `event_type == 'sack'`; sack-fumbles recorded as `fumble_lost` are not sacks here (§3.1) |
| `sack_yards` | counted | `game_stats.py:49` | Negative by convention (median -7.0 yd/sack); a "yards" field whose sign is not stated |
| `punts` | counted | `game_stats.py:66-67` | Correct |
| `field_goal_attempts` | counted | `game_stats.py:68-73,85-90` | Correct |
| `field_goals_made` | counted | `game_stats.py:72,89-90` | Correct |
| `turnovers` | counted | `game_stats.py:57-62` | Equal to `interceptions+fumbles_lost` in 2,000/2,000 rows (identity, excludes downs) |
| `fumbles_lost` | counted | `game_stats.py:61-62` | Correct |
| `turnovers_on_downs` | counted | `game_stats.py:83-84` | Correct |

### Red-zone block (`slc_outputs._red_zone_diagnostics`, `slc_outputs.py:92-119`)

| Field | Class | Writer | Verdict |
|---|---|---|---|
| `red_zone_trips` | counted | `slc_outputs.py:101-106` | Drives with ≥1 play snapped inside the 20 |
| `red_zone_plays` | counted | `slc_outputs.py:107` | Plays whose pre-snap spot is inside the 20 |
| `red_zone_touchdowns` | counted | `slc_outputs.py:108-111` | Offensive TDs on red-zone drives |
| `red_zone_field_goal_attempts` | counted | `slc_outputs.py:112-113` | Correct |
| `red_zone_field_goals` | **aliased** | `slc_outputs.py:112-114` | **Equals `red_zone_field_goal_attempts` in 2,000/2,000 rows, every arm** — mislabelled duplicate (§2.2) |
| `red_zone_field_goals_made` | counted | `slc_outputs.py:115-116` | Correct |
| `red_zone_scoring_drives` | derived identity | `slc_outputs.py:117-118` | Equals `red_zone_touchdowns + red_zone_field_goals_made` in 2,000/2,000 rows (definitionally summed, no new information) |

Census: **22 team stat fields + 7 red-zone fields = 29 reported team values**. Exact duplicates found:
2 aliases (`targets`, `red_zone_field_goals`) plus 1 derived identity (`red_zone_scoring_drives`).
Near-duplicate: `offensive_touchdowns`/`touchdowns` (r = 0.997).

## 2. Alias and near-alias findings

### 2.1 `targets` is `pass_attempts` in 2,000/2,000 rows (all three arms)

`game_stats.py:40-41` increments `pass_tgt` for every `pass_complete`/`pass_incomplete`/`interception`
play that has `receiver_id`; `pass_att` (`game_stats.py:46-51`) increments for exactly the same event
set without the `receiver_id` guard. The event vocabulary has no throwaway, spike or intentional
grounding (`e1_drive.py:40-41`: `EVENTS = ('run','pass_complete','pass_incomplete','sack','interception',
'fumble_lost','punt','field_goal_attempt')`), and the pre-event chooser assigns a receiver to every pass
play, so the guard never excludes anything: the two team fields are the same number.

- Measured: `team-stats-v1.csv` 2,000/2,000 equal; `team-stats-v15.csv` 2,000/2,000; `team-stats-v2.csv` 2,000/2,000.
- Player side: sum of player `targets` equals `pass_attempts` in 2,000/2,000 team-rows.
- This equality is asserted by a test, i.e. it is intended behaviour, not a slip:
  `test_slc_football_invariants.py:144-162` builds 3 pass attempts and asserts `pass_tgt == 3`.
- Consequence: the team `targets` field carries zero information beyond `pass_attempts`, and the reported
  total hides the modelling fact that every attempt is assigned an intended receiver. NFL team targets
  are attempts minus throwaways/spikes; this engine has neither event.

### 2.2 `red_zone.red_zone_field_goals` is `red_zone_field_goal_attempts` in 2,000/2,000 rows

`slc_outputs.py:112-116`:

```python
if drive.get('field_goal_made') is not None:
    item['red_zone_field_goal_attempts'] += 1
    item['red_zone_field_goals'] += 1
    if drive['field_goal_made']:
        item['red_zone_field_goals_made'] += 1
```

The same `+= 1` guard increments both counters, so the column named `..._field_goals` counts attempts.
Measured equal in 2,000/2,000 rows in every arm (`team-stats-v1/v15/v2.csv`). The made count already
exists as `red_zone_field_goals_made`, so `red_zone_field_goals` is a mislabelled duplicate rather than
a missing statistic. It also propagates into the aggregate summary, which distributes both fields
(`slc_outputs.py:654-657`).

### 2.3 Other equality/near-equality results (not defects, recorded for completeness)

- `turnovers == interceptions + fumbles_lost`: 2,000/2,000 rows (definition, excludes downs).
- `red_zone_scoring_drives == red_zone_touchdowns + red_zone_field_goals_made`: 2,000/2,000 rows.
- `offensive_touchdowns == touchdowns`: 1,982/2,000 (V1, V2), 1,973/2,000 (V1.5); r = 0.997.
- Correlation scan over all 31 numeric team columns, |r| ≥ 0.98: only the three pairs above plus
  `red_zone_field_goals ~ red_zone_field_goals_made` at r = 0.982. No hidden aliases beyond §2.1-2.2.

## 3. Reconciliation failures (ranked)

### 3.1 `plays` ≠ `pass_attempts + rush_attempts + sacks_taken`

`game_stats.py:38-39` counts every event in `SCRIMMAGE_EVENTS = ('run','pass_complete','pass_incomplete',
'sack','interception','fumble_lost')` as a play, but `game_stats.py:43-56` counts only `run`/
`fumble_lost`-with-rusher as a rush, only `pass_complete/pass_incomplete/interception` as a pass attempt,
and only explicit `sack` events as sacks. A `fumble_lost` play with a passer and no rusher — the
sack-fumble/strip path — increments `plays` and increments **no** component.

Measured on `team-stats-*.csv`:

| Arm | rows where `plays == pass+rush+sacks` | rows where `plays > pass+rush+sacks` | unexplained scrimmage plays |
|---|---|---|---|
| V1 | 1,643/2,000 | 357/2,000 | 397 |
| V1.5 | 1,809/2,000 | 191/2,000 | 202 |
| V2 | 1,808/2,000 | 192/2,000 | 203 |

The residual is ≥1 and ≤3 per row, and `residual <= fumbles_lost` in 2,000/2,000 rows in every arm —
i.e. the missing plays are exactly lost-fumble events that are not also rush attempts. `plays ==
pass+rush+sacks+fumbles_lost` holds in only 1,640/1,895/1,901 of 2,000 rows because most lost fumbles
are already rush attempts. **The exported boxscore has no field that identifies the leftover plays**, so
`plays` cannot be reconstructed from the reported components, and the sack counter under-reports
sack-fumbles by the same events.

### 3.2 `possession_seconds` cannot sum to the 3,600 s regulation clock

`game_stats.py:34-35` sums, per drive, `elapsed(end_quarter,end_clock) - elapsed(quarter_start,clock_start)`
and nothing else. That is the sum of drive windows, not a partition of the game clock: time the clock
advances outside a drive is never credited to either team. In `game_state.py` the only such advance is
the kickoff/free-kick runoff (`_kick`, `game_state.py:753-793` sets `self.clock = after_clock` before
`_take_possession`), plus half-boundary handling. Overtime (played by the regulation simulator at HEAD,
`game_state.py:61`) adds drive windows beyond 3,600 s.

Measured (sum of both teams per seed, joined to `seed-outcomes/JAX-BAL-corrected-*.csv`):

| Arm | complete-regulation games | possession sum, median | sum == 3600 | sum < 3600 | sum > 3600 | 3600−sum, median [p5,p95] | OT games | OT sum, median |
|---|---|---|---|---|---|---|---|---|
| V1 | 962 | 3,575 | 5/962 | 957/962 | 0/962 | 25 s [10, 44] | 38 | 3,984 |
| V1.5 | 956 | 3,576 | 7/956 | 949/956 | 0/956 | 24 s [8, 44] | 44 | 3,980 |
| V2 | 965 | 3,575 | 8/965 | 957/965 | 0/965 | 25 s [10, 44] | 35 | 3,942 |

Every overtime game is over 3,600 s (38/38, 44/44, 35/35) and every overtime sum is short of
3,600 + 600 s by a median of 216-258 s across arms, so the field is neither a regulation partition nor a
full-game partition. Per-team values range 808-2,775 s, i.e. the two teams' values sum to the game value but the
game value is not a clock total. A reader who uses this field as time of possession gets a number that
is structurally 20-30 s low in regulation and 340-380 s high in overtime.

### 3.3 `drives` has no reported terminal breakdown, so the identity cannot be closed

The engine knows every drive's terminal (`drive['terminal']`, used by `game_stats.py:83-94` and by the
legality validator), and `slc_outputs._quarter_by_quarter` exports per-drive `terminal` in
`drive_summaries`. The team line itself exports `drives` with no terminal counters. Testing the
requested identity `drives = scoring_drives + punts + turnovers + end-of-half` with every exported
counter (`punts + field_goal_attempts + interceptions + fumbles_lost + turnovers_on_downs +
offensive_touchdowns`):

- Team-row unexplained remainder: V1 `{1: 961, 0: 533, 2: 476, 3: 22, 4: 4, -1: 4}`; V2 `{1: 953,
  0: 542, 2: 480, 3: 20, -1: 4, 4: 1}` of 2,000.
- Game-level remainder equals exactly 2 (the two half-ending drives) in 818/1,000 (V1), 819/1,000 (V1.5),
  806/1,000 (V2); remainder 0-5 in the rest.

The remainder is explained by terminal classes the team line does not report: end-of-half/end-of-regulation
drives (0-2 per team-game), overtime end, safeties (a scoring terminal absent from every team field), and
return/defensive touchdowns (scored by the other team's row). `drives` is not shown wrong; it is
**unreconcilable from the reported fields**, and the boxscore exports no counter for the missing classes.

### 3.4 `points` does not reconcile to `touchdowns*6 + field_goals_made*3`

`points` is the game's points ledger (`game_state.py:1618`), injected into the team line
(`game_stats.py:106-107`) and re-verified against drive points (`game_state.py:1998-2002`). The team line
reports `touchdowns`, `field_goals_made` and `points` but **no extra-point, two-point or safety field**
(tries are recorded only inside the unexported drive records, `game_state.py:1569-1578,1986-1994`).

Measured on `team-stats-*.csv`:

- `points == 6*touchdowns + 3*field_goals_made`: 114/2,000 rows (V1), 138/2,000 (V1.5), 163/2,000 (V2).
- Residual `points - (6*touchdowns + 3*field_goals_made)` ranges 0-8, never negative.
- Residual exceeds the maximum legal try contribution `2*touchdowns` in 18/2,000 rows (V1), 20/2,000 (V1.5),
  21/2,000 (V2) — those rows necessarily contain unexported safety points.

So the total is internally consistent but its components are only partially reported: a consumer cannot
reconstruct `points`, and the missing PAT/2-point/safety fields are exactly the ones a reconciliation
would need.

### 3.5 `targets` vs `receptions + incompletions`

`pass_attempts - completions - interceptions` (i.e. incompletions) is always ≥ 0 — 2,000/2,000 rows, range
[2,30] V1 / [1,28] V2 — but **incompletions are not a reported field**. Because `targets ≡ pass_attempts`
(§2.1), the requested identity `targets = receptions + incompletions` reduces to
`pass_attempts = completions + interceptions + incompletions`, which holds by construction and tells a
reader nothing. Receptions do equal completions: 2,000/2,000 team-rows.

## 4. What does reconcile: team totals vs player totals

Every player statistic that appears in **both** `player-usage-*.csv.gz` and `team-stats-*.csv` sums to the
team value exactly, per arm, joining on `(seed, team)` (2,000/2,000 matched team-rows in all arms):

| Team field | Player column(s) | Equal rows (V1 / V1.5 / V2) |
|---|---|---|
| `rush_attempts` | `carries` | 2,000/2,000 each |
| `rushing_yards` | `rush_yds` | 2,000/2,000 each |
| `pass_attempts` | `pass_att` | 2,000/2,000 each |
| `completions` | `receptions` | 2,000/2,000 each |
| `passing_yards` | `rec_yds` | 2,000/2,000 each |
| `targets` | `targets` | 2,000/2,000 each |

**Team and player totals reconcile, exactly, for every quantity this bundle exports on both sides.** That
is a genuine positive result and it should be stated as loudly as the failures.

Its limits:

1. The export contains 6 of the engine's 15 player stat fields. Missing: passing `comp`, `yds`, `td`,
   `int`, `sacked`, `sack_yds`; rushing `td`; receiving `td`; miscellaneous `fumbles_lost`. The engine's
   own `reconcile_boxscore` (`slc_outputs.py:541-559`) checks 13 team/player identities including
   touchdowns, interceptions, sacks and fumbles; **nine of the player fields it checks are absent from the
   bundle**, so those identities are unverifiable here.
2. `targets` reconciles trivially because both sides are the pass-attempt count (§2.1).

## 5. Allocated quantities presented without an allocation label

### 5.1 The player lines are allocations — and the engine says so

The boxscore is honest in the JSON: `game_stats.py:1-8` says *"Pregame player totals reconcile to the
generated team totals, but they are role allocations rather than player-specific performance projections
or a complete lineup. Every line carries `attribution`."*, and each player row carries
`attribution` plus a game-level `player_attribution` / `player_note` (`game_stats.py:194-218`, e.g.
*"Participants were selected before the outcome from the frozen pregame roster ... these lines are
allocations, not player-conditioned outcome projections."*). `player_shares.py:1-10` states the draw:
*"the pre-event choice draws a target or ball carrier among the players on the frozen snapshot roster in
proportion to them ... This is a first adapter."*

The **exported tables drop all of it**: `player-usage-*.csv.gz` has no `attribution`, no `player_note`,
and no lineup/layer flag. On the bundle surface, a column of per-player targets/carries is indistinguishable
from a decision record. This is an export defect, not an engine one, but it is the surface a reviewer reads.

### 5.2 `snaps` is a skill-lineup count, not a snap count

Source: `slc_engine.lineup_summary()` (`slc_engine.py:980-1000`), whose docstring is explicit:
*"Per-team skill snaps from the participation field's lineups: each scrimmage play the lineup was built for
counts one team snap, and one snap for every RB, FB, TE and WR on the field. QBs and linemen are not in the
lineup model."* The layer itself is flagged *"research, opt-in, not adopted"* (`participation_field.py:1`).

Measured on `player-usage-*.csv.gz`:

- V1 and V1.5: `snaps` is null in 124,000/124,000 rows per arm (no lineup record) — a placeholder column.
- V2: team-seed sums median 333, mean 333.2, range 184-487, against a theoretical minimum near 740
  (11 players × ~67 plays). The ratio to the team's `plays` is 4.96 — i.e. the column sums to ~5 skill
  players per snap, never 11.
- One player per team-seed is the leading passer, and **that player's `snaps` is 0 in 2,000/2,000
  team-seeds** (leading passer identified as the max-`pass_att` player per `(seed, team)`; 2,000 team-seeds,
  2,000/2,000 with `snaps == 0`).
- 12,682/51,000 starter rows (24.9%) have `snaps > 0`; 38,318/51,000 (75.1%) have `snaps == 0`. This is
  explained, not excused: the full-depth roster builder requires **exactly 28 starter roles per team**
  (`pregame_snapshot.py:187-210`, `starter_count != 28` raises; see also
  `build_full_depth_roster_snapshot.py:173-174`), while the lineup covers 5 skill spots.
- 2,734 player-rows hold production with `snaps == 0`: 2,000 are the passers (`pass_att > 0`) and 734 are
  RB/WR/TE with carries/targets/receptions. Of the 25,331 skill rows, 734 (2.9%) are credited production
  the lineup says they were not on the field for.
- Production above the reported snaps is widespread among skill players: 1,151 rows have `carries > snaps`,
  778 rows have `targets > snaps`.
- All 1,978 QB carry rows (scrambles) belong to players with `snaps == 0`.
- Example row (`player-usage-v2.csv.gz`, seed 1): Ameer Abdullah, RB, starter, 13 carries, 30 rush yd,
  `snaps = 0`.

Two engine components disagree about who was on the field on the same play: the participation field draws
the lineup, `player_shares`/`pre_event` draw the ball carrier and target from the whole roster. That is an
ownership mismatch in the allocation, not merely a naming problem.

### 5.3 `starter` is a depth-chart role flag, not a playing-time claim

`starter` comes from the frozen full-depth roster (`_roster_index` `slc_outputs.py:70-73`), which requires
28 starter roles per team. Measured: 51,000/124,000 player-rows are `starter = True` (41%); per team-seed
25-26 distinct players hold the 28 roles. It is a legitimate flag, but a reader will take "starter" to mean
"plays"; combined with §5.2 it produces the misleading picture that 75% of starters never took a snap.

### 5.4 `targets`/`carries` are pre-outcome share draws presented as a team total

§2.1 shows the team-level target total is redundant; at player level the recipient is drawn before the
outcome from historical team shares (`player_shares.py:1-10,20-50`). The team count is a real event count;
the individual attribution is an allocation. Nothing in the team line says which is which.

## 6. Placeholders and constant fields

| Field | Where | Measured |
|---|---|---|
| `snaps` | `player-usage-v1.csv.gz`, `player-usage-v15.csv.gz` | null 124,000/124,000 rows per arm |
| `observed_overtime_touchdowns` | `team-stats-v1.csv` | 0 in 2,000/2,000 rows; non-zero in 21/2,000 (V1.5) and 14/2,000 (V2). It is a reconciliation carve-out — `game_stats.py:103-105` sets it only for `observed_overtime_drive` rows with no plays, and it is subtracted again in the player check (`game_stats.py:247-248`) — not an independent statistic. Its presence in two arms and absence in one is unexplained and worth a follow-up. |
| `blocker` | all team CSVs | null 2,000/2,000 — correct (no blocked seeds in the corrected rerun), not a placeholder |
| `player_projections` | batch payload `simulate_pregame_batch.py:1179` | Built only from `valid_full_game` seeds (`:1044-1051,564-568`); with 0 valid seeds `_player_projections` returns `{'sample_games': 0, 'players': []}` (`:385-387`). A consumer sees an empty list, not an error, when no seed validated. |
| `status` | all team CSVs | constant `incomplete` 2,000/2,000 while the same seeds report `complete_game = True` in 1,000/1,000 — see §7.1 |

No other team field is constant or all-zero in any arm: all 31 numeric columns have ≥3 distinct values in
the 2,000-row tables except `observed_overtime_touchdowns` (V1) and `blocker` (all arms).

## 7. Name / semantics defects (correct number, misleading name)

### 7.1 `status = "incomplete"` for complete games (2,000/2,000 rows)

`_box_status` (`slc_outputs.py:524-533`) returns `valid_complete` only for `valid_full_game`, then
`regulation_tie`, `error`, `blocked`, and otherwise **`incomplete`**. A complete game with unverified input
therefore lands in `incomplete`. Measured: `team-stats-*.csv` `status` is `incomplete` in 2,000/2,000 rows
in every arm, while `seed-outcomes/*.csv` says `complete_game = True` in 1,000/1,000 seeds and
`status = complete_regulation/complete_overtime` in 1,000/1,000. The two exports of the same run disagree
about whether the games are complete. The label needs a separate "complete but unverified" state.

### 7.2 The snap-vs-production guard is unreachable at HEAD

`reconcile_boxscore` reads `boxscore['realism']['lineup']['player_snaps']` (`slc_outputs.py:587-598`), but
`build_boxscore` computes the reconciliation at `slc_outputs.py:505`, while the batch attaches
`boxscore['realism']` only later (`simulate_pregame_batch.py:525-527`, `:561`). The value is therefore
always `None` and the `player_stats_exceed_snaps` branch can never fire, even with `--export-plays`.
`reconcile_boxscore` has exactly one call site, `slc_outputs.py:505` inside `build_boxscore`; the batch
only calls `build_boxscore` (`simulate_pregame_batch.py:521`, `:558`). The check also did not exist at the
bundle commit — `git diff 9b5a1e43 HEAD -- slc_outputs.py` shows it added afterwards — so in this bundle
the 734 off-field production rows and 1,151 `carries > snaps` rows were never even eligible to be flagged.

### 7.3 Two different "plays" in one record

`team.plays` is scrimmage snaps excluding special teams, while `drive_summary_by_team_and_period.plays`
counts all recorded events including punts and field goals. The difference is documented in the same record
(`slc_outputs.py:372-375`, `play_stats_scope` at `:376`), but the identical key name in the same JSON is a
trap for a consumer.

### 7.4 Yardage is capped, so "yards" is not the sampled play's yards

`_credited` (`game_stats.py:111-117`) clips a touchdown's yards to the distance to the goal line. The
docstring states why (`game_stats.py:6-8`: *"a line that said otherwise would contradict the field"*).
This is an honest, documented definition difference, not a defect; it does mean `rushing_yards`/
`passing_yards` are simulation-credited, not observed-play, yardage.

### 7.5 Smaller name issues

- `sack_yards` is negative (median -7.0 per sack); no field states the sign convention.
- `home_points`/`away_points` are per-game constants denormalised onto both team rows; they equal each
  row's `points` for its own side (1,000/1,000 home rows, 1,000/1,000 away rows) and carry no new information.
- `red_zone_scoring_drives` is the sum of two other reported fields (§2), i.e. a derived duplicate.
- `touchdowns` includes return/defensive scores; the separation from `offensive_touchdowns` is real
  (18/2,000 or 27/2,000 rows) and correctly named once the pair is read together.

## 8. Ranked defect list

Severity: **HIGH** = a reader using the field as named draws a materially wrong conclusion;
**MEDIUM** = the number is defensible but the field cannot be reconciled or its label conflicts with
another export; **LOW** = duplication/naming/coverage.

1. HIGH — `targets` is identically `pass_attempts` in 2,000/2,000 rows, every arm (§2.1). The team's target
   total is a duplicate; the model has no throwaway/spike event, so every attempt is assigned a receiver.
2. HIGH — `possession_seconds` is a sum of drive windows, not possession time: 957/962 complete-regulation
   games sum below 3,600 s (median 3,575), all overtime games above it (median 3,942-3,984 across arms), and the field cannot
   be a clock partition by construction (§3.2).
3. HIGH — `snaps` reports ~5 skill players per snap: team-seed sums median 333 against a ≥740 expectation,
   the leading passer has 0 in 2,000/2,000 team-seeds, 75.1% of starters are 0, and 2,734 production rows
   carry `snaps = 0` (§5.2).
4. HIGH — `red_zone_field_goals` is `red_zone_field_goal_attempts` in 2,000/2,000 rows (§2.2).
5. MEDIUM — `plays` is not reconstructible from reported components: `plays > pass+rush+sacks` in
   357/2,000 (V1), 191/2,000 (V1.5), 192/2,000 (V2) rows; 397/202/203 scrimmage events have no component
   field, and they are also missing from `sacks_taken` (§3.1).
6. MEDIUM — `drives` cannot be reconciled from the reported fields: no terminal counters for end-of-half,
   overtime end, safeties or return touchdowns; unexplained remainder 0-5 per team-row, exactly 2 per game
   in 806-819/1,000 games (§3.3).
7. MEDIUM — `points` cannot be reconstructed: equals `6*touchdowns+3*field_goals_made` in only
   114-163/2,000 rows; PAT/two-point/safety components are unexported; 18-21 rows require safety points
   (§3.4).
8. MEDIUM — boxscore `status` says `incomplete` on 2,000/2,000 team-rows while the seed record says
   `complete_game = True` 1,000/1,000 (§7.1).
9. MEDIUM — the snap-vs-production reconciliation check is dead code at HEAD because the realism block is
   attached after `reconcile_boxscore` runs; the check also postdates the bundle (§7.2).
10. LOW/MEDIUM — `observed_overtime_touchdowns` is a reconciliation carve-out, constant 0 in V1
    (2,000/2,000) but non-zero in V1.5/V2; arm-dependent, needs explanation (§6).
11. LOW — the player-usage export drops `attribution`, `player_note` and the layer flag, so the allocation
    disclosure the engine makes in JSON disappears at the CSV surface (§5.1).
12. LOW — `starter` is a 28-role depth-chart flag; 41% of player rows are "starters" and 75% of them have
    zero snaps (§5.3).
13. LOW — the player export omits 9 of 15 player stat fields, including every touchdown, sack and
    interception, so those team/player identities cannot be checked from the bundle (§4).
14. LOW — `sack_yards` negative sign undocumented; duplicated `home_points`/`away_points` columns;
    derived duplicate `red_zone_scoring_drives` (§7.5).

## 9. Direct answers to the five flagged questions

1. **Aliases/near-aliases (empirical):** yes, two exact aliases (`targets` = `pass_attempts`, 2,000/2,000;
   `red_zone_field_goals` = `red_zone_field_goal_attempts`, 2,000/2,000) and one near-alias
   (`offensive_touchdowns` ≈ `touchdowns`, r = 0.997). No other pair of the 31 numeric team columns is
   equal in ≥99% of rows or correlated above 0.98.
2. **Fields that cannot reconcile to the play records:** `possession_seconds` (clock partition),
   `plays` (missing fumble-lost component), `drives` (missing terminal classes), `points` (missing
   PAT/2-point/safety components). `targets` and `red_zone_field_goals` reconcile trivially because they
   are duplicates.
3. **Allocated quantities without an allocation label:** the whole player stat table (labelled in the JSON
   boxscore, unlabelled in the exported CSV), `snaps` (skill-lineup count), `starter` (depth-chart role),
   and per-player `targets`/`carries` (pre-outcome share draws).
4. **Counters that should sum to a total but do not:** `plays` vs pass+rush+sacks (357/2,000 V1,
   192/2,000 V2); `drives` vs any combination of reported terminal counters (remainder -1 to 4 per row);
   `points` vs `6*touchdowns+3*field_goals_made` (1,837-1,886 of 2,000 rows fail). **Team vs player totals
   do reconcile: 2,000/2,000 in all six exportable quantities, all arms.**
5. **Present but always null/zero/constant:** `snaps` (V1, V1.5: 124,000/124,000 null each);
   `observed_overtime_touchdowns` (V1: 0 in 2,000/2,000); `status` (constant `incomplete`);
   `blocker` (null, correctly); `player_projections.players` (empty when no seed validates).

## 10. How the counts were produced

Read the CSV with pandas, group by `(seed, team)`, join team rows to player aggregates on `(seed, team)`
(1:1, full coverage in every arm), and compare columns row by row; join `(seed)` to the seed-outcome CSVs
for game status, overtime and cross-file points. Identities tested are listed in §2-§4 with the exact
column pairs. Decimal values in the tables are medians/means of integer counts from the named CSVs; the
"equal in N of M" figures are exact column-equality counts, not tolerances.

Key code references: `game_stats.py:22-108` (team counters), `:111-124` (yardage credit),
`:127-191` (player lines), `:194-261` (allocation notes and the pregame reconciliation);
`slc_outputs.py:11-26` (field maps), `:92-119` (red zone), `:405-521` (boxscore assembly),
`:524-533` (status), `:536-606` (reconciliation); `game_state.py:753-793` (kickoff clock outside drives),
`:929-960` (drive windows), `:1434-1595` (drive terminals and points), `:1607-1673` (record),
`:1973-2002` (points ledger validation); `slc_engine.py:980-1000` (lineup/snap summary);
`participation_field.py:1-18`; `player_shares.py:1-55`; `simulate_pregame_batch.py:385-434` (player
projections and seed outcome), `:519-562` (boxscore export and realism ordering), `:1044-1051`
(player totals); `e1_drive.py:36-46` (event vocabulary); `pregame_snapshot.py:187-210` and
`build_full_depth_roster_snapshot.py:173-174` (28 starter roles).

No source file was modified. Analysis was read-only over the repo and the exported CSVs.
