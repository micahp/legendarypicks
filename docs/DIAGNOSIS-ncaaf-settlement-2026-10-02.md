# NCAAF prop settlement diagnosis — 2026-10-02

## Conclusion

The 4,898 open props are not one ESPN outage and are not caused by missing
`props.player_id` values.

1. **2,274 Bovada props on 93 games never enter settlement.** Their
   `prop_games` rows have neither `espn_event_id` nor a final score. The runner
   therefore does not select them. Eighty-nine of those rows, carrying 2,198
   props, have a same-date NCAAF fixture twin that is already linked; four rows,
   carrying 76 props, have no linked counterpart.
2. **2,624 RotoWire-feed props on 149 linked, final games enter the generic
   team-sport settlement path.** NCAAF has market mappings but no dedicated
   settler. It calls the ESPN site boxscore and does not read the stored CFBD
   game logs. The latest retained same-event DEV run directly accounts for
   2,616 of these props and returned `settled=0`, `unmappable=0`,
   `pending=2616`, `errors=0`.
3. **Player identity is populated, but not always correct.** All 4,898 props
   join to a player with an ESPN ID. Among the linked population, 84 props over
   15 game/player pairs resolve to a player whose canonical team is not either
   team in the fixture. These are concrete same-name identity errors, not
   missing IDs.
4. **CFBD is present but disconnected from NCAAF settlement.** PROD contains
   21,134 CFBD NCAAF player-log rows over 328 completed 2026 games through
   2026-09-27. `settle_game.py` never queries them for NCAAF. However, none of
   the 260 distinct linked game/player pairs in this backlog has an exact CFBD
   row by ESPN event ID and ESPN athlete ID, so merely switching the reader to
   CFBD would not clear this population. Two pairs have a same-date CFBD row in
   a different game, independently proving bad identity; the other 258 have no
   same-date row.
5. **Historical attempt outcomes are not durable.** Only settled/void results
   are written to `prop_results`; successful `ingest_runs.detail` is null and
   the journal has rotated the relevant PROD per-game output. Exact historical
   per-prop pending/error attribution cannot be reconstructed for eight props
   on three events. This is an observability defect, called out rather than
   filled with a hypothesis.

No production data, settings, services, schedules, or shared utilities were
changed during this diagnosis.

## Scope and denominator

PROD was opened only through:

```text
file:/root/legendarypicks/backend/data/picks.db?mode=ro
```

The measured denominator was:

```sql
FROM props p
JOIN prop_games pg ON pg.id = p.game_id
LEFT JOIN prop_results pr ON pr.prop_id = p.id
WHERE pg.league = 'ncaaf'
  AND pg.start_time < datetime('now', '-6 hours')
  AND pr.prop_id IS NULL
```

It returns **4,898 props across 242 games**, from kickoff
`2026-08-29T16:00:00Z` through `2026-09-27T03:00:00Z`. There are 2,449 over
rows and 2,449 under rows.

## Counts

### Market, fixture link, and player resolution

“Attempted” below means the game satisfies the runner's selection and reaches
`settle_game`; “skipped” means the game has no final score and no publisher
event link, so it is absent from the runner's input.

| Market | Total | Event ID set / attempted | Event ID missing / skipped | `player_id` set |
|---|---:|---:|---:|---:|
| `receiving_yards` | 3,004 | 1,736 | 1,268 | 3,004 |
| `passing_yards` | 486 | 10 | 476 | 486 |
| `rushing_yards` | 422 | 214 | 208 | 422 |
| `total_touchdowns` | 370 | 370 | 0 | 370 |
| `total_passing_touchdowns` | 322 | 0 | 322 | 322 |
| `receptions` | 230 | 230 | 0 | 230 |
| `rushing_receiving_yards` | 36 | 36 | 0 | 36 |
| `kicking_points` | 18 | 18 | 0 | 18 |
| `rush_attempts` | 6 | 6 | 0 | 6 |
| `extra_points_made` | 4 | 4 | 0 | 4 |
| **Total** | **4,898** | **2,624** | **2,274** | **4,898** |

All 4,898 also join to an existing `players` row and all 4,898 joined players
have a nonempty `players.espn_id`. A populated foreign key therefore does not
certify correct identity.

### Fixture and source split

| Fixture state | Props | Games | Settlement behavior |
|---|---:|---:|---|
| `espn_event_id` set and `final_home` set | 2,624 | 149 | Selected and sent through generic ESPN boxscore grading |
| `espn_event_id` missing and `final_home` null | 2,274 | 93 | Not selected by `settle_props.py` |

All 2,274 unlinked props are `bovada`. The 2,624 linked props are:

| Source | Props |
|---|---:|
| `rotowire:sleeper` | 916 |
| `rotowire:prizepicks` | 520 |
| `rotowire:underdog` | 518 |
| `rotowire:betr` | 242 |
| `rotowire:caesars-sb` | 212 |
| `rotowire:fanduel-sb` | 200 |
| `rotowire:pick6` | 16 |
| **Total** | **2,624** |

The provider named in `props.source` publishes the line. It is not necessarily
the stored authority for the final statistic. The current NCAAF grader uses
ESPN for that final statistic even when the line came from Bovada or a
RotoWire relay.

### Attempt result evidence

| Population | Props | Settled | Unmappable | Pending | Error | Evidence |
|---|---:|---:|---:|---:|---:|---|
| Unlinked Bovada games | 2,274 | 0 | 0 | 0 | 0 | Not attempted by runner |
| Linked events present in latest completed DEV run | 2,616 | 0 | 0 | 2,616 | 0 | Direct journal output for 146 matching event IDs |
| Linked events absent from retained comparable output | 8 | 0 | not recoverable | not recoverable | not recoverable | Three event IDs; PROD did not retain per-game outcome |

The three events without retained comparable output are:

| ESPN event ID | Props | Players / market |
|---|---:|---|
| `401862773` | 2 | Cole Cabana / `total_touchdowns` |
| `401866423` | 4 | Nick Poulos and Bishop Davenport / `total_touchdowns` |
| `401858463` | 2 | Nathan McNeil / `total_touchdowns` |

All 2,624 linked props have a market and side accepted by the current mapping.
That proves their current mapping eligibility, but it does not retroactively
manufacture a lost PROD return value for the eight rows above.

The latest completed comparable DEV settlement (PID 690748) processed 150
NCAAF games and reported, in aggregate, `settled=0`, `void=0`,
`unmappable=0`, `pending=2566`, `errors=0`. Correlation by event ID, rather
than DEV's local `prop_games.id`, covers the 2,616 current PROD props above.
For example, DEV logged Oregon at USC as eight pending with no error and Texas
A&M at LSU as 14 pending with no error.

The journal example `settled=0 void=0 unmappable=958 pending=162` is not an
NCAAF result; it belongs to an NFL game. Also, in this implementation a failed
boxscore request returns all of that game's props as pending plus one game-level
error. `pending` and `errors` are therefore not mutually exclusive counters.

## What the code actually does

There is NCAAF settlement support, but no NCAAF-specific settlement module:

1. `settle_props.py` selects games having either a stored final score or a
   nonempty `espn_event_id`.
2. `settle_game.py` has specialized DB-first branches for tennis, World Cup,
   UFC, and soccer, plus an MLB Stats API branch. It has no NCAAF branch.
3. NCAAF falls through to `espn.boxscore(league, espn_event_id)`.
4. `market_mapping.py` maps NCAAF markets to ESPN boxscore groups and labels.
5. The extractor first matches the stable ESPN athlete ID. If the target stat
   is absent but another boxscore group proves that athlete appeared, NCAAF
   grades zero. If the athlete is absent from the entire boxscore, it remains
   pending rather than inventing a zero for a possible DNP.

The CFBD ingest stores published game logs in `player_game_logs`, keyed with
ESPN event IDs and ESPN athlete IDs, but its normalized vocabulary is different
from the live ESPN boxscore vocabulary. Examples are `pass_yds`, `rush_yds`,
`rec_yds`, `rec`, and `pass_td`, versus boxscore group/label pairs such as
`passing/YDS` and `receiving/REC`. No adapter translates those stored fields
for NCAAF settlement. Current CFBD ingest also does not publish every accepted
settlement field, notably the complete kicking and return-touchdown components,
so it cannot safely be treated as a universal drop-in replacement.

## Root causes with real populations

### 1. Duplicate/unlinked Bovada fixtures: 2,274 props

The runner never sees these rows because both the event link and final score
are absent. This is the first blocker, before boxscore fetch, market mapping, or
player-stat extraction.

Of the 93 unlinked games, 89 games carrying 2,198 props have a same-date linked
NCAAF row with overlapping player IDs. The ingest has made a separate Bovada
`prop_games` row instead of reusing the canonical linked fixture.

The four remaining unlinked games carry 76 props:

| PROD game ID | Fixture | Props |
|---:|---|---:|
| 5937 | South Florida at Army | 10 |
| 6797 | Syracuse at Pittsburgh | 32 |
| 8406 | Liberty at Coastal Carolina | 16 |
| 8666 | Army at Temple | 18 |

### 2. Generic ESPN-only NCAAF reader: 2,624 props

The linked population enters settlement, but the current reader only inspects
the live ESPN site boxscore. It does not consult the durable CFBD logs already
in PROD. The latest same-event DEV evidence returned every covered prop as
pending without mapping or request errors.

This dependency is an architectural gap, not proof that CFBD has an answer for
each prop. For the exact linked denominator there are 260 distinct
event/player pairs. Exact joins to `player_game_logs` by both
`game_id = espn_event_id` and `source_player_key = players.espn_id` return zero
pairs. The same result holds using canonical `player_id`.

### 3. Accumulated spine without fixture-scoped roster membership: 84 linked props

NCAAF does have roster ingestion, but not a complete roster-membership contract.
The older ESPN roster walker populated the initial spine on August 6-8, before
RotoWire NCAAF prop ingestion began on August 29. The broader two-request CFBD
roster job was committed and first completed on September 6. Its job is to
upsert `players` by the publisher's stable athlete ID; it deliberately never
deletes or deactivates rows.

As measured on PROD, `players` holds 22,853 NCAAF rows, all with ESPN IDs and
teams and 22,658 with positions. The latest recorded successful CFBD roster job
finished 2026-10-01T16:07:16Z. Those facts show a large, recently refreshed
identity spine, not a current roster map:

- `roster_snapshots` has zero NCAAF snapshots;
- `roster_memberships` has zero NCAAF memberships; and
- `published_roster` has zero NCAAF rows.

Consequently, the RotoWire resolver searches the accumulated league-wide
`players` table. On first sight of a RotoWire athlete ID it gathers same-name
candidates, and `_pick_one` immediately accepts a sole candidate before
checking the supplied team. It then stores that decision in
`player_source_ids`; later runs return the stored binding before rechecking the
team or fixture. PROD currently has 1,092 such NCAAF RotoWire bindings.

This is not only a historical pre-roster defect. Of the six wrong RotoWire
identity bindings in the linked backlog, three were first recorded before the
first successful CFBD roster run and three were first recorded afterward. A
concrete timeline is Jack Stevens: the RotoWire Washington State key was bound
at 2026-09-06T03:05:05Z to the sole then-visible Jack Stevens, a Wagner player;
the correct Washington State Jack Stevens row arrived at
2026-09-06T22:06:38Z. The durable source binding kept returning the Wagner row.
The post-roster failures prove the missing fixture/team assertion remains an
independent cause.

The archived RotoWire entities name the intended teams directly: Winston
Watkins/LSU, Chris Henry/Ohio State, Chris Johnson/Clemson, DJ Allen/UTSA, Jack
Stevens/Washington State, and Brian Williams/Auburn. Each stored binding points
to a player on another team.

Scoreboard fixture teams and the canonical player team classify the 260 linked
event/player pairs as:

| Identity relationship | Game/player pairs | Props |
|---|---:|---:|
| Player team is one of the fixture teams | 245 | 2,540 |
| Player team is neither fixture team | 15 | 84 |

The 84 wrong-team props break down as:

| Market | Props |
|---|---:|
| `receiving_yards` | 36 |
| `total_touchdowns` | 20 |
| `receptions` | 10 |
| `kicking_points` | 10 |
| `rushing_yards` | 8 |

Examples include Winston Watkins (`TOW`) attached to LSU fixtures, Chris Henry
(`CCU`) attached to Ohio State fixtures, Chris Johnson (`SDSU`) attached to
Clemson fixtures, and Jack Stevens (`WAG`) attached to Washington State
fixtures. The populated ESPN ID makes the generic extractor consistently look
for the wrong human in the correct game. Sacramento State's Jamar Curtis was
excluded from this corrected count: `SAC` is the scoreboard's Sacramento State
code, so that row is a valid identity, not a team mismatch.

The remaining 2,540 linked props are on players whose team belongs to the
fixture, but there is no exact CFBD event/player row. That is evidence of no
published CFBD stat-line appearance, not sufficient evidence by itself to call
every player a DNP or to grade every missing statistic as zero.

### 4. Latent market alias defect: 322 props

All 322 `total_passing_touchdowns` props are currently in the unlinked Bovada
population, so fixture selection blocks them first. If linked without another
change, they would become unmappable: the NCAAF market map accepts
`passing_touchdowns`, while these rows use `total_passing_touchdowns` and no
alias connects the two.

The other 1,952 unlinked props are on currently mappable markets.

### 5. Attempt audit and runner completion are insufficient

`prop_results` records terminal settled/void output only. Pending,
unmappable, and request-error outcomes are aggregate console lines, not durable
per-prop attempt records. Successful `ingest_runs` rows do not retain those
details. Once the journal rotates, an exact historical classification is lost.

The combined ingest service also has many stale `running` settlement ledger
rows because long DEV-plus-PROD work can reach the service's hard timeout. This
makes retries irregular, but it is secondary: completed PROD settlement runs
after these games still produced no NCAAF result rows.

## Three end-to-end traces

### Prop 914399 — never attempted, then latent unmappable market

- Prop: `total_passing_touchdowns`, over 1.5, Bovada
- Player: Byrum Brown, `player_id=33484`, team `AUB`, ESPN athlete
  `4880272`
- Fixture: PROD game 2574, Baylor at Auburn, 2026-09-05
- Fixture link: `espn_event_id=''`; both stored finals are null

`settle_props.py` does not select game 2574, so settlement did not fetch or
grade this prop. Calling `settle_game` directly would return pending with “no
durable publisher event link.” After fixture linking, the current market map
would still return unmappable because `total_passing_touchdowns` lacks an alias
to `passing_touchdowns`.

### Prop 1099086 — attempted with the wrong same-name identity

- Prop: `receiving_yards`, over 56.5, `rotowire:underdog`
- Stored player: Winston Watkins, `player_id=54343`, team `TOW`, ESPN athlete
  `5226917`
- Fixture: PROD game 8944, Texas A&M at LSU, ESPN event `401856702`, final
  6-35

The market maps to the NCAAF receiving-yard field. Settlement asks the event
boxscore for ESPN athlete `5226917`, but that stable ID is a Towson player and
neither fixture team is Towson. The latest same-event DEV run processed 14
props and returned all 14 pending, with zero unmappable and zero errors.

CFBD independently proves the mismatch: athlete `5226917` has no log in event
`401856702`, but has a same-date log in event `401858244`, William & Mary at
Duke. This prop remains pending because the identity points to a different
human/game, not because `player_id` is null.

### Prop 1099258 — attempted; no published player appearance found

- Prop: `receiving_yards`, over 31.5, `rotowire:underdog`
- Player: Corey Simms, `player_id=35806`, team `USC`, ESPN athlete `5148664`
- Fixture: PROD game 8933, Oregon at USC, ESPN event `401858469`, final 41-27

USC is a fixture team and the market maps. The latest same-event DEV run
processed eight props and returned all eight pending with zero unmappable and
zero errors. The generic extractor did not find a numeric receiving-yard value
or another boxscore group proving this stable athlete appeared, so its
fail-closed behavior left the prop pending. There is also no exact or same-date
CFBD row for athlete `5148664`. The available published evidence supports
“no stat-line appearance found”; it does not justify silently grading zero.

## Proposed fix — not applied

The repair should be staged and rehearsed against `picks.dev.db` or a disposable
clone, not applied directly to PROD.

1. **Canonicalize fixtures before inserting props.** Match Bovada fixtures to
   a canonical game by normalized teams and published kickoff, reject
   ambiguity, and reuse the linked `prop_games.id`. Plan a backfill for the 89
   measured twins and explicitly resolve the four unmatched fixtures.
2. **Add a DB-first NCAAF settlement adapter.** For an exact event ID and stable
   athlete ID, read the durable CFBD row first and translate its published keys
   to settlement markets. Use it only for fields CFBD actually publishes. Keep
   a bounded ESPN fallback for unsupported/missing fields; do not invent values
   from absence.
3. **Complete and prove field coverage.** If CFBD is to grade rush attempts,
   kicking, or all components of total touchdowns, ingest those published
   fields explicitly and reconcile them before enabling those markets. Do not
   claim the current CFBD schema covers them.
4. **Enforce fixture-aware identity.** Resolve RotoWire/Bovada athletes by a
   provider-native crosswalk where available. Before publishing a prop, require
   the canonical player's team to be one of the fixture teams; queue ambiguous
   or wrong-team matches instead of accepting a unique name match. Repair the
   15 measured wrong event/player pairs only after source verification.
5. **Implement source-specific DNP handling.** A missing player row must remain
   pending until published participation evidence or the originating book's
   void/DNP rule permits a terminal result. Grade zero only when another
   published field proves the same stable athlete participated.
6. **Add the market alias**
   `total_passing_touchdowns -> passing_touchdowns`, with a regression test.
7. **Persist settlement attempts.** Store game/prop, timestamp, source,
   terminal category, pending reason, unmappable market, and request error so a
   production diagnosis does not depend on journal retention. Keep error and
   pending semantics explicit rather than overlapping silently.
8. **Bound the production settlement pass.** Reorder or split the normal
   application work so PROD settlement finishes inside its existing parent
   budget. This proposal does not require changing systemd units or timers.

The practical recovery order is fixture links, identity repairs, market alias,
then a DEV replay through the DB-first adapter with a source-specific DNP audit.
Only the resulting measured terminal rows should be considered for a later,
separately authorized PROD apply.

## ESPN request note

The diagnosis used stored databases and retained journals for the measured
population. A planned three-event live ESPN spot check was stopped after the
first request returned HTTP 403; no second or third request was sent. That 403
describes the host response at that moment and is not used as the explanation
for the historical backlog. The retained same-event DEV run had zero request
errors for the 2,616 directly correlated props.
