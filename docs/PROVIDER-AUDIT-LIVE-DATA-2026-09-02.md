# Live in-event data: what is reachable, measured 2026-09-02

Scope: **live, in-progress** data for three asks — tennis point-level scoring, UFC
significant strikes, soccer possession/passes and "where the ball is". Every claim
below is a probe run from this box on 2026-09-02, not a recollection.

Supersedes the live-data parts of `PROVIDER-AUDIT-2026-08-06.md`, which evaluated
these publishers for **batch/backfill** use and never asked the live question.

## 0. The methodology error that came first

The first pass at this answered a **live** question by probing a **finished** match,
concluded "not published", and was wrong. `content.superlive.superLiveUrl` is `null`
on a finished FotMob match and **populated on a live one**. A finished-match payload
is a different instrument than a live-match payload, and the difference is not
cosmetic — it is the entire answer.

Rule for anyone re-running this: **to answer a live question, probe a live event.**
`www.fotmob.com/api/data/matches?date=YYYYMMDD` lists 37+ live matches on a normal
day; there is no excuse for testing against a finished one.

---

## 1. UFC — SOLVED. Live significant strikes are free and reachable.

### ESPN is a dead end, and now it is measured

`site.web.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard` advertises
`playByPlayAvailable: true`. It does not mean what it sounds like:

```
sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/600060735/competitions/401911592/plays?limit=500
-> count: 14
```

**14 plays for a three-round fight.** The full type vocabulary observed: `Fight Open`,
`Walkout`, `Tale of the tape`, `Staredown`, `Round Start`, `Round End`, `Fight Over`,
`Results`. Fight-flow milestones only. Zero strike events. Competitor `statistics`
is `[]`; `linescores` carries judges' scorecards (86.0 = 28+29+29), not strikes.

Do not re-probe ESPN for MMA strike data.

### UFC's own live API is the answer

Unauthenticated, no key, **not blocked from this box**:

```
d29dxerjsp82wz.cloudfront.net/api/v3/event/live/{eventId}.json
d29dxerjsp82wz.cloudfront.net/api/v3/fight/live/{fightId}.json
```

Event feed (`LiveEventDetail`) carries live-state fields:
`LiveEventId`, `LiveFightId`, `LiveRoundNumber`, `LiveRoundElapsedTime`, plus a
`FightCard` of 12 fights, each with `FightId`, `Status`, `Fighters`, `Result`,
`Referee`, `RuleSet`.

Fight feed (`LiveFightDetail`) carries `FightStats` and **`RoundStats`**. Per round,
per fighter, measured on event 1250 / fight 11980:

```json
{
  "RoundNumber": 1,
  "Knockdowns": 0,
  "TotalStrikesAttempted": 28,  "TotalStrikesLanded": 10,
  "SigStrikesAttempted": 28,    "SigStrikesLanded": 10,
  "SigStrikesAccuracy": 35.71,
  "SigHeadStrikesLanded": 6,    "SigBodyStrikesLanded": 3,
  "SigLegStrikesLanded": 1,
  "SigDistanceStrikesLanded": 10,
  "SigClinchStrikesLanded": 0,  "SigGroundStrikesLanded": 0,
  "SigDistanceHeadStrikesLanded": 6,
  "SigClinchBodyStrikesLanded": 0
}
```

Head/body/leg **cross-split** by distance/clinch/ground. This is strictly richer than
what `ingest_ufc_fight_stats/` currently scrapes from UFCStats.com, which is
`/statistics/events/completed` — completed events only, by construction
(`ufcstats_source.py:27`).

### The one thing NOT verified

Structure was read from an event with `Status: "Final"`. The `/live/` path plus
`LiveRoundNumber` / `LiveRoundElapsedTime` make the intent unambiguous, but **the
update cadence during an actual live fight has not been observed.** Confirm against
a live card before building a poller against an assumed refresh interval. Do not
record "live-verified" until someone has watched it move.

---

## 2. Soccer — the ball widget is Opta, and that matters

### What `superLiveUrl` actually is

On a live match (`ongoing: true`, Coppa Italia 83'), `content.superlive` resolves:

```
superLiveUrl:  https://pub.fotmob.com/prod/news/api/law?matchid=...&competition=...&season=...&version=v4w
showSuperLive: true
```

That URL serves an HTML page whose entire body is one embedded widget:

```html
<opta-widget sport="football" widget="live_action" live="true"
             plot_events="5" show_direction_of_play="true"
             show_event_counters="true" animation_speed="normal">
```

**That is the moving-ball-on-a-pitch surface.** It is Opta's `live_action` widget,
loaded from `secure.widget.cloud.opta.net/v3/v3.opta-widgets.js`. The `matchid` /
`competition` / `season` values are Opta UUIDs, not FotMob ids. `playerStats[id].optaId`
in the main payload independently confirms Opta is FotMob's upstream supplier.

Note what the widget is and is not: `plot_events="5"` plots the **last five events**
on a pitch with direction-of-play. It is an event plot, not continuous optical
tracking. Nobody in this price class has true ball-tracking; that is
Tracab/Second Spectrum stadium-camera data, licensed to leagues and broadcasters.

### Licensing constraint — read before building

The Opta widget library carries a hardcoded subscription id and OMO feed credentials
(`omo_username` / `omo_password`, plus a `fast_omo_*` pair). **Values deliberately not
recorded in this doc.** The feed sits behind `omo.akamai.opta.net/auth/` and
`omo/feed/byUrl`.

Pulling data through those credentials is not public-API discovery. It is using
**FotMob's paid Stats Perform subscription** under their subscription id. Consequences
if we build on it: it is their key that gets revoked, their contract that is breached,
and our ingest dies the moment either happens. This is categorically different from
the free public endpoints we already use (ESPN, FotMob `matchDetails`). Treat as
**closed** unless someone buys an Opta/Stats Perform licence.

### What IS legitimately ours, live

From FotMob's own `www.fotmob.com/api/data/matchDetails?matchId=` — the endpoint
`ingest_fotmob_soccer_logs.py` already calls, currently only for `playerStats`:

| Field | Content | Wired up? |
|---|---|---|
| `content.shotmap.shots` | per shot: **x/y pitch coords**, xG, xGOT, `blockedX/Y`, `goalCrossedY/Z`, shotType, situation, minute, playerId | NO |
| `content.momentum.main.data` | per-minute attack momentum, `{minute, value}`, 94 points | NO |
| `content.stats.Periods.All` | team **Ball possession %**, xG, passes own-half / opposition-half, long balls, crosses | NO |
| `content.attackingZones`, `content.heatmapUrl` | zone + heatmap surfaces | not inspected |
| `playerStats[].stats` | per-player accurate passes, tackles, duels, rating | partly (logs ingest) |

Team possession % is a **double** find: it also closes the gap flagged at
`backend/team_stats_contract.py:258`, where soccer-native stats (`possessionPct`,
`shotsOnTarget`, `corners`) are documented as published by ESPN but never given a
column. Two publishers now confirm the value is available; only our schema is missing.

### Player-to-player passes: NOT available free

Exhaustively checked every section of the live payload — `matchFacts.events`
(goals/cards/subs commentary only), `stats.Periods` (aggregates), `playerStats`
(per-player totals), `lineup` (no passmap key). There is no pass-event stream with
passer, receiver and start/end coordinates.

The asymmetry is structural, not an oversight: ~10-25 shots a match are cheap to
itemise, 300-600 passes are a materially larger product. Pass-event data is the same
Opta event-feed tier as the widget above.

---

## 3. Tennis — **RESOLVED same day. The US Open publishes point-by-point, free.**

> **This section's original conclusion was wrong, and the way it was wrong matters.** It
> ended at "the US Open feed is unresolved, needs a headless browser" after five guessed
> URLs returned 404. No browser was needed. The paths are *declared* by the site itself in
> `/en_US/json/gen/config_web.json`, reachable with `curl`, and the real live-scores path
> was `matches/live/scores.json` — one segment off every guess. A guessed URL that 404s is
> evidence you guessed wrong, not evidence the data is absent. Original section kept below.

### What is actually available

```
config (declares all 35 feed paths)
  https://www.usopen.org/en_US/json/gen/config_web.json
live scores + point score in the current game
  /en_US/scores/feeds/2026/matches/live/scores.json
point-by-point, full history
  /en_US/scores/feeds/2026/slamtracker/history/<matchId>C.json
also declared: draws, head2head, player stats_chart, match_insight, distance
```

No auth, no key, not blocked from this box. It is IBM SlamTracker's own data — the same
engine behind the tournament's app, which is almost certainly what Google's tennis panel
renders too. Go to the source, not the aggregator.

**Live scores feed** carries `scores.gameScore` — the live point score inside the current
game (`[null, "A"]` = advantage to team 2) — plus per-set games with tiebreaks, server,
`last_serve_speed`, seeds, and ATP player ids.

**Point-by-point** is a JSON array, one record per point, **57 fields**. Measured live on
Shelton vs Hurkacz (match 1225): 140 points at the time of reading; 1,248 points across 10
matches captured on the first full run, with 23 break points won.

| field | why it matters |
|---|---|
| `BreakPoint`, `BreakPointWon`, `BreakPointOpportunity` | the reversible moment, flagged by the publisher rather than derived |
| `P1Momentum`, `P2Momentum` | IBM's own momentum number, per point |
| `P1Score`, `P2Score` | 0/15/30/40/AD inside the game |
| `P1GamesWon/SetsWon`, `P2GamesWon/SetsWon` | the ladder above the point |
| `Ace`, `DoubleFault`, `UnforcedError`, `Winner`, `WinnerShotType` | how the point ended |
| `Speed_MPH`, `ServeWidth`, `ServeDepth`, `ReturnDepth`, `RallyCount` | how it was played |
| `P1DistanceRun`, `P2DistanceRun` | fatigue proxy, per point and cumulative |
| **`EpochTimeStart` / `EpochTimeEnd`** | **joins a point to the order-book tape by time** |
| `Sentence` | e.g. "H. Hurkacz loses the break point with a double fault" |

`EpochTimeStart` is the load-bearing field. It is what turns "price fell 15c at 18:32" into
"he was broken at 18:31", which is the entire stop-loss / take-profit decision.

**Scope limit, recorded so nobody assumes more:** these feeds are tournament-scoped. They
work for the US Open and stop when it ends. There is no equivalent for ordinary tour events.
Bovada (§3b) covers the rest at set/game/server resolution only.

Captured by `prediction-market-trading/usopen_points.py`, cron every minute.

## 3b. Bovada — the general fallback, and the reason to stop leaning on ESPN

ESPN declares `statsSource: none` for tennis, and during this session **both** its hosts
(`site.web.api`, `sports.core.api`) returned 403 under the burst limit — a budget this box
shares with the production scoreboard ingest, so every request spent probing is one the
serving path cannot make.

Bovada prices tennis in-play, so it must carry live state, and it is a separate estate:

```
live events   /services/sports/event/coupon/events/A/description/tennis?liveOnly=true...
match state   /services/sports/results/api/v1/scores/<eventId>
              REQUIRES  Accept: application/vnd.scoreboards.full+json
```

The scores endpoint refuses `Accept: application/json` with a **406 that lists the media
types it accepts** — the error is the documentation.

Measured 2026-09-02: 33 live tennis events (all US Open) plus soccer, 104 events captured in
one pass. Publishes `sportDetails.tennis.sets`, `currentPeriodScore` (games),
`previousPeriodsScore`, and **`server`** — which makes completed breaks computable.

**Does NOT publish the point score.** Break *points* are therefore invisible here; only
completed breaks. That is the line between Bovada and the US Open feed.

Captured by `prediction-market-trading/bovada_scores.py`, cron every minute.

<details>
<summary>Original §3 (superseded above — kept because the failure is the lesson)</summary>

### Tennis — ESPN declares it has nothing; one thread still open

### The publisher answers directly

`sports.core.api.espn.com/v2/sports/tennis/leagues/atp/events/189-2026`, per
competition:

```
gameSource        = {id: 0, description: "none"}
linescoreSource   = {id: 0, description: "none"}
statsSource       = {id: 0, description: "none"}
commentaryAvailable = False
liveAvailable       = False
```

ESPN is telling us it has no stats source for tennis. Corroborating probes:

- A tennis competition object carries **no plays / point reference at all** — only
  `status`, `odds`, `broadcasts` refs. Compare MMA, which does expose a plays
  collection. The tennis plays route is valid but returns `count: 0`.
- Scoreboard: 625 US Open matches; competitor `statistics` is `[]`. `linescores` is
  set-level only, e.g. `[{value: 6.0, tiebreak: 3}, {value: 3.0}]` — games per set
  plus tiebreak, no point score.
- `.../tennis/atp/summary?event=` returns 400 on every id shape tried.
- SofaScore: 403 estate-wide (re-confirmed 2026-09-01, see §4).

Set-level is the ceiling on ESPN. Points-per-game is not derivable from it.

### Open, not dead: the US Open's own feed

usopen.org responds (no block) but the scores page is a **4KB JS-rendered shell** —
curl cannot see the XHR it fires. Five guessed feed paths under
`/en_US/scores/feeds/...` all 404'd. **A failed guess is not a finding**, and this is
recorded as unresolved rather than dressed up as a negative result.

Next step is a headless browser reading the network tab while the scores page loads.
No browse binary is built on this box (`~/.claude/skills/gstack/browse/dist/browse`
absent) — building it is the blocker, not the site.

---

</details>

## 4. SofaScore — confirmed dead, do not re-probe

Re-measured 2026-09-01 after being logged as "walled" on 2026-08-25:

- Every resolving host — `api`, `www`, `widgets`, `m`, bare `sofascore.com` — returns
  403 from the **same Fastly edge** (`199.232.71.52`). `webws.` and `api2.` do not
  resolve.
- Response is `{"error": {"code": 403, "reason": "Forbidden"}}` from **Varnish**, not
  a Cloudflare challenge page. That shape means IP/ASN blocking at their edge, not a
  bot-fingerprint check.
- Referer/Origin spoofing and HTTP/1.1 downgrade change nothing.
- Wayback holds only asset/doc endpoints (`ads.txt`, `nodeinfo`, SVGs) from 2023-24 —
  no event data, and stale snapshots cannot answer a live question anyway.

Same datacenter-IP pattern as `app.atptour.com` and `live-tennis.eu`. Upgraded from
"cross-check candidate, fragile" to **blocked, confirmed dead**.

---

## 5. Verdicts

| Ask | Live? | Source | State |
|---|---|---|---|
| UFC significant strikes | **YES** | UFC `fight/live/{id}.json` `RoundStats` | reachable, free, per-round, head/body/leg × distance/clinch/ground. Cadence unverified |
| Soccer possession % | **YES** | FotMob `stats.Periods` + ESPN boxscore | published by two sources, no column in our schema |
| Soccer shot x/y | **YES** | FotMob `content.shotmap.shots` | reachable, not wired up |
| Soccer momentum | **YES** | FotMob `content.momentum.main.data` | reachable, not wired up |
| Soccer ball position | NO (as tracking) | Opta `live_action` widget | licensed; nobody publishes true tracking free |
| Soccer player-to-player passes | **NO** | — | Opta event-feed tier, paid |
| Tennis points per game | **YES** | US Open `slamtracker/history/<id>C.json` | 57 fields/point incl. break points + IBM momentum. Tournament-scoped only |
| Tennis sets/games/server (any event) | **YES** | Bovada `results/api/v1/scores/<id>` | no point score; needs the vnd.scoreboards.full+json Accept header |

## 6. What to do next, in order

1. **UFC live strikes** — highest value, zero blockers. Wire
   `fight/live/{fightId}.json` `RoundStats` alongside the existing UFCStats history
   ingest. Confirm refresh cadence against a live card before setting a poll interval.
2. **Soccer possession + shotmap** — one endpoint we already call, three fields we
   already receive and discard. Closes `team_stats_contract.py:258` at the same time.
3. **Tennis** — build the browse binary, read the US Open network tab, then decide.
   Do not spend more curl guesses on it.
4. **Do not** build on the Opta widget credentials. Do not re-probe SofaScore or ESPN
   MMA play-by-play.
