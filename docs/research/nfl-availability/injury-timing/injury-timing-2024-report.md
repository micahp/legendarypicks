# 2024 regular season: injury report timing against proposed forecast cutoffs

Read-only measurement from nfl_hist_injuries and nflverse schedules. Cutoffs are the proposed rules in the brief, not verified report publication times. date_modified is an update time, not a publication time.

## Coverage
- Injury rows, 2024 REG weeks 1-18: 5954
- Unique player-weeks (latest version): 5952
- Rows with null date_modified: 0
- Rows not matched to a scheduled game: 0
- Keys with more than one stored version: 2
- Games on weekdays without a cutoff rule (unmapped): {'Friday': 32, 'Saturday': 140, 'Wednesday': 44}

## Stored versions
| week | team | player | designation | date_modified |
|---|---|---|---|---|
| 15 | NYJ | Tyler Conklin | Questionable | 2024-12-14T20:55:19+00:00 |
| 15 | NYJ | Tyler Conklin | Out | 2024-12-15T13:57:00+00:00 |
| 15 | HOU | Cade Stover | Questionable | 2024-12-15T03:34:33+00:00 |
| 15 | HOU | Cade Stover | Out | 2024-12-15T14:17:06+00:00 |

## Share of latest versions by class, per horizon (mapped games only)
| horizon | timestamp-proxy | post-cutoff | unverifiable | verified point-in-time |
|---|---|---|---|---|
| early | 0 (0.0%) | 5736 (100.0%) | 0 (0.0%) | 0 (no archived snapshots) |
| practice | 290 (5.1%) | 5446 (94.9%) | 0 (0.0%) | 0 (no archived snapshots) |
| final | 5659 (98.7%) | 77 (1.3%) | 0 (0.0%) | 0 (no archived snapshots) |
| pregame | 5735 (100.0%) | 1 (0.0%) | 0 (0.0%) | 0 (no archived snapshots) |

## Modified after kickoff
- Latest versions modified after kickoff: 1 of 5736 (0.0%)

## By weekday, share modified after each cutoff
| weekday | n | early | practice | final | pregame | after kickoff |
|---|---|---|---|---|---|---|
| Monday | 454 | 100.0% | 96.5% | 1.1% | 0.0% | 0.0% |
| Sunday | 4910 | 100.0% | 94.6% | 1.4% | 0.0% | 0.0% |
| Thursday | 372 | 100.0% | 97.0% | 0.3% | 0.3% | 0.3% |

## By designation, share modified after the final cutoff and after kickoff
| designation | n | after final cutoff | after kickoff |
|---|---|---|---|
| Doubtful | 188 | 2.7% | 0.0% |
| NULL | 3096 | 0.5% | 0.0% |
| Note | 6 | 33.3% | 0.0% |
| Out | 1044 | 1.7% | 0.1% |
| Questionable | 1402 | 2.7% | 0.0% |

## By week, share modified after the final cutoff
| week | n | after final cutoff |
|---|---|---|
| 1 | 195 | 3.1% |
| 2 | 256 | 0.4% |
| 3 | 298 | 0.3% |
| 4 | 329 | 1.5% |
| 5 | 330 | 1.8% |
| 6 | 334 | 0.3% |
| 7 | 365 | 0.8% |
| 8 | 371 | 0.8% |
| 9 | 379 | 0.3% |
| 10 | 355 | 7.3% |
| 11 | 319 | 1.9% |
| 12 | 268 | 0.4% |
| 13 | 328 | 0.0% |
| 14 | 304 | 1.0% |
| 15 | 377 | 2.1% |
| 16 | 336 | 0.3% |
| 17 | 258 | 0.0% |
| 18 | 334 | 1.5% |

## Rows modified after kickoff
| week | team | player | designation | date_modified | kickoff (UTC) |
|---|---|---|---|---|---|
| 1 | BAL | Kyle Van Noy | Out | 2024-09-06 03:11:40+00:00 | 2024-09-06 00:20:00+00:00 |

## Engram, 2024 week 2 (regression case)
- No row found for Engram in week 2 with this key.

## Verdict for the rule
- No verified point-in-time inputs exist in this table for 2024. Every class above is timestamp-proxy, post-cutoff or unverifiable.
- Designation rates in the rate report use the latest version and are retrospective. The table above shows how many of them could have changed after the final cutoff.
- Prospective timestamped snapshots are needed for verified multi-horizon evaluation.
