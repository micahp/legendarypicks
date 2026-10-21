# NHL event-data coverage: detailed field and target audit

This report supersedes any rounded headline in the initial `REPORT-EVENTS.md`. It uses the same
deterministic 300-game, five-season sample and the exact source bodies, but adds field-level
completeness, event-time shift checks, and comparisons against the approved label-quality reader.

Research feasibility only. No model fitting, market/ROI analysis, production changes, or full-frame
event download was performed. The pinned 4,876-game frame is unchanged; 2022 is a partial season
from 2022-10-11 through 2022-11-27 (343 games in the official frame), sampled at 60 games like each other season.

## Population, sample, and source integrity

The sample is 300 games, 60 per start season, drawn without replacement with seed `20261021` from the 4876-game official frame. The sample is not the 4,872-game SBR market subset, the 4,763-game goalie-preregistration complete-case subset, or its 3,509-game out-of-fold evaluation population.

All 600 expected event bodies (300 PBP and 300 shift charts) passed manifest, game-ID, row-count, compressed-byte/hash, and decompressed-byte/hash checks. The approved 84,283,212-byte research-label artifact was hash-verified before reading; only `VERIFIED`/`ADJUDICATED` observations with `eligible_grading=true` were used as label targets. Joins use canonical game IDs and numeric NHL player IDs.

## Shot-event field completeness

Denominator is every GameCenter shot event in the sample, including blocked shots, missed shots, goals, and shootout shot events. Direct shooter ID and goal-scorer attribution are reported separately; a credited scorer is used for the SOG credit on a goal event, not represented as a raw `shootingPlayerId`.

| Field | Present / total | Missing | Coverage | Interpretation |
|---|---:|---:|---:|---|
| `shooter_id_direct` | 32,675/34,508 | 1,833 | 94.688% | Published `shootingPlayerId` field is present and numeric. |
| `shot_player_id_attributed` | 34,508/34,508 | 0 | 100.000% | Direct shooter ID, or credited goal scorer for goal events. |
| `location_xy` | 34,506/34,508 | 2 | 99.994% | Both finite coordinates are present. |
| `shot_type` | 26,037/34,508 | 8,471 | 75.452% | Published nonempty `shotType` is present. |
| `period` | 34,508/34,508 | 0 | 100.000% | Valid period number and period type are present. |
| `game_clock` | 34,508/34,508 | 0 | 100.000% | Valid `MM:SS` game clock is present. |
| `period_and_clock` | 34,508/34,508 | 0 | 100.000% | Both period and game clock are valid. |
| `situation_code` | 34,508/34,508 | 0 | 100.000% | Published situation code parses as four-position strength state. |

The direct `shootingPlayerId` field is absent on 1,833 goal events; all 1,833 have a credited numeric `scoringPlayerId`, which supplies the SOG player attribution for that goal. This is recorded as a separate fallback role, not as if the raw shooter field were present.

Shot type split: unblocked 26,037/26,039; blocked 0/8,469. The unblocked feed is missing 2 shot types; blocked-shot rows do not carry a shot type in this sample. No shot type is inferred.

| Season | Games | Shot events | Games missing a tracked field | Direct shooter ID | Credited player ID | x/y | Shot type | Period + clock |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 60 | 7,066 | 60 | 95.018% | 100.000% | 99.986% | 74.370% | 100.000% |
| 2019 | 60 | 6,784 | 60 | 94.649% | 100.000% | 99.985% | 76.430% | 100.000% |
| 2020 | 60 | 6,738 | 60 | 94.672% | 100.000% | 100.000% | 76.417% | 100.000% |
| 2021 | 60 | 6,826 | 60 | 94.316% | 100.000% | 100.000% | 75.769% | 100.000% |
| 2022 | 60 | 7,094 | 60 | 94.770% | 100.000% | 100.000% | 74.373% | 100.000% |

## Outcome and event reconciliation

| Approved target/stat | Eligible labels in sample | Event match | Mismatch |
|---|---:|---:|---:|
| `SOG` | 10,797 | 10,795 | 2 |
| `SAVES` | 646 | 644 | 2 |
| `SHOTS_AGAINST` | 646 | 644 | 2 |
| `GOALS_AGAINST` | 646 | 646 | 0 |

PBP team goals reconcile against official final scores in 300/300 games after excluding shootout goal events and crediting the shootout winner with the official +1. Team SOG reconcile in 298/300 games; the remaining team-side conflicts are retained, not corrected.

For 18,891 non-shootout on-target events, 0 lack a usable credited SOG player ID and 109 lack `goalieInNetId`. Of the latter, 108 agree with a no-goalie situation code; 1 remains unexplained. Empty-net goals are not assigned to a goalie. Goalies with zero TOI remain `NOT_APPLICABLE`; zero-TOI backups eligible as goalie targets: 0.

The label comparison used accepted values only when the approved reader returned an eligible grading label. Quarantined and not-applicable labels remain present in the per-player CSVs and are not compared as targets. PBP-to-label mismatches identify event reconstruction conflicts; they do not invalidate the approved official label itself.

The approved full-frame label artifact has 6 quarantined goalie statistic labels from two appearances. None falls in this 300-game sample; the 554 `NOT_APPLICABLE` rows per goalie statistic in the sample are zero-TOI/nonappearance goalie slots and are excluded.

### Unresolved event-vs-label cases

| Game | Statistic | Player ID | Official accepted | PBP event aggregate |
|---|---|---:|---:|---:|
| `2019020372` | `SOG` | 8470612 | 2 | 3 |
| `2021020345` | `SOG` | 8480806 | 2 | 3 |
| `2019020372` | `SAVES` | 8471306 | 20 | 21 |
| `2019020372` | `SHOTS_AGAINST` | 8471306 | 23 | 24 |
| `2021020345` | `SAVES` | 8471734 | 32 | 33 |
| `2021020345` | `SHOTS_AGAINST` | 8471734 | 36 | 37 |

The two SOG player conflicts are on the same two games as the two team-side PBP SOG conflicts. In each, the PBP aggregate is one above the approved official player/team value; the opposing goalie PBP saves and shots-against are also one above their approved values. The evidence localizes each discrepancy to a PBP-vs-official shot-count disagreement, but does not establish which source is wrong or authorize correcting either source. Original approved values are retained.

## Strength states and event-time shift alignment

| Event/player check | Tested | Match/on ice | Boundary ambiguous | Mismatch/off ice |
|---|---:|---:|---:|---:|
| Shooter at shot event | 34,363 | 31,504 | 2,858 | 1 |
| Goalie in net at on-target event | 18,782 | 18,661 | 85 | 36 |
| Situation-code skater/goalie counts vs active shifts | 33,500 | 33,204 | 863 | 296 |

Boundary cases are within one second of a shift start/end and are not forced to match or mismatch. Situation checks deduplicate active player IDs, decode the four-digit goalie/skater counts, and exclude shootout periods. The sample contains these non-shootout state classes:

| Situation | Events | Games |
|---|---:|---:|
| `EN_away_pulled` | 1,201 | 166 |
| `EN_home_pulled` | 1,155 | 172 |
| `EV_3v3` | 852 | 69 |
| `EV_4v4` | 1,287 | 154 |
| `EV_5v5` | 75,114 | 300 |
| `PP_away_4v3` | 72 | 17 |
| `PP_away_5v3` | 133 | 31 |
| `PP_away_5v4` | 6,045 | 295 |
| `PP_home_4v3` | 104 | 23 |
| `PP_home_5v3` | 172 | 40 |
| `PP_home_5v4` | 6,621 | 298 |
| `both_pulled` | 33 | 33 |

The feed distinguishes 5v5, 4v4, 3v3, and empty-net counts directly. `PP_away_*` and `PP_home_*` identify the advantaged team and both teams' skater counts; the opposing side's penalty-kill state is the complement. This supports event-time 5v5/PP/PK/empty-net reconstruction, subject to the shift comparison mismatches and boundary cases above.

Shift charts record more than one goalie for 45 sampled games (47 team-game goalie substitution instances). Event-time goalie IDs are mostly represented by the charts, but off-ice checks and the published shift-TOI conflicts below mean shifts should not be treated as perfectly authoritative event lineups.

## Missing, contradictory, or unusable games by season

Contradictions count distinct sampled games per issue type; the expected shootout winner-score convention is excluded. A game is marked unusable for SOG event reconstruction when PBP is absent, an on-target event lacks a credited player ID, or SOG disagrees with an eligible approved label/team total. Goalie event reconstruction is unusable for an unexplained missing goalie ID or eligible label mismatch. Shift features are unusable when charts are missing or a shift/lineup identity, TOI, duplicate, overlap, or event-time check conflicts. These flags do not exclude a game from the frozen frame or invalidate an independent approved official target.

| Season | Sampled | Missing PBP | Missing shifts | Any contradiction | SOG event reconstruction unusable | Goalie event reconstruction unusable | Shift features unusable |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 60 | 0 | 0 | 1 | 0 | 0 | 1 |
| 2019 | 60 | 0 | 0 | 14 | 1 | 2 | 13 |
| 2020 | 60 | 0 | 0 | 18 | 0 | 0 | 18 |
| 2021 | 60 | 0 | 0 | 10 | 1 | 1 | 9 |
| 2022 | 60 | 0 | 0 | 2 | 0 | 0 | 2 |

The event-field exception ledger contains 8,580 shot-event rows, each linked by `game_id` and source event ID. Tracked missing-field counts: `location_xy` 2, `shot_type` 8,471; goalie-ID status counts on on-target events: `EXPECTED_EMPTY_NET` 108, `UNEXPLAINED` 1. See `event_field_exceptions.csv` for exact event-level evidence, including the single unexplained missing goalie ID and both missing coordinate pairs.

| Exception | Game / event | Period / clock | Source detail |
|---|---|---|---|
| Goal with missing goalie ID | `2019020096` / `650` | REG 3 / 16:47 | situation `1551` has both goalie flags on; the PBP row has no `goalieInNetId` |
| Missing x/y pair | `2018020573` / `446` | REG 2 / 14:50 | `blocked-shot`; x=-19, y=null, shotType=null |
| Missing x/y pair | `2019020349` / `774` | SO 5 / 00:00 | `shot-on-goal`; x=null, y=null, shotType=null |

| Issue | Distinct games |
|---|---:|
| `DUPLICATE_SHIFT_CHART` | 2 |
| `GOALIE_LABEL_MISMATCH` | 2 |
| `GOALIE_OFF_SHIFT_AT_EVENT` | 4 |
| `GOALIE_SHIFT_TOI` | 5 |
| `SHOOTER_OFF_SHIFT_AT_EVENT` | 1 |
| `SITUATION_SHIFT_COUNT_MISMATCH` | 33 |
| `SOG_FEED_VS_OFFICIAL` | 2 |
| `SOG_PLAYER_LABEL_MISMATCH` | 2 |
| `TOI_SHIFT_VS_OFFICIAL` | 14 |

## Proposed import decision

**Recommendation: proceed with a staged, research-only full-frame import of both PBP and available shift charts as immutable raw artifacts; do not treat the normalized event set as uniformly complete or model-ready.** The sample retrieved every feed for all 300 selected games and supports the event schema in `PROPOSED-SCHEMA.md`. Full import should preserve null shot types/coordinates and issue flags, and should reject or quarantine duplicate/inconsistent shift charts at the derived layer. Verify the same coverage and label checks season by season during import, then publish a full-frame completeness report before modeling from event-derived features.

At the fetcher's 1.1-second request spacing, 9,752 source requests imply a lower-bound spacing time of 178.77 minutes before network time or retries. Linear scaling from the sample estimates 123.0 MB compressed; payload size is a sample-based estimate, not a measured full-frame total. Keep raw bodies in durable external artifact storage, with hashes and manifests in Git.

This recommendation is for event-data acquisition and coverage, not model fitting, ROI testing, deployment, or replacing the separate approved outcomes. SOG and goalie-saves baseline research against the approved labels can proceed independently while event ingestion is built.

## Reproduction

```sh
cd research/nhl/event-data-audit-2026-10-20
PY=/root/legendarypicks/backend/venv/bin/python
$PY audit_event_detail.py
$PY write_event_detail_report.py
$PY -m pytest tests -q
```
