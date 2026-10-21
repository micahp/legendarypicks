# NHL full-frame event reconciliation

**Run status:** Final full-frame audit, independent replay, artifact comparison,
and failure-injection suite passed on 2026-10-21.

**Decision:** Approve [event schema v1](PROPOSED-SCHEMA.md) for preliminary
chronological simulator design. Team scoring and selected player targets have
measured eligible populations. Every event, player identity, goalie identity,
spatial feature, and shift deployment remains gated by its own disposition.
Preliminary simulator design can begin against the approved chronology and
component-level schema. This authorization does not fit a simulator or change
production data.

## 1. Source coverage and integrity

The canonical frame contains 4,876 regular-season games: 2018 (1,271), 2019
(1,082), 2020 (868), 2021 (1,312), and 2022 (343). Both PBP and shift-chart
evidence were verified for every game. There were no failed requests, missing
bodies, duplicate or extra manifest IDs, or source-integrity issues. All
4,876 rows in each hardened source manifest matched their corresponding rows in
the earlier full-frame manifests.

| Source | Verified | Compressed bytes | Decompressed bytes | Hardened manifest SHA-256 |
|---|---:|---:|---:|---|
| NHL play-by-play | 4,876 / 4,876 | 51,293,401 | 596,487,543 | `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990` |
| NHL shift charts | 4,876 / 4,876 | 71,197,704 | 1,339,338,887 | `deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5` |

Each compressed and decompressed body hash, body length, source URL, source and
game identity, JSON shape, row count, sidecar, and manifest entry was checked.
The original 300-game sample files, manifest, and audit reports remain
unchanged. The hardened source lists, manifests, and reports are separate.

| Season | Frame games | PBP verified | Shift charts verified | PBP events | PBP shots | Ordinary shots | Shootout shots | Regulation goals | OT goals | SO goal events excluded | Penalties | Score match | SOG match | Missing shot coordinates | Unblocked shots missing type |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 1,271 | 1,271 | 1,271 | 402,616 | 147,133 | 146,494 | 639 | 7,393 | 184 | 188 | 9,035 | 1,271 | 1,259 | 6 | 12 |
| 2019 | 1,082 | 1,082 | 1,082 | 335,749 | 123,378 | 122,757 | 621 | 6,284 | 164 | 200 | 7,809 | 1,082 | 1,065 | 1 | 10 |
| 2020 | 868 | 868 | 868 | 258,119 | 94,320 | 93,872 | 448 | 4,901 | 130 | 145 | 6,009 | 868 | 857 | 0 | 4 |
| 2021 | 1,312 | 1,312 | 1,312 | 404,656 | 149,412 | 148,665 | 747 | 7,964 | 186 | 224 | 9,696 | 1,312 | 1,292 | 0 | 3 |
| 2022 | 343 | 343 | 343 | 108,964 | 40,098 | 39,949 | 149 | 2,104 | 51 | 55 | 2,868 | 343 | 341 | 0 | 2 |
| **All** | **4,876** | **4,876** | **4,876** | **1,510,104** | **554,341** | **551,737** | **2,604** | **28,646** | **715** | **812** | **35,417** | **4,876** | **4,814** | **7** | **31** |

Counts in the table are derived from verified PBP. Ordinary shots are goals,
on-target non-goals, misses, and blocks with every shootout event excluded.
Official SOG includes goals and `shot-on-goal` events; it excludes shootout
attempts. For final score reconciliation, PBP regulation/overtime goals matched
all 4,876 official scores after applying the official shootout winner's separate
one-goal score adjustment. Shootout goal events were never added to ordinary
goals.

| Season | Ordinary on-target events | Misses | Blocks | Empty-net state events | Penalties without committed player | Shooter identity issues | Goalie identity issues | Event-owner identity issues |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 79,954 | 30,392 | 36,263 | 9,676 | 279 | 4 | 0 | 0 |
| 2019 | 67,983 | 25,261 | 29,617 | 8,025 | 312 | 11 | 14 | 0 |
| 2020 | 52,033 | 19,351 | 22,561 | 6,318 | 205 | 8 | 0 | 0 |
| 2021 | 83,004 | 30,424 | 35,375 | 10,405 | 267 | 12 | 0 | 0 |
| 2022 | 21,637 | 8,196 | 10,135 | 2,983 | 74 | 2 | 0 | 0 |

Every penalty has valid event timing and duration in each season. Missing
committed-player IDs include legitimate bench penalties; individual penalty
attribution has its own disposition. Season-level event, type, strength, and
identity metrics are also retained at game granularity in `game_metrics.csv`.

Approved-label event eligibility by season (`matched / approved eligible`):

| Season | Player SOG | Goalie goals against | Goalie saves | Goalie shots against |
|---|---:|---:|---:|---:|
| 2018 | 45,742 / 45,755 | 2,720 / 2,720 | 2,714 / 2,720 | 2,714 / 2,720 |
| 2019 | 38,931 / 38,949 | 2,306 / 2,306 | 2,293 / 2,306 | 2,293 / 2,306 |
| 2020 | 31,215 / 31,226 | 1,852 / 1,852 | 1,845 / 1,852 | 1,845 / 1,852 |
| 2021 | 47,188 / 47,208 | 2,817 / 2,818 | 2,802 / 2,818 | 2,801 / 2,818 |
| 2022 | 12,342 / 12,344 | 721 / 721 | 721 / 721 | 721 / 721 |

The aggregate derived shot types are wrist 229,126; slap 61,154; snap 56,087;
backhand 31,254; tip-in 28,502; deflected 10,389; wrap-around 3,648; poke 102;
bat 74; between-legs 22; and cradle 1. The published blocked-shot type is
absent throughout this frame.

## 2. Event, identity, and outcome findings

- Shot-family events: 554,341; ordinary shots: 551,737; shootout attempts
  excluded: 2,604. The separate event counters report 133,951 blocks, 113,624
  missed-shot events, and 304,611 ordinary on-target events. Miss counters
  include any shootout misses, so these category totals are not additive; the
  row-level event ledger retains the period type for each play.
- PBP event-owner identity issues: 0. Shooter identity issues: 37 events in 36
  games. The goal-scoring ID is used as a documented fallback on 30,173 goals
  that lack a direct shooter ID. Do not reinterpret the fallback as a directly
  observed shooter.
- Shot coordinates: 7 of 554,341 events lack a valid coordinate pair
  (99.9987% coverage). Keep the missing values null. The seven game/event keys
  are `2018020055/901`, `2018020573/446`, `2018020963/50`, `2018020993/941`,
  `2018021114/87`, `2018021122/14`, and `2019020349/774` (the last is a
  shootout event).
- Shot type: all 133,951 blocked shots lack a type in the feed; blocked-shot
  type is `NOT_APPLICABLE` unless explicitly published. Of 420,390 unblocked
  shots, 420,359 have a type and 31 do not. The 31 events span 28 games and are
  listed under `UNBLOCKED_SHOT_TYPE_MISSING` in the issue ledger.
- PBP versus official SOG: 4,814 games reconcile; 62 games are quarantined.
  There are 63 side-specific issue rows: 62 differ by +1 and one differs by +2
  in game `2018020751`, for 64 excess PBP SOG across the affected sides. Game
  `2019020876` has +1 on both sides. The two +1 differences discovered in the
  original sample, `2019020372` and `2021020345`, remain unresolved. No official
  total was changed and no event was added or removed to force a match.
- Goals against approved player labels: one mismatch remains in game
  `2021020368`, goalie `8477992` (4 PBP-attributed goals against versus 3
  accepted official-label goals against). Saves and shots-against event counts
  also disagree with approved labels for 42 and 43 player-game rows,
  respectively. These rows are excluded from those event-derived targets.
- Strength and empty-net state: 37,407 events carry an empty-net state.
  Regulation/overtime strength categories are derived from the raw PBP
  situation code. Shootout rows are outside the ordinary strength and shot
  targets. Preserve the source code alongside every derived state. Frame-wide
  state counts are EV 5v5 1,218,706; PP home 5v4 106,183; PP away 5v4 95,990;
  EV 4v4 18,041; EN away pulled 18,865; EN home pulled 18,152; EV 3v3 12,185;
  PP home 5v3 2,779; PP away 5v3 2,375; PP home 4v3 1,622; PP away 4v3 1,269;
  and both goalies pulled 390.
- Penalties: all 35,417 have timing and valid duration; duration remains in
  source minutes. There are 1,137 events with no committed-player assignment,
  including bench penalties. The issue ledger separately identifies 8 missing
  committed-player identities, unresolved committed-player IDs, and unresolved
  drawn-player IDs. Individual attribution is quarantined where identity is
  unresolved.
- Goalie event identity: 417,626 shot-family rows contain direct PBP goalie IDs;
  415,241 meet the stricter ordinary-event, event-key, team, and official
  appearance gates for event attribution. There are 14 identity issues: 13
  unexplained missing in-net IDs in 11 games and one direct ID not found among
  official appearances (`2019020604`). Another 1,580 on-target
  events without a goalie ID are explained by the source situation code showing
  an empty net. PBP records 695 goalie substitutions across 658 team-game
  appearances.
- Goalie shift charts are not used to assign saves or shots faced. Direct PBP
  goalie identity and accepted official goalie targets are the event evidence;
  official boxscore TOI is the authoritative goalie duration.

## 3. Shift chart and deployment reconciliation

Across all games, 3,448,108 shift intervals are accepted, 5,292 quarantined,
and 290,560 rejected. The accepted intervals cover 162,310 skater player-games
and 9,578 goalie player-games. Of 175,482 skater player-game TOI comparisons,
173,765 are within 30 seconds of official TOI; 1,717 exceed 30 seconds and
1,176 exceed 60 seconds. Of 10,432 goalie comparisons, 10,316 are within 30
seconds; 116 exceed 30 seconds and 104 exceed 60 seconds. Official boxscore TOI
remains authoritative.

| Season | Accepted intervals | Quarantined intervals | Rejected intervals | Accepted skater player-games | Accepted goalie player-games | Skater TOI within 30s / compared | Goalie TOI within 30s / compared |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 976,533 | 657 | 2 | 45,728 | 2,711 | 45,729 / 45,755 | 2,714 / 2,727 |
| 2019 | 824,423 | 1,078 | 2 | 38,906 | 2,276 | 38,907 / 38,949 | 2,276 / 2,306 |
| 2020 | 558,838 | 892 | 107,794 | 26,401 | 1,560 | 30,553 / 31,226 | 1,824 / 1,854 |
| 2021 | 859,226 | 2,567 | 149,119 | 40,482 | 2,402 | 46,359 / 47,208 | 2,781 / 2,821 |
| 2022 | 229,088 | 98 | 33,643 | 10,793 | 629 | 12,217 / 12,344 | 721 / 724 |

There are 12 full duplicated charts, 360 games with exact duplicate shift
intervals, and 376 games with overlapping shifts. Do not deduplicate or adjust
any interval without new evidence. The full duplicated-chart games are:
`2020020056`, `2020020057`, `2020020279`, `2020020281`, `2020020362`,
`2020020363`, `2021020227`, `2021020228`, `2021020541`, `2021020544`,
`2021020948`, and `2021020949`.

The final event-level player-on-ice population contains 467,900 accepted
ordinary-shot attributions and 83,837 quarantined attributions. Situation-code
versus shift comparisons contain 1,289,635 accepted matches and 216,399
quarantined events. Direct goalie-to-shift comparison has 380,951 accepted
matches and 34,290 quarantined comparisons. These are deployment comparisons
only; shift charts do not reveal actual player movement, puck location, or
possession.

## 4. Chronology and event schema

The publisher provides a complete chronology key: `sortOrder` was present,
unique, and strictly increasing for all 1,510,104 plays. Preserve this integer
as `publisher_sort_order`; retain zero-based source-array position as
`source_play_index`. Sort by publisher order and keep period and source clock as
separate observed fields. Do not order by event ID or clock alone.

Five games have 105 total period-number sequence regressions:
`2018020164`, `2018020176`, `2018020189`, `2018020367`, and `2018020416`.
Preserve their event order and independently reconciled team outcomes; quarantine
period-dependent joins to shifts and event deployment. Do not silently repair
period numbers. The final artifact marks 1,571 affected event rows and
period-dependent comparisons with `PBP_PERIOD_NUMBER_SEQUENCE_REGRESSION` or
`PBP_PERIOD_NUMBER_UNTRUSTED`, while retaining their accepted source order.

The approved schema defines the game timeline, shot outcomes, stable player and
goalie IDs, score/manpower state, penalties and power plays, player shift
intervals, and event provenance/quality. It labels fields as directly observed,
derived, unavailable, or unreliable. It does not claim to observe continuous
elapsed wall time, actual player movement, puck tracking, possession, or the
latent state a simulator must infer. See [PROPOSED-SCHEMA.md](PROPOSED-SCHEMA.md)
and [DISPOSITION-RULES.md](DISPOSITION-RULES.md).

## 5. Model-eligible populations

These populations respect the approved NHL research-label quality flags. The
same counts apply to training, evaluation, and grading because the approved
foundation exposes the same eligible rows for those splits. Event-derived
counts must still match the accepted official label row.

| Target | Approved eligible labels | Event-count matched and eligible | Excluded for event mismatch |
|---|---:|---:|---:|
| Team score | 4,876 games | 4,876 | 0 |
| Team SOG | 4,876 candidate games | 4,814 | 62 |
| Player SOG | 175,482 player-games | 175,418 | 64 |
| Goalie goals against | 10,417 goalie-games | 10,416 | 1 |
| Goalie saves | 10,417 goalie-games | 10,375 | 42 |
| Goalie shots against | 10,417 goalie-games | 10,374 | 43 |

For shift-derived player-on-ice features, only accepted intervals and accepted
event-time alignments are eligible. Final populations are 3,448,108 accepted
shift intervals, 467,900 accepted ordinary-shot skater attributions, and
1,289,635 accepted situation-code/shift matches. Direct goalie IDs remain
independently auditable; no goalie target is created from goalie shifts.

## 6. Unresolved issue ledger

The complete discrepancy ledger is
`/root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-final/unresolved_issues.csv.gz`.
It has one row per unresolved source/event/player/game discrepancy, including
`game_id`, subject type and ID, event/player key when available, reason code,
observed details, and disposition. It is the authoritative exhaustive mapping
from every unresolved discrepancy to its exact IDs. The final ledger has
124,514 rows and SHA-256
`b6b39dcb332963ff9f4a08d22ae6a4d958333a700db3daa32f489273e88614fb`.
The replay ledger is byte-identical.

| Reason code | Rows | Games |
|---|---:|---:|
| `DIRECT_GOALIE_SHIFT_DEPLOYMENT_UNTRUSTED` | 31,893 | 414 |
| `DIRECT_GOALIE_VS_SHIFT_CHART_MISMATCH` | 327 | 316 |
| `DUPLICATE_SHIFT_CHART` | 467 | 12 |
| `DUPLICATE_SHIFT_INTERVAL` | 25,862 | 360 |
| `ON_TARGET_GOALIE_ID_MISSING_UNEXPLAINED` | 13 | 11 |
| `PBP_GOALS_AGAINST_VS_APPROVED_LABEL` | 1 | 1 |
| `PBP_PERIOD_NUMBER_SEQUENCE_REGRESSION` | 1,571 | 5 |
| `PBP_SAVES_VS_APPROVED_LABEL` | 42 | 42 |
| `PBP_SHOTS_AGAINST_VS_APPROVED_LABEL` | 43 | 43 |
| `PBP_SOG_VS_APPROVED_LABEL` | 64 | 62 |
| `PBP_SOG_VS_OFFICIAL` | 63 | 62 |
| `PENALTY_COMMITTED_PLAYER_ID_UNRESOLVED` | 224 | 205 |
| `PENALTY_COMMITTED_PLAYER_MISSING` | 8 | 8 |
| `PENALTY_DRAWN_PLAYER_ID_UNRESOLVED` | 454 | 419 |
| `PLAYER_SHIFT_OVERLAP` | 14,940 | 376 |
| `SHIFT_DURATION_DISAGREES_WITH_INTERVAL` | 116 | 4 |
| `SHIFT_INTERVAL_INVALID` | 1,173 | 191 |
| `SHIFT_PLAYER_OFFICIAL_NONAPPEARANCE` | 13 | 13 |
| `SHIFT_TEAM_IDENTITY_MISMATCH` | 742 | 1 |
| `SHIFT_TOI_OUTSIDE_30S` | 1,833 | 446 |
| `SHOOTER_EVENT_SHIFT_DEPLOYMENT_UNTRUSTED` | 36,709 | 445 |
| `SHOOTER_REPORTED_OFF_ACCEPTED_SHIFT` | 67 | 44 |
| `SHOT_COORDINATES_MISSING_OR_INVALID` | 7 | 7 |
| `SHOT_EVENT_GOALIE_ID_NOT_IN_OFFICIAL_APPEARANCES` | 1 | 1 |
| `SHOT_SHOOTER_ID_NOT_IN_OFFICIAL_SKATERS` | 37 | 36 |
| `SITUATION_CODE_VS_SHIFT_CHART_MISMATCH` | 7,813 | 480 |
| `UNBLOCKED_SHOT_TYPE_MISSING` | 31 | 28 |

`PBP_PERIOD_NUMBER_SEQUENCE_REGRESSION` covers 105 period transitions in five
games. The ledger includes every affected event and player comparison with its
game/event/player IDs and reason code. All unresolved rows remain available in
the external gzip ledger; the table summarizes row and unique-game counts.

## 7. Reproducibility and release boundary

The hardened importer uses separate source lists, manifests, and reports; checks
existing bodies before requesting; resumes from valid cached bodies; preserves
raw response bodies outside Git; writes progress and final manifests atomically;
and stops on access refusal or rate limiting. Request duration is not estimated
from pacing alone: the measured 27-body sample was 31.327 seconds including the
0.9-second pause (1.1603 seconds per body; about 88.5 minutes per source for
4,576 requests at that mean, about 177 minutes sequentially). The completed
full-frame runs reused valid cached evidence and made no new requests.

The deterministic importer/auditor failure-injection suite passed all 19 tests.
It covers source identity and payload-shape failures, compressed hash failures,
cache reuse and resume, refusal/rate limiting, atomic manifest preservation,
body non-overwrite, shift rejection/quarantine, score convention, aggregation,
publisher-order anomalies, and period regressions. Both full audit runs
completed all 4,876 games. All six CSV/gzip data artifacts matched byte-for-byte;
the normalized JSON reports were equal after removing only run timestamp and
output-directory metadata. Final SHA-256 values:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `event_dispositions.csv.gz` | 34,744,326 | `c5ee8cc948e8de2f070d6b5b417d3756a731135d771d91d911d3e0f24c356e1f` |
| `game_metrics.csv` | 4,506,345 | `7162cb7bdc0859f6d6310702e44557e84724584b27abdc958cdcfe192d1d3a17` |
| `game_source_provenance.csv.gz` | 1,012,808 | `33ae97e296b797ef8e5a68e5b1e8e391ed563a3c2c1495de6e376ee797618013` |
| `player_shift_dispositions.csv.gz` | 30,612,139 | `c665ef85477c34a8accabff260a87111838a6f5f6c28228cab6c65fced23be82` |
| `target_reconciliation.csv.gz` | 1,822,672 | `f093d8108a5492a2bd1c7400e71b2fa8b2c782d66ee3cba855ba85e110166a47` |
| `unresolved_issues.csv.gz` | 985,234 | `b6b39dcb332963ff9f4a08d22ae6a4d958333a700db3daa32f489273e88614fb` |

The two audit JSON files differ only in run timestamps and output-directory
metadata; all other values match. Required final artifacts are under:

- `/root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-final/`
- `/root/lp-data/nhl-fullframe-event-audit-2026-10-21/derived/hardened-final-replay/`

The source manifests and raw bodies were not modified during either audit run.

The source frame SHA-256 is
`f417a1272b2bb4adff5757dae398dd1000dd2284f43b6ccb7dd28eaae99edf2b`; its game
list SHA-256 is
`ef02d94ff0ff5e494b8cdcb7eeca2f3e466e1fac1d30682c3e25cf4065ae55a8`. The
separate [erratum](ERRATUM-2026-10-21.md) corrects the obsolete frame prefix
`336d8a8d` and the sample coordinate and shot-type coverage statements without
altering files pinned by the label-verification chain.

Raw and derived files live outside Git under
`/root/lp-data/nhl-fullframe-event-audit-2026-10-21/`. This host and workspace
share `/dev/sda3`; no separate-volume or off-host copy exists. A follow-up note
and checksum-preserving backup/restore commands are in
[STORAGE-AND-REPRODUCIBILITY.md](STORAGE-AND-REPRODUCIBILITY.md). The Git branch
contains scripts, rules, schema, erratum, and report only; it does not contain
raw bodies or large generated data.

**Simulator recommendation:** begin preliminary simulator design against the
approved event sequence and component-level schema now. Training/evaluation
data ingestion must enforce the final dispositions and exact issue ledger;
keep quarantined outcomes out of target populations, preserve accepted team
score use for games with bad shifts, and do not infer motion or possession from
shift charts. No simulator was fitted in this work.
