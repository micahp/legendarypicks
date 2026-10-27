# 2024 point-in-time injury audit

Read-only. Horizons and cutoffs are the proposed rules in the brief, not verified report publication times. date_modified is an update time, not a publication time. No availability probability is fitted, and no model is promoted.

## Coverage
- nfl_hist_injuries 2024 rows, all game types: 6215
- Rows with no matching schedule game: 0
- Latest rows analysed: 6213 (regular season 5952, playoffs 261)
- Player-weeks with more than one stored version: 2 (all Week 15 Conklin and Stover)
- Rows with null date_modified: 0
- Official inactive identities with no injury row on the exact key (missing input): REG 1889, playoffs 131

## Verified point-in-time inputs
Zero. No archived or dated snapshot exists for 2024 in the database. Every class below is a timestamp-proxy, retrospective or unverifiable.

## Regular season, mapped weekdays (Sunday, Thursday, Monday): n = 5736
| horizon | timestamp-proxy | retrospective | unverifiable | verified |
|---|---|---|---|---|
| early | 0 (0.0%) | 5736 (100.0%) | 0 | 0 |
| practice | 290 (5.1%) | 5446 (94.9%) | 0 | 0 |
| final | 5659 (98.7%) | 77 (1.3%) | 0 | 0 |
| pregame | 5735 (100.0%) | 1 (0.0%) | 0 | 0 |

## By designation, regular season (mapped)
| designation | n | early retrospective | practice retrospective | final retrospective | pregame retrospective | after kickoff |
|---|---|---|---|---|---|---|
| Doubtful | 188 | 100.0% | 100.0% | 2.7% | 0.0% | 0.0% |
| NULL | 3096 | 100.0% | 91.8% | 0.5% | 0.0% | 0.0% |
| Note | 6 | 100.0% | 100.0% | 33.3% | 0.0% | 0.0% |
| Out | 1044 | 100.0% | 98.6% | 1.7% | 0.1% | 0.1% |
| Questionable | 1402 | 100.0% | 98.6% | 2.7% | 0.0% | 0.0% |

## By game day, regular season (mapped)
| weekday | n | early retrospective | practice retrospective | final retrospective | pregame retrospective | after kickoff |
|---|---|---|---|---|---|---|
| Monday | 454 | 100.0% | 96.5% | 1.1% | 0.0% | 0.0% |
| Sunday | 4910 | 100.0% | 94.6% | 1.4% | 0.0% | 0.0% |
| Thursday | 372 | 100.0% | 97.0% | 0.3% | 0.3% | 0.3% |

## Playoffs: n = 261, all unmapped for horizon cutoffs (no published cutoff rule verified)
- Latest versions modified after kickoff: 0 of 261

## Explicit cases
### Engram, 2024 week 2 (JAX, GSIS 00-0033881)
- No injury row exists for this player-week in nfl_hist_injuries. The designation at every horizon is unverifiable, and the table cannot show the warm-up change described for this case.

### Engram, 2024 week 3 (JAX, GSIS 00-0033881)
- stored version: Out, date_modified 2024-09-21 17:02:51+00:00, kickoff 2024-09-23 23:30:00+00:00
- early: cutoff 2024-09-19 16:00:00+00:00, class of latest version retrospective
- practice: cutoff 2024-09-21 13:00:00+00:00, class of latest version retrospective
- final: cutoff 2024-09-22 13:00:00+00:00, class of latest version timestamp-proxy
- pregame: cutoff 2024-09-23 22:00:00+00:00, class of latest version timestamp-proxy

### Cade Stover, 2024 week 15 (HOU, GSIS 00-0039359)
- stored version: Questionable, date_modified 2024-12-15 03:34:33+00:00, kickoff 2024-12-15 18:00:00+00:00
- stored version: Out, date_modified 2024-12-15 14:17:06+00:00, kickoff 2024-12-15 18:00:00+00:00
- early: cutoff 2024-12-11 17:00:00+00:00, class of latest version retrospective
- practice: cutoff 2024-12-13 14:00:00+00:00, class of latest version retrospective
- final: cutoff 2024-12-14 14:00:00+00:00, class of latest version retrospective
- pregame: cutoff 2024-12-15 16:30:00+00:00, class of latest version timestamp-proxy

### Tyler Conklin, 2024 week 15 (NYJ, GSIS 00-0034270)
- stored version: Questionable, date_modified 2024-12-14 20:55:19+00:00, kickoff 2024-12-15 18:00:00+00:00
- stored version: Out, date_modified 2024-12-15 13:57:00+00:00, kickoff 2024-12-15 18:00:00+00:00
- early: cutoff 2024-12-11 17:00:00+00:00, class of latest version retrospective
- practice: cutoff 2024-12-13 14:00:00+00:00, class of latest version retrospective
- final: cutoff 2024-12-14 14:00:00+00:00, class of latest version retrospective
- pregame: cutoff 2024-12-15 16:30:00+00:00, class of latest version timestamp-proxy

### Kyle Van Noy, 2024 week 1 (BAL, GSIS 00-0031360)
- stored version: Out, date_modified 2024-09-06 03:11:40+00:00, kickoff 2024-09-06 00:20:00+00:00
- early: cutoff 2024-09-02 16:00:00+00:00, class of latest version retrospective
- practice: cutoff 2024-09-04 13:00:00+00:00, class of latest version retrospective
- final: cutoff 2024-09-05 13:00:00+00:00, class of latest version retrospective
- pregame: cutoff 2024-09-05 22:50:00+00:00, class of latest version retrospective

## Method notes
- A retrospective class means the latest stored version was modified after the cutoff. Whatever the report said at the cutoff is not stored, so the forecast input cannot be reconstructed.
- Post-cutoff revisions are excluded from forecast inputs but kept in evaluation. Nothing here removes player-games.
