# NBA dev lock preflight — 2026-10-21

## Scope and snapshot

Read-only audit of the NBA 2027 regular-season and cup schedule, previews, locks, grades, lock events, and live result observations. The schedule was read from `picks.dev.db` (`nba_schedule`, `season=2027`, `season_type IN ('REG','CUP')`, source `nba.com`); model state was read from `nba-model.dev.sqlite3`. Both databases were opened read-only. No database, unit, or model was changed.

The schedule window is **2026-10-22 02:17:00Z through 2026-10-29 02:17:00Z** (seven days; 2026-10-21 21:17 through 2026-10-28 21:17 CDT). The model database's newest live observation is timestamped 02:17:00Z. Timer state was checked with `systemctl list-timers --all --no-pager` at about 2026-10-21 21:19 CDT. The code inspected was local dev HEAD `04a421cfb2b17c2e5c64518da04ecf257f122bc6`.

## Findings

There are **54** scheduled games in the seven-day window. The model database has **75 preview rows for 25 games**, exactly 25 each for G1, G2, and G3; every previewed game has all three rows. At this snapshot:

| Classification | Games | Definition |
| --- | ---: | --- |
| `ready` | 22 | T−90 is still in the future and all three preview rows exist |
| `at_risk` | 0 | No preview rows and T−90 is within the next 24 hours |
| `already_missed` | 1 | The T−90 lock window has passed without a lock |
| `no_schedule_row` | 0 | No preview or lock game IDs are missing from the season schedule |
| `future_missing` | 31 | No previews yet; T−90 is more than 24 hours away |

`future_missing` is an additional bucket because the four requested labels do not cover games whose preview horizon has not arrived. It is expected here: `build_preview_rows` defaults to a three-day schedule horizon (`backend/nba_model_runtime.py:280-291`). The `ready` label means rows exist now; it does not guarantee they will still be fresh at T−90. Locking rejects previews older than two hours (`backend/nba_model_store.py:443-445`), so successful refreshes must continue before each lock window.

Every scheduled lock window is `[T−90,T−88)`. Starts in this schedule fall on whole or half hours; with the active once-per-minute lock timer, each window contains two nominal timer ticks, at T−90 and T−89. These are scheduled tick times, not a claim that each future service call has already run.

| Game ID | Matchup | Tip UTC | T−90 UTC | T−88 UTC | T−90 CDT | Previews | Lock ticks in window | State |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| `0022600093` | SAC@LAC | 2026-10-22 02:30 | 2026-10-22 01:00 | 2026-10-22 01:02 | Wed Oct 21 20:00 | 3/3 | 2 (past) | already_missed |
| `0022600006` | CLE@PHI | 2026-10-22 23:00 | 2026-10-22 21:30 | 2026-10-22 21:32 | Thu Oct 22 16:30 | 3/3 | 2 | ready |
| `0022600007` | DEN@OKC | 2026-10-23 01:30 | 2026-10-23 00:00 | 2026-10-23 00:02 | Thu Oct 22 19:00 | 3/3 | 2 | ready |
| `0022600008` | NY@BOS | 2026-10-23 23:00 | 2026-10-23 21:30 | 2026-10-23 21:32 | Fri Oct 23 16:30 | 3/3 | 2 | ready |
| `0022600094` | ATL@CHA | 2026-10-23 23:00 | 2026-10-23 21:30 | 2026-10-23 21:32 | Fri Oct 23 16:30 | 3/3 | 2 | ready |
| `0022600095` | DAL@IND | 2026-10-23 23:00 | 2026-10-23 21:30 | 2026-10-23 21:32 | Fri Oct 23 16:30 | 3/3 | 2 | ready |
| `0022600096` | MIN@ORL | 2026-10-23 23:00 | 2026-10-23 21:30 | 2026-10-23 21:32 | Fri Oct 23 16:30 | 3/3 | 2 | ready |
| `0022600097` | TOR@WSH | 2026-10-23 23:00 | 2026-10-23 21:30 | 2026-10-23 21:32 | Fri Oct 23 16:30 | 3/3 | 2 | ready |
| `0022600098` | DET@MIA | 2026-10-24 00:00 | 2026-10-23 22:30 | 2026-10-23 22:32 | Fri Oct 23 17:30 | 3/3 | 2 | ready |
| `0022600099` | CHI@MIL | 2026-10-24 00:00 | 2026-10-23 22:30 | 2026-10-23 22:32 | Fri Oct 23 17:30 | 3/3 | 2 | ready |
| `0022600009` | HOU@SA | 2026-10-24 01:30 | 2026-10-24 00:00 | 2026-10-24 00:02 | Fri Oct 23 19:00 | 3/3 | 2 | ready |
| `0022600100` | NO@UTAH | 2026-10-24 01:30 | 2026-10-24 00:00 | 2026-10-24 00:02 | Fri Oct 23 19:00 | 3/3 | 2 | ready |
| `0022600101` | MEM@GS | 2026-10-24 02:00 | 2026-10-24 00:30 | 2026-10-24 00:32 | Fri Oct 23 19:30 | 3/3 | 2 | ready |
| `0022600102` | LAC@LAL | 2026-10-24 02:00 | 2026-10-24 00:30 | 2026-10-24 00:32 | Fri Oct 23 19:30 | 3/3 | 2 | ready |
| `0022600103` | POR@SAC | 2026-10-24 02:00 | 2026-10-24 00:30 | 2026-10-24 00:32 | Fri Oct 23 19:30 | 3/3 | 2 | ready |
| `0022600104` | MIA@CHA | 2026-10-24 22:00 | 2026-10-24 20:30 | 2026-10-24 20:32 | Sat Oct 24 15:30 | 3/3 | 2 | ready |
| `0022600105` | BKN@CLE | 2026-10-24 23:30 | 2026-10-24 22:00 | 2026-10-24 22:02 | Sat Oct 24 17:00 | 3/3 | 2 | ready |
| `0022600106` | MIL@PHI | 2026-10-24 23:30 | 2026-10-24 22:00 | 2026-10-24 22:02 | Sat Oct 24 17:00 | 3/3 | 2 | ready |
| `0022600107` | HOU@ATL | 2026-10-25 00:00 | 2026-10-24 22:30 | 2026-10-24 22:32 | Sat Oct 24 17:30 | 3/3 | 2 | ready |
| `0022600108` | WSH@CHI | 2026-10-25 00:00 | 2026-10-24 22:30 | 2026-10-24 22:32 | Sat Oct 24 17:30 | 3/3 | 2 | ready |
| `0022600109` | SA@DAL | 2026-10-25 00:00 | 2026-10-24 22:30 | 2026-10-24 22:32 | Sat Oct 24 17:30 | 3/3 | 2 | ready |
| `0022600110` | NO@DEN | 2026-10-25 01:00 | 2026-10-24 23:30 | 2026-10-24 23:32 | Sat Oct 24 18:30 | 3/3 | 2 | ready |
| `0022600111` | GS@PHX | 2026-10-25 02:00 | 2026-10-25 00:30 | 2026-10-25 00:32 | Sat Oct 24 19:30 | 3/3 | 2 | ready |
| `0022600112` | LAL@UTAH | 2026-10-25 21:00 | 2026-10-25 19:30 | 2026-10-25 19:32 | Sun Oct 25 14:30 | 0/3 | 2 | future_missing |
| `0022600113` | IND@BKN | 2026-10-25 22:00 | 2026-10-25 20:30 | 2026-10-25 20:32 | Sun Oct 25 15:30 | 0/3 | 2 | future_missing |
| `0022600114` | ORL@NY | 2026-10-25 23:00 | 2026-10-25 21:30 | 2026-10-25 21:32 | Sun Oct 25 16:30 | 0/3 | 2 | future_missing |
| `0022600115` | TOR@MIN | 2026-10-25 23:00 | 2026-10-25 21:30 | 2026-10-25 21:32 | Sun Oct 25 16:30 | 0/3 | 2 | future_missing |
| `0022600116` | LAC@OKC | 2026-10-25 23:00 | 2026-10-25 21:30 | 2026-10-25 21:32 | Sun Oct 25 16:30 | 0/3 | 2 | future_missing |
| `0022600117` | DET@PHI | 2026-10-25 23:30 | 2026-10-25 22:00 | 2026-10-25 22:02 | Sun Oct 25 17:00 | 0/3 | 2 | future_missing |
| `0022600118` | MEM@SAC | 2026-10-26 01:00 | 2026-10-25 23:30 | 2026-10-25 23:32 | Sun Oct 25 18:30 | 0/3 | 2 | future_missing |
| `0022600119` | WSH@CHA | 2026-10-26 23:00 | 2026-10-26 21:30 | 2026-10-26 21:32 | Mon Oct 26 16:30 | 0/3 | 2 | future_missing |
| `0022600120` | MIN@CLE | 2026-10-26 23:00 | 2026-10-26 21:30 | 2026-10-26 21:32 | Mon Oct 26 16:30 | 0/3 | 2 | future_missing |
| `0022600121` | CHI@BOS | 2026-10-26 23:30 | 2026-10-26 22:00 | 2026-10-26 22:02 | Mon Oct 26 17:00 | 0/3 | 2 | future_missing |
| `0022600122` | DAL@MIA | 2026-10-26 23:30 | 2026-10-26 22:00 | 2026-10-26 22:02 | Mon Oct 26 17:00 | 0/3 | 2 | future_missing |
| `0022600123` | IND@MIL | 2026-10-27 00:00 | 2026-10-26 22:30 | 2026-10-26 22:32 | Mon Oct 26 17:30 | 0/3 | 2 | future_missing |
| `0022600124` | PHX@OKC | 2026-10-27 00:00 | 2026-10-26 22:30 | 2026-10-26 22:32 | Mon Oct 26 17:30 | 0/3 | 2 | future_missing |
| `0022600125` | ATL@HOU | 2026-10-27 00:30 | 2026-10-26 23:00 | 2026-10-26 23:02 | Mon Oct 26 18:00 | 0/3 | 2 | future_missing |
| `0022600126` | MEM@UTAH | 2026-10-27 01:00 | 2026-10-26 23:30 | 2026-10-26 23:32 | Mon Oct 26 18:30 | 0/3 | 2 | future_missing |
| `0022600127` | GS@DEN | 2026-10-27 02:00 | 2026-10-27 00:30 | 2026-10-27 00:32 | Mon Oct 26 19:30 | 0/3 | 2 | future_missing |
| `0022600128` | BKN@BOS | 2026-10-27 23:30 | 2026-10-27 22:00 | 2026-10-27 22:02 | Tue Oct 27 17:00 | 0/3 | 2 | future_missing |
| `0022600129` | DET@NY | 2026-10-28 00:00 | 2026-10-27 22:30 | 2026-10-27 22:32 | Tue Oct 27 17:30 | 0/3 | 2 | future_missing |
| `0022600130` | SAC@SA | 2026-10-28 00:00 | 2026-10-27 22:30 | 2026-10-27 22:32 | Tue Oct 27 17:30 | 0/3 | 2 | future_missing |
| `0022600131` | POR@LAL | 2026-10-28 03:00 | 2026-10-28 01:30 | 2026-10-28 01:32 | Tue Oct 27 20:30 | 0/3 | 2 | future_missing |
| `0022600132` | MIA@ATL | 2026-10-28 23:00 | 2026-10-28 21:30 | 2026-10-28 21:32 | Wed Oct 28 16:30 | 0/3 | 2 | future_missing |
| `0022600133` | WSH@CLE | 2026-10-28 23:00 | 2026-10-28 21:30 | 2026-10-28 21:32 | Wed Oct 28 16:30 | 0/3 | 2 | future_missing |
| `0022600134` | CHA@DET | 2026-10-28 23:00 | 2026-10-28 21:30 | 2026-10-28 21:32 | Wed Oct 28 16:30 | 0/3 | 2 | future_missing |
| `0022600135` | PHI@IND | 2026-10-28 23:00 | 2026-10-28 21:30 | 2026-10-28 21:32 | Wed Oct 28 16:30 | 0/3 | 2 | future_missing |
| `0022600136` | ORL@TOR | 2026-10-28 23:30 | 2026-10-28 22:00 | 2026-10-28 22:02 | Wed Oct 28 17:00 | 0/3 | 2 | future_missing |
| `0022600137` | NY@CHI | 2026-10-29 00:00 | 2026-10-28 22:30 | 2026-10-28 22:32 | Wed Oct 28 17:30 | 0/3 | 2 | future_missing |
| `0022600138` | HOU@MIL | 2026-10-29 00:00 | 2026-10-28 22:30 | 2026-10-28 22:32 | Wed Oct 28 17:30 | 0/3 | 2 | future_missing |
| `0022600139` | GS@MIN | 2026-10-29 00:00 | 2026-10-28 22:30 | 2026-10-28 22:32 | Wed Oct 28 17:30 | 0/3 | 2 | future_missing |
| `0022600140` | DEN@NO | 2026-10-29 00:00 | 2026-10-28 22:30 | 2026-10-28 22:32 | Wed Oct 28 17:30 | 0/3 | 2 | future_missing |
| `0022600141` | SA@UTAH | 2026-10-29 01:00 | 2026-10-28 23:30 | 2026-10-28 23:32 | Wed Oct 28 18:30 | 0/3 | 2 | future_missing |
| `0022600142` | OKC@DAL | 2026-10-29 01:30 | 2026-10-29 00:00 | 2026-10-29 00:02 | Wed Oct 28 19:00 | 0/3 | 2 | future_missing |

## Earliest future lock to watch

The earliest future-window game is **CLE@PHI**, game `0022600006`:

- T−90: **2026-10-22 21:30Z / Thu Oct 22 16:30 CDT**.
- T−88: 2026-10-22 21:32Z / 16:32 CDT.
- Its current three preview rows were last written at 02:07Z and will be far older than the two-hour lock freshness limit by then. A successful refresh before the lock is required.
- For this window, the relevant scheduled runs are `data` at 16:17 CDT, `preview` at 16:22 CDT, and `lock` at 16:30 and 16:31 CDT. The preview should use data refreshed at 16:17 and be committed by the lock ticks. `grade` is not needed to lock; after the game, `data` must first capture a verified final and a later `grade` run must process it.

The live timer listing confirmed these cadences and the actual recent/next activations (CDT):

| Timer | `OnCalendar` | Last | Next | Latest service result |
| --- | --- | --- | --- | --- |
| data | `*:02/15:00` | 21:17 | 21:32 | success; stored 6 results |
| preview | `*:07/15:00` | 21:07 | 21:22 | success; 23 games / 69 rows |
| grade | `*:12/15:00` | 21:12 | 21:27 | success; 0 grades, 75 previews awaiting verified finals |
| lock | `*:*:00` | 21:19 | 21:20 | success; 1 missed-window game, 0 miss events recorded |

The table is the systemd live listing, not an inferred schedule. The lock service was also seen firing once per minute. These upcoming runs support the CLE@PHI lock only if the data and preview jobs finish successfully and leave all three previews no more than two hours old.

## Preview cadence versus the two-minute lock window

Preview ticks fall at minutes `:07`, `:22`, `:37`, and `:52`; lock ticks fall every minute. For CLE@PHI, T−90 is 16:30 CDT: the surrounding preview ticks are 16:22 and 16:37, while lock ticks are 16:30 and 16:31. No preview timer tick lands inside `[16:30,16:32)`.

For the requested three-minute example, suppose T−90 is 16:25 CDT. A preview tick at 16:22 is three minutes earlier; the lock ticks are 16:25 and 16:26; T−88 is 16:27; and the next preview tick is 16:37, ten minutes after T−88. If the 16:22 preview job has committed valid rows before 16:25, the game can lock. **There is an ordering that misses:** if that job has not committed rows by 16:27 (or fails), both lock calls see no preview and the next preview tick is too late. A completed preview row within the two-hour freshness limit avoids this timing gap. Thus the cadence alone does not guarantee success when the preview job is absent, delayed, or failing.

## Missed locks, grading coverage, and identifiers

`0022600093` SAC@LAC has T−90 at 01:00Z and T−88 at 01:02Z, with no lock. Its three previews were not written until 02:07Z, after the window. The lock service reported `missed_window_games=1` on each observed tick from 02:09Z onward, but the database still had no missed-window event at 02:17Z. This is explained by `record_missed_windows`: it skips a game while `now < scheduled_start_utc` (`backend/nba_model_store.py:476-480`), and therefore records the miss only once tip time arrives. The runtime calls it from the once-per-minute lock worker (`backend/nba_model_runtime.py:389-391`). **The operational miss record is delayed until tipoff**, leaving the interval after T−88 and before tip without a persisted miss event. No fix was made.

At the snapshot, the model DB had **0 locks, 0 locked grades, and 0 preview grades**. It had six `missed_t90_window` events for `0022600005` and `0022600092` (G1/G2/G3 each), all recorded at 02:00Z at tip time. The lock grader reads only lock rows (`backend/nba_model_store.py:508-516`); the separate preview grader can grade only stored preview rows (`backend/nba_model_store.py:561-576`).

There were **13 final-confirmed live result observations across six completed games**: `0022600001` (3), `0022600002` (2), `0022600003` (2), `0022600085` (2), `0022600086` (3), and `0022600087` (1). None of those six game IDs had a preview, lock, or grade row. Their final scores were available in the live observation store, but there was no forecast row for either grader to score; those outcomes cannot contribute to model grading. The grade service's 21:12 CDT run likewise reported zero grades.

There were no duplicate `game_id`s in the 2027 REG/CUP schedule. No game IDs in preview, lock, grade, lock-event, or live-observation tables lacked a corresponding 2027 REG/CUP schedule row. Counts and observations above are a snapshot; future timer and data runs may change them.

## Action

This is a report-only finding. No implementation, timer, gate, model, or data changes were made.
