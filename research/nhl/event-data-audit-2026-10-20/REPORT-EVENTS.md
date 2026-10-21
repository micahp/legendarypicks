# NHL event-data coverage audit

Question: **before anyone fits a simulator, how much of an NHL game can we actually
reconstruct from official event feeds, season by season, and where do the feeds
contradict the official-label foundation?**

Research only. Read-only against the label foundation and the event cache. No model
is fitted, no market is evaluated, nothing is written to the production database.

## Frame and sample

Event evidence is fetched for a deterministic stratified sample of the pinned
official-outcome frame rather than the whole frame: field availability is a property
of the source and is settled by a sample, while a full-frame fetch is a
~100-minute network job. Every rate below is reported with its per-season n and is a
statement about **the sampled games**, not about the frame.

| season | games sampled | PBP bodies | shift bodies |
|---|---:|---:|---:|
| 2018 | 60 | 60 | 60 |
| 2019 | 60 | 60 | 60 |
| 2020 | 60 | 60 | 60 |
| 2021 | 60 | 60 | 60 |
| 2022 | 60 | 60 | 60 |
| **total** | **300** | **300** | **300** |

Sample: 60 games per start season, uniform without replacement, seed 20261021, from
`official-outcome-backfill-2026-10-20/canonical_frame.csv` (4,876 regular-season
games, 2018 through 2022-11-27). Raw bodies are gzipped outside Git with per-file
SHA256 sidecars; the sample and every fetch are pinned in `sample_games.csv` and
`event_evidence_manifest.csv`.

## Can we rebuild the game? Per-dimension answer

| dimension | measured | reading |
|---|---|---|
| shots and locations | 100.0% of 34,508 shot events carry x/y | **complete** — every shot is placeable |
| shot types | 26,037 of 26,039 unblocked shot events carry `shotType`; 0 of 8,469 blocked shots do | usable — blocked shots are the only real gap |
| period scoring | 300/300 games reconcile goal-for-goal with the official score **once the shootout rule below is applied** | **complete** |
| strength states | 100.0% of 92,975 situation codes parse | **complete**, incl. empty net |
| penalties | 99.6% of 2,219 penalty events carry duration | **complete** |
| deployment / shifts | skaters: 98.8% of 10,797 within 30s of official TOI; 2 games carry a duplicated chart | **usable**, with two feed defects to guard |

Strength states observed across the sample: `EN_away_pulled`, `EN_home_pulled`, `EV_3v3`, `EV_4v4`, `EV_5v5`, `PP_away_4v3`, `PP_away_5v3`, `PP_away_5v4`, `PP_home_4v3`, `PP_home_5v3`, `PP_home_5v4`, `both_pulled`.

Shot-type vocabulary observed: `backhand`, `bat`, `between-legs`, `deflected`, `poke`, `slap`, `snap`, `tip-in`, `wrap-around`, `wrist`.

## Two feed rules that must be implemented before any simulator

**1. Shootouts are events in the feed but not in the official totals.** In the sampled games, 20 went to a shootout, contributing 48 goal events and 129 shot events. The official team SOG excludes them, and the official final score credits only the winner with +1. Counting feed goal events as the score overstates it by the shootout's conversion count; excluding shootout periods and adding one goal to the winner reconciles 300/300 sampled games exactly. A simulator must model the shootout as a separate stage or drop it, never as ordinary 5v5 events.

**2. Shift charts can be duplicated at the game level.** 2 sampled games have a median shift-summed TOI of ~2x the official value across every player — a duplicated chart, not a tolerance problem. It is detected by the ratio test in `audit_event_coverage.py` (`DUPLICATE_SHIFT_CHART`); a simulator must reject the chart rather than fit through it.

## Season-by-season detail

| season | games | SO games | shot events | x/y | shot type (unblocked) | situation parsable | goals = official | SOG = official | skater TOI within 30s | contradictions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 60 | 3 | 7,066 | 100.0% | 100.0% | 100.0% | 60/60 | 60/60 | 100.0% | 3 |
| 2019 | 60 | 5 | 6,784 | 100.0% | 100.0% | 100.0% | 60/60 | 59/60 | 99.9% | 8 |
| 2020 | 60 | 3 | 6,738 | 100.0% | 100.0% | 100.0% | 60/60 | 60/60 | 98.8% | 9 |
| 2021 | 60 | 5 | 6,826 | 100.0% | 100.0% | 100.0% | 60/60 | 59/60 | 95.4% | 18 |
| 2022 | 60 | 4 | 7,094 | 100.0% | 100.0% | 100.0% | 60/60 | 60/60 | 99.8% | 5 |

## Full-frame ID reconciliation (all 4,876 games, not sampled)

Every game in the pinned frame: player IDs carried by the imported official boxscore body
versus the IDs the label tables published for that game.

| season | games | label player-slots | only in boxscore | only in labels | games disagreeing |
|---|---:|---:|---:|---:|---:|
| 2018 | 1271 | 50,840 | 0 | 0 | 0 |
| 2019 | 1082 | 43,280 | 0 | 0 | 0 |
| 2020 | 868 | 34,700 | 0 | 0 | 0 |
| 2021 | 1312 | 52,460 | 0 | 0 | 0 |
| 2022 | 343 | 13,716 | 0 | 0 | 0 |
| **total** | **4,876** | **194,996** | **0** | **0** | **0** |

Reconciliation issues raised at frame level: **0**.

## Contradictions found (the reason to audit before fitting)

| issue | count | what it means |
|---|---:|---|
| `SHOOTOUT_GOAL_BONUS_APPLIED` | 20 | expected: the official score credits the shootout winner +1 |
| `TOI_SHIFT_VS_OFFICIAL` | 14 | in this game at least one skater's shift-summed TOI differs from official by >60s |
| `GOALIE_SHIFT_TOI` | 5 | goalie TOI from shifts disagrees with official (goalie intervals are unreliable) |
| `SOG_FEED_VS_OFFICIAL` | 2 | regulation shot count still disagrees with official team SOG (not explained by shootouts) |
| `DUPLICATE_SHIFT_CHART` | 2 | every player's shift-summed TOI is ~2x official: the chart is duplicated |

## What this establishes, and what it does not

Establishes: the official feeds carry the event structure a simulator needs —
located shots, shot types, strength states, period scoring, penalties, shift
boundaries, and rosters that join to the label foundation on NHL player ID. Period
scoring reconciles exactly against the official score on the sampled games once the
shootout rule is applied, and that reconciliation is the strongest anchor because it
is an independent path to the same number. Full-frame player IDs reconcile with zero
one-sided IDs across all 4,876 games.

Also establishes two defects that would otherwise reach a simulator silently: the
shootout convention above, and game-level duplicated shift charts. Both are now
detected by assertions rather than remembered by whoever wrote the simulator.

Does not establish: any rate on the full 4,876-game frame, any model, any prop
market result, or that the two sources agree everywhere outside the sample. The
contradiction counts are sampled counts, not frame totals.

## Reproduce

```sh
cd research/nhl/event-data-audit-2026-10-20
PY=/root/legendarypicks/backend/venv/bin/python
$PY select_sample.py                    # deterministic sample, prints its sha256
$PY fetch_event_evidence.py             # resumable, pinning, 1.1s between requests
$PY audit_event_coverage.py             # writes event_game_metrics / coverage_by_season
$PY write_report.py                     # regenerates this file from those outputs
$PY -m pytest tests -q                  # parsers + injected contradictions
```
