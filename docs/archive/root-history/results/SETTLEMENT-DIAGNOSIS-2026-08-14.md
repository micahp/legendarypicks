# UFC and MLS prop settlement diagnosis — 2026-08-14

This report records the observed failure before any settlement code was changed. All
production queries used SQLite URI `mode=ro` plus `PRAGMA query_only=ON`. The production
database was never opened writable. ESPN requests used
`LP_ESPN_CACHE_DIR=/tmp/lp-ufc-settlement-espn-cache` and an explicit per-host budget.

## UFC: exact production failure

The walked fight was production `prop_games.id=376`:

| field | value |
|---|---|
| date / start | `2026-07-25` / `2026-07-25T17:20:00+00:00` |
| home / away | `Steve Erceg` / `Ramazan Temirov` |
| stored `espn_event_id` | `401874315` |
| final columns | `final_home=NULL`, `final_away=NULL` |
| unsettled props | 6 |

The six joined prop/player rows are:

| prop ids | player row | player payload | markets |
|---|---|---|---|
| 205922–205924 | 30050 | `Steve Erceg`, team=`Ramazan Temirov`, ESPN id=`4997217` | `win_by_ko`, `win_by_submission`, `win_by_decision`; each over 0.5 |
| 205925–205927 | 30051 | `Ramazan Temirov`, team=`Steve Erceg`, ESPN id=`4895691` | `win_by_ko`, `win_by_submission`, `win_by_decision`; each over 0.5 |

`settle_props.py:23-35` selects this row because it has a non-empty ESPN id and six
props with no `prop_results`. `settle_props.py:74` calls `settle_game(con, 376)`.
`settlement.py:666-673` reads the values above. Because `final_home` is null, execution
reaches exactly `settlement.py:717`:

```text
result = espn.game_result("ufc", "401874315")
```

That calls the site summary URL with `event=401874315`. The real response was HTTP 404.
The exception is caught at `settlement.py:741-743`, producing:

```text
{"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
 "error_msg": "game 376: ESPN pull failed: HTTP Error 404: Not Found"}
```

This is the first stopping point. `401874315` is a fight competition id, despite being
stored in a column named `espn_event_id`. The real `2026-07-25` MMA scoreboard pairs it
with parent card event `600059667`. MMA summary also returned HTTP 404 for that parent
card id, so substituting the parent id would not make the generic summary/boxscore path
work.

## UFC: independent defects after the first stop

This is several incompatible contracts, not one missing map entry.

1. **Finality/id shape.** The site scoreboard's raw competition object for fight
   `401874315` reports:

   ```text
   status.type = {completed: true, state: "post", description: "Final"}
   status.period = 1
   status.clock = 261.0
   status.displayClock = "4:21"
   competitors = [
     {id: "4895691", order: 2, winner: true,  athlete.displayName: "Ramazan Temirov"},
     {id: "4997217", order: 1, winner: false, athlete.displayName: "Steve Erceg"}
   ]
   ```

   The fight has `order`, athlete competitors, and no `homeAway`, team object, or score.
   Generic `game_result()` expects team competitors with `homeAway` and scores. UFC must
   locate the fight inside the card scoreboard and gate on the fight competition's own
   `status.type.completed` field.

2. **No MMA summary boxscore.** Both MMA summary requests returned 404. The raw
   scoreboard competitor objects have `statistics=[]`; there is no generic
   `boxscore.players` surface for this fight. Therefore the call at
   `settlement.py:768` and the team/category extractor at `settlement.py:136` are not
   UFC actuals sources.

3. **No UFC entries in `MARKET_STAT`.** Every production market reaches
   `resolve_market()` as unmapped if execution gets to `settlement.py:794`.
   Production has 122 UFC props: 70 `win_by_decision`, 26 `win_by_ko`, and 26
   `win_by_submission`. The generic unmappable branch at lines 795-800 would insert a
   null result rather than grade them.

4. **The player join itself is not the production blocker.** All 122 UFC props join
   through `props.player_id -> players.id`; 117 have an ESPN athlete id. For the walked
   fight the join is 6/6 and both athlete ids match the publisher. The player `team`
   values are opponent names, so the generic team-group matcher would still be the
   wrong UFC identity contract even though the relational join succeeds.

## UFC actuals source and market decision

The intended durable actuals source already exists in `player_game_logs`. Production
has 119 UFC log rows covering 99 fights. For the walked fight it has one row per fighter,
keyed by fight id and ESPN athlete id:

| fighter | published log values |
|---|---|
| Ramazan Temirov | `result="W"`, `method="KO/TKO"`, `sigStrikesLanded=27`, `fight_time=4.35`, `fight_time_seconds=261.0` |
| Steve Erceg | `result="L"`, `method="KO/TKO"`, `sigStrikesLanded=11`, `fight_time=4.35`, `fight_time_seconds=261.0` |

Those rows were persisted by the UFC ingest from the publisher's per-fight status and
statistics objects. Across the 114 production UFC props whose games are linked, 89
currently join to such a durable fighter/fight log. A missing log is an ingestion/data
availability gap and must remain retryable; it is not evidence that the fighter recorded
zero.

The evidence-backed settlement split is:

| market strings | decision | published field / rule |
|---|---|---|
| `significant_strikes` | settleable when a matching log exists | numeric `sigStrikesLanded` |
| `fight_time` | settleable when a matching log exists | numeric `fight_time` in minutes |
| `win_by_decision` | settleable when a matching log exists | 1 only for publisher `result="W"` and `method="DEC"`; otherwise 0 |
| `win_by_ko`, `knockouts` | settleable when a matching log exists | the repository records both as win-by-method props; 1 only for `W` + `KO/TKO` |
| `win_by_submission`, `submissions` | settleable when a matching log exists | the repository records both as win-by-method props; 1 only for `W` + `SUB` |
| `finishes` | **not settled by this change** | the source label alone does not define whether DQ or other stoppages count; choosing a method set would invent a grading rule |

The worktree's 272 UFC props comprise 92 `win_by_decision`, 62
`significant_strikes`, 38 `finishes`, 28 `fight_time`, 26 `submissions`, and 26
`knockouts`. Thus 234 have a defined actual contract once their game and durable log are
available; 38 `finishes` remain explicitly unsupported pending a recorded source rule.

## MLS: real event 761469

MLS has a related but different source-shape defect. The worktree's game 692 has 68
props (goals and assists) but was not linked in this older database copy; the measured
publisher event is `761469`, New England Revolution 0–2 Houston Dynamo FC, completed
full time.

`summary.boxscore` is non-empty but contains only `{"teams": [...]}`. It has no
`players`, so adding a guessed category/key pair to `MARKET_STAT` would still make
`_find_player_stat()` return no value. The same summary directly publishes the player
actuals under `summary.rosters[].roster[]`:

```text
athlete.id / athlete.displayName
stats[] = [
  {name: "goalAssists", abbreviation: "A", value: 0.0, ...},
  {name: "totalGoals", abbreviation: "G", value: 0.0, ...},
  ...
]
```

There are two roster groups and 40 unique athlete ids. Game 692 has 68 prop rows for
41 distinct players. Only 23 of those 41 players match the roster by stored ESPN id;
18 do not. Four of the 18 have a non-null but non-matching ESPN id (`Sam Vines
260912`, `Ilay Feingold 343191`, `Leonardo Campana 284834`, and `Luca Langoni
338883`), so the id-first branch correctly refuses to fall back to a name. Of the 14
players with no ESPN id, exact normalized-name fallback recovers 10. The final result
is 57 settleable prop rows and 11 absent/id-drift rows belonging to eight distinct
players.

Absence from this roster is **not** a positive DNP signal. It can be a partial roster
or stale identity, as the four non-matching ids demonstrate. The original MLS change
incorrectly turned all 11 absent rows into permanent null-result voids. They now stay
pending with no `prop_results` row. The non-zero published facts include:

| athlete | `totalGoals` | `goalAssists` |
|---|---:|---:|
| Guilherme Augusto | 1 | 0 |
| Agustín Resch | 1 | 0 |
| Jack McGlynn | 0 | 1 |

Both MLS markets are therefore settleable without inventing keys: `goals` maps to the
publisher's `totalGoals`, and `assists` maps to `goalAssists`, read from the soccer
roster surface rather than generic boxscore players.

## Why World Cup is not the path to reuse

There is no WC special settlement path. WC falls through the generic loop with no
`MARKET_STAT` rows, reaches `settlement.py:795-800`, and inserts a `prop_results` row
whose `actual_value` and `hit` are both null for every unmapped prop. In the worktree
database all 1,128 WC props have result rows, but all 1,128 have null actuals and null
hits. Production has the same pattern for its 392 WC result rows. That is false settled
coverage, not successful grading, and it is not a pattern to copy into MLS or UFC.

## Terminal-result contract and the legacy generic/MLB paths

The same pending-instead-of-placeholder treatment applies to the generic path and to
every MLB failure state. There is no reason for an inability to grade to create a
`prop_results` row: row existence is the driver's terminal-state marker, so writing a
row necessarily prevents a later retry.

The corrected contract is:

| observed state | write | counter |
|---|---|---|
| numeric actual, including a push whose `hit` is null | numeric `prop_results` row | `settled` |
| unsupported market or invalid side | no row | `unmappable` |
| missing local identity, absent athlete/stat group, incomplete or malformed published value | no row | `pending` |
| explicit publisher DNP/void | no current write; no path measured here publishes that positive signal | `pending` |

The generic ESPN reader returns the same `None` for athlete absence, ambiguous
identity, category absence, label absence, and empty values. It cannot prove DNP.
The MLB box score likewise publishes player/stat dictionaries but no positive DNP
field used by this code; absence is not sufficient evidence. All former null inserts
for those states have therefore been removed. The MLS roster-absence insert was
removed for the same reason. New inability-to-grade cases remain eligible under
`settle_props.py` on every later run.

The current four-column schema cannot safely encode a distinct terminal void. Using
`hit=-1` was considered and rejected: `routers/props.py`, `routers/analytics.py`,
`regrade_props.py`, and `core_stories.py` select every non-null `hit` as a graded
attempt, while `routers/game_extras.py` converts it through `bool(hit)`. A negative
sentinel would silently become a loss in some places and a win in another. A fake
numeric `actual_value` would contaminate averages and margins. The correct future
shape is an explicit result-status column (for example `graded`, `push`, `void`) plus
an audited reader migration. That schema work is outside this task's authorized files;
until it exists, no path writes a terminal void without both a positive publisher
signal and an unambiguous representation.

`settle_props.py` still counts a result row as terminal, which is correct for all new
rows because the corrected writers create only numeric outcomes. Its summary no longer
calls raw row count "props graded"; it prints numeric outcomes separately from null
outcome rows so legacy placeholders remain visible.

### Existing ambiguous rows and the would-delete plan

Read-only measurement on 2026-08-14 found:

| database / league | all result rows | numeric actual | `actual_value IS NULL AND hit IS NULL` |
|---|---:|---:|---:|
| canonical dev / MLB, after the real settlement run | 756,334 | 651,184 | 105,150 |
| canonical dev / MLS, after the real settlement run | 57 | 57 | 0 |
| canonical dev / WC | 1,128 | 0 | 1,128 |
| production / MLB | 700,549 | 421,145 | 279,404 |
| production / WC | 392 | 0 | 392 |

All 106,278 dev candidates and all 279,796 production candidates have a non-null
`settled_at`. Neither database has an orphan `prop_results` row or an
`actual_value=NULL, hit!=NULL` row. Both currently have zero pushes, but the predicate
below is structurally safe for future legitimate pushes: a push has
`actual_value IS NOT NULL AND hit IS NULL`, so it cannot satisfy
`actual_value IS NULL`. Numeric wins and losses likewise have a non-null actual and
cannot match.

There is one limit no SQL predicate can overcome: the old failure and true-void
encodings are byte-identical. No query can prove which historical null-both rows were
genuine voids. If retaining an intended historical void is a requirement, there is no
safe bulk delete. The plan below instead adopts the corrected contract: without a
positive DNP signal and distinct status, every old null-both terminal row is an invalid
placeholder and should become retryable. Current mapping inspection can classify likely
causes, but cannot prove the historical branch:
dev MLB includes 23,076 currently unmapped `total_pitcher_walks` rows, 4,335 rows whose
player currently lacks MLBAM identity, 5,672 incomplete compound rows, and 72,067 other
mapped-market nulls; production has 18,868, 3,414, 5,468, and 251,654 respectively.
Every WC null is currently unmapped.

I would delete **only** the known MLB/WC ambiguous rows, after approval, with this
predicate (not run during this task):

```sql
DELETE FROM prop_results
 WHERE actual_value IS NULL
   AND hit IS NULL
   AND prop_id IN (
       SELECT p.id
         FROM props p
         JOIN prop_games g ON g.id = p.game_id
        WHERE LOWER(g.league) IN ('mlb', 'wc')
   );
```

The preflight count query is the delete predicate expressed without mutation:

```sql
SELECT LOWER(g.league) AS league, COUNT(*) AS rows_to_delete
  FROM prop_results r
  JOIN props p ON p.id = r.prop_id
  JOIN prop_games g ON g.id = p.game_id
 WHERE r.actual_value IS NULL
   AND r.hit IS NULL
   AND LOWER(g.league) IN ('mlb', 'wc')
 GROUP BY LOWER(g.league)
 ORDER BY LOWER(g.league);
```

It must return exactly `mlb=105150, wc=1128` on dev and
`mlb=279404, wc=392` on production immediately before execution. After attaching the
immutable pre-delete backup as `before`, both of these must return zero:

```sql
SELECT COUNT(*) AS numeric_rows_missing_after
  FROM (
      SELECT prop_id, actual_value, hit, settled_at
        FROM before.prop_results WHERE actual_value IS NOT NULL
      EXCEPT
      SELECT prop_id, actual_value, hit, settled_at
        FROM main.prop_results WHERE actual_value IS NOT NULL
  );

SELECT COUNT(*) AS numeric_rows_added_or_changed
  FROM (
      SELECT prop_id, actual_value, hit, settled_at
        FROM main.prop_results WHERE actual_value IS NOT NULL
      EXCEPT
      SELECT prop_id, actual_value, hit, settled_at
        FROM before.prop_results WHERE actual_value IS NOT NULL
  );
```

That deliberately deletes possible genuine historical voids too: the legacy encoding
makes them unknowable, and leaving them would preserve permanent false terminal state.
They become retryable, not graded as anything. I would verify it as follows:

1. Quiesce settlement writes and make a SQLite `.backup`; run `PRAGMA quick_check` on
   the backup. Rehearse the delete on a second disposable copy first, never on
   production.
2. Capture candidate counts by league plus the numeric-result fingerprints. The exact
   expected deletes are dev MLB `105150`, dev WC `1128` (total `106278`), production
   MLB `279404`, and production WC `392` (total `279796`). Current numeric fingerprints
   are dev `count=651241, sum(prop_id)=257091309541, min=485, max=768858` and
   production `count=421145, sum(prop_id)=166897803522, min=485, max=757010`.
3. In one `BEGIN IMMEDIATE` transaction, assert the candidate count is still exactly
   106,278 on dev or 279,796 on production, execute the predicate, and assert
   `changes()` equals that same count before committing. A changed precondition aborts.
4. Verify `PRAGMA quick_check='ok'`, zero remaining MLB/WC null-both rows, unchanged
   numeric fingerprints, and an empty two-way `EXCEPT` diff of
   `(prop_id, actual_value, hit, settled_at)` for every pre/post row with a non-null
   actual. That tuple-level comparison is the proof that no real outcome or push moved.
5. Run `settle_props.py --dry-run` to prove affected games re-enter the queue, then a
   bounded league/date settlement. Verify that numeric outcomes increase, unsupported
   and unavailable rows remain absent/retryable, and zero new null-both rows appear.

No row was deleted from either database during this work.

## UFC linker: card enumeration versus fight identity

The live publisher shape confirms two linker defects. UFC 330 contains 12 fight
competitions under the card dated `2026-08-15`; `espn_client.games('ufc',
'2026-08-16')` returns zero. The existing neighbor-day fetch does eventually see the
August 15 card, but ESPN gives several competitions one card-segment time (`21:30`,
`23:00`, or `01:00`) while the prop feed gives rolling bout estimates. The generic
linker treated the mismatched instant as decisive and rejected valid fighter pairs.
UFC's home/away slots are also not stable between publishers: the real Cody
Gibson/Abdul Hussein fight is reversed between the two payloads.

The UFC-specific matcher now treats the fighter pair as unordered, folds accents,
accepts a conservative seven-character bookmaker truncation and first/last match, and
ignores card-segment time. Both fighter names are preferred. A one-name match is used
only when it identifies exactly one fight on the slate and the other prop name matches
no published fighter; every ambiguity returns no link.

The production database was opened `mode=ro` with `query_only=ON`. Against cached live
cards, the matcher reproduced all 33 stored production fight ids exactly with zero
mismatches. It proposes 34/35 production links because the duplicate Eduardo Henrique
/ Charles Johnson row can now share the published fight id; Wellington Turman / Islam
Dulatov is absent from ESPN's card and remains unlinked. A no-write dev dry run linked
47/48, with that same matchup as the sole refusal. The test fixture records all 33
production oracle rows and the corresponding live ESPN names/times. No
`_MLB_TEAM_MAP` or `_MLS_TEAM_MAP` entry was changed.

### The seven errors in the canonical-dev settlement run, and the fix

The real run reported `Settled=8893, Void=0, Unmappable=206, Pending=614,
Errors=7`. All seven errors are the already-measured UFC card-date shape, not a new
MLS, generic, or MLB failure. They are games `801`, `880`, `881`, `882`, `883`, `885`,
and `954`; each game is dated `2026-08-16`, and each returned:

```text
UFC fight <competition id> absent from 2026-08-16 scoreboard
```

ESPN publishes all seven competition ids inside the card indexed under
`2026-08-15`; the August 16 scoreboard contains zero events. The linker handled this
with neighbor-day enumeration, but `_ufc_scoreboard_competition()` queried only
`game["date"]` during settlement finality. The exception was fail-closed: it wrote no
result rows, so all 14 affected props remained retryable. This was the same known UFC
publisher shape, not evidence of an MLS regression or a new source payload.

Commit `bd09b57` removes the inconsistency. The date window now lives once as
`espn_client.neighbor_dates()` and both the linker and settlement use it in the same
order: stored date, previous day, next day. A regression starts with an August 16 prop
game whose competition exists only in the August 15 payload and proves that the full
settlement path reaches grading with zero errors. A cached live replay resolved all
seven real competition ids through that path; no new network request was issued. They
currently publish `completed=false`, so the corrected behavior before the card is
"not final" with no write; after the card the same lookup can reach their final status
and durable logs.

## Implemented and verified

The diagnosis was committed alone as `0e2c2aa` before either runtime fix.

The UFC slice (`aa6be88`) now:

- finds the stored fight competition id inside the date's site scoreboard and gates on
  that fight's own `status.type.completed` value;
- does not invent team scores for fighter competitions;
- reads supported actuals from the unique `player_game_logs` row selected by ESPN
  athlete id first, or `player_id` only when the player has no ESPN id;
- leaves missing logs and unsupported markets without a `prop_results` row so they
  remain retryable; and
- reports those data-availability gaps as `pending` separately from DNP/void and
  unmappable counts.

An in-memory replay copied game 376, its players, props, and UFC logs through the
production `mode=ro` connection and used the cached real scoreboard. It graded all six
props with zero errors: Temirov `win_by_ko=1`; Temirov submission/decision and all three
Erceg method props `=0`. Production itself was not written.

The MLS slice (`4cf77b0`) now reads the measured roster-stat surface instead of adding
an ineffective generic boxscore map. It uses ESPN athlete id first and unique,
accent-folded exact name matching only for players without an ESPN id. The follow-up
settlement contract (`02b45ef`) leaves absent roster players and missing published
stats pending rather than turning either state into a permanent null result.

An in-memory replay of all 68 worktree game-692 props, linked only in memory to the real
cached event 761469, returned:

```text
settled=57 void=0 unmappable=0 pending=11 errors=0
result_rows=57 numeric=57 null_both=0
```

It wrote only the 57 numeric actuals. The 11 absent/id-drift prop rows wrote nothing
and remain retryable. The three over-0.5 hits were Agustin Resch goal, Guilherme Augusto
goal, and Jack McGlynn assist, matching the published payload.

The UFC linker follow-up (`bd548ed`) reproduced the production oracle and the 47/48
dev dry-run result described above. The ESPN investigation used 15 cached requests to
`site.web.api.espn.com` in total; subsequent oracle checks were cache hits.

Focused settlement/finality coverage passed `18 passed`. A plain full-suite run exposed
the worktree's unrelated 164 KiB `backend/data/picks.db` stub: 14 real-data assertions
failed while 1,372 tests passed. The tests intentionally hard-code both database
filenames and provide no environment override. The authoritative rerun created a
disposable SQLite backup from a production `mode=ro` connection, verified
`PRAGMA quick_check=ok`, and overlaid only that disposable copy at the stub pathname in
a Bubblewrap mount namespace. The real production file remained outside the writable
test view; the worktree's real `picks.dev.db` remained the second database under test.
The exact full backend result was:

```text
1386 passed, 4 skipped, 6 xfailed in 64.65s
```

After the retryability and linker follow-ups, the same isolation procedure overlaid
disposable backups at **both** test database paths and mounted the real production file
read-only inside the namespace. The current exact full backend result is:

```text
1405 passed, 4 skipped, 6 xfailed in 50.97s
```

Before and after that run, the real database SHA-256 values were unchanged:

```text
production picks.db  edfec59dade379d42cbd8e6bf9e360d687a26707c725f0c0b6f0188992029979
worktree picks.dev   fc9bdd131b76808204d27d80c997fb74a1c660fe5849d4ca646cb60dd0dbac26
```

Both source databases returned `PRAGMA quick_check=ok`. The disposable test copies
were removed. The user's `league_feature_matrix.py` read-side fix (`18ed3e1`) was merged
from `dev` and was not edited in this branch.

After the shared UFC neighbor-date fix, the focused linker/settlement set passed
`39 passed`. The final isolated full backend suite passed:

```text
1406 passed, 4 skipped, 6 xfailed in 46.75s
```

The production and canonical-dev database hashes were identical before and after that
run (`edfec59d...29979` and `9c85a2af...65634d`, respectively), and both returned
`PRAGMA quick_check=ok`. The full suite again used and then removed disposable copies;
no database row was changed by this final fix or its verification.
