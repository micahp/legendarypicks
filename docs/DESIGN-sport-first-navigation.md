# Sport-first navigation

**Written 2026-08-24.** Decides one question that has been re-argued every time a new
competition appears: **is the top-level entity on `/props` and `/leagues` a sport or a
competition?**

Answer: **sport at the top, competition underneath, and the competition level only exists
where we cover more than one competition in that sport.**

The relay numbers in this doc were measured on 2026-08-24 against
`backend/data/rotowire-archive/rotowire-2026-08-24.json.gz` (3,191 props, the full relay)
and the frontend source. The Draws decision was measured separately against one bounded
ESPN scoreboard response, documented in §4.

---

## 1. Why the level has to be the sport

The trigger was Leagues Cup. It has games and props, it is not MLS, and `/props` shows
league chips, so it is invisible there. The obvious fix is to add an `lcup` chip. The reason
not to is that the same question returns for Campeones Cup, CCC, Club World Cup, and every
summer tournament after them, and each time it is a nav decision rather than a data fact.

**A filter bar is a partition or it is noise.** PrizePicks reads badly because it offers
`EPL` next to `Soccer`, which are not mutually exclusive, so no combination of chips answers
"have I now seen all the soccer props". We already shipped a smaller version of the same
defect. `pages/props.tsx:36`:

```ts
export const LEAGUES: League[] = ['All', 'ufc', 'mls', 'nba', 'nfl', 'nhl', 'mlb', 'atp', 'wta']
```

`ufc` is a promotion, `mls` a league, `atp` and `wta` two tours of one sport. A visitor who
wants tennis has to know to click two chips, and nothing on screen tells them there is a
second one.

### The publisher does not partition soccer either

This is the part that settles it. RotoWire's relay carries **one** soccer bucket. The sport
key is the literal string `Soccer`, there is no competition field on the market, and the
props carry no `eventID`, so the competition is recoverable only from the club name.

On 2026-08-24 the 113 soccer props in the relay were:

```
Chelsea, Fulham                                   EPL
Bologna, Fiorentina, Lazio, Roma                  Serie A
Levante, Osasuna, Real Madrid, Real Sociedad      La Liga
Deportivo, Málaga                                 Segunda
```

**Zero MLS.** Six fixtures, none of them a competition we have a hub for. Underdog publishes
no MLS at all (`reference_underdog_no_mls`, measured 08-16). So a soccer tab whose contents
are the two buttons `MLS` and `Leagues Cup` is not merely an ugly design, it is wrong about
where our soccer props actually come from: it would show two competitions that had no props
that day and hide four that did.

### The sport grouping is published, so do not invent it

`backend/espn_client/config.py` stores the complete set of ESPN site paths, and the prefix is
the sport. (`backend/espn_leagues.py` is a narrower core-API registry containing only MLS and
NCAAF, so it cannot drive whole-product navigation.)

```
mls    soccer/usa.1
ncaaf  football/college-football
atp    tennis/atp
```

Derive `sport` from the registry path rather than hand-maintaining a slug-to-sport map, so a
new competition lands in the right bucket the moment its registry row exists. Same rule as
everywhere else: the value is published, do not re-derive it
(`published-first-skill`).

---

## 2. The rule

1. **Top level is the sport.** Stable across the calendar. It never changes because a
   tournament started or ended.
2. **A competition level appears only where we cover more than one competition in that
   sport,** and it appears as a second row inside that sport, never mixed into the first.
3. **The second row defaults to all competitions.** A filter the visitor did not set must
   never hide props.
4. **Which competitions are offered comes from the product's enablement registry, not row
   presence.** League directory cards read the vouched coverage registry
   (`docs/DATA-COVERAGE-CONTRACT.md` §4). Props filters read the Props product registry.
   Current or historical rows are inventory, not enablement: NBA remains navigable when no
   player offers are posted, and a scheduled Leagues Cup slate remains navigable before a
   provider has created any `prop_games` rows. One stray stored row also cannot silently
   launch a new competition in the UI.
5. **A sport is named for what it is, not for the one competition we happen to carry.** The
   exception is stated per sport in §3, because "we have one competition" and "this sport is
   one competition" look identical in a count and only one of them should be renamed later.

---

## 3. Per-sport decisions

| sport | top chip | competition row | note |
|---|---|---|---|
| Football | `NFL`, `NCAAF` | none | **Deliberately two top-level chips.** See below. |
| Soccer | `Soccer` | yes | MLS, Leagues Cup, and whatever the relay actually carries |
| Tennis | `Tennis` | yes | ATP, WTA |
| Basketball | `NBA` | none | |
| Baseball | `MLB` | none | |
| Hockey | `NHL` | none | |
| MMA | `UFC` | none | renamed to MMA only when a second promotion has props |
| Esports | `Esports` | yes | CS2 today, see §6 |

**Football keeps NFL and NCAAF separate at the top level.** This is a deliberate exception to
the rule, not an oversight. Nobody browsing thinks "football" and means either one, the
seasons and the rosters do not overlap, and NFL is the product's forced focus
(`project_nfl_product_direction`). Grouping them under a `Football` chip would put a chip
between a drafter and the only league that matters to them.

**UFC stays UFC.** It becomes `MMA` with a promotion row the day a second promotion is
carried, and **a promotion is only worth carrying if we can get its props**, because props
are the product. Same test for any new league in any sport. This is now a roadmap gate
rather than a per-case argument.

---

## 4. What a Tennis rollup page contains

Consolidating ATP and WTA on `/props` forces a `Tennis` entry on `/leagues`, and there is no
tennis hub today. What we actually have, from `backend/league_feature_matrix.py:61`, is
short and honest:

- **Scores.** `atp` and `wta` are in `BOARD_LEAGUES` (`backend/ingest_scoreboards.py:61`) and
  ingest per-day, because tennis returns `events: []` for the range form.
- **Props.** `_parse_tennis_props`, Bovada.
- **News.** `news_items` carries tennis rows.

And what tennis explicitly does **not** have, declared as not-applicable rather than missing:
game detail, team stats, coverage row, scoring plays, game context, **game logs, and season
stats**. That declaration is why every tennis market in `backend/core_markets.py:53` maps to
`None` for charting.

The 2026-08-25 ranking-source pass adds one more measured surface. The tennis
hub is four tabs, not the seven a team-sport league hub gets:

```
Tennis
  [ Scores ]  [ Draws ]  [ Rankings ]  [ News ]
             ATP · WTA toggle inside each tab, defaulting to both
```

- **Scores** is the existing per-day board, both tours interleaved, tour shown on the row.
- **Draws** is the current covered major's singles bracket for each tour. Measured
  2026-08-24 from ESPN's existing `site.web.api.espn.com/.../tennis/{tour}/scoreboard`
  response: a tournament event publishes `groupings[].competitions[]`; each competition
  carries `tournamentId`, a `round` id/name, competitors and future undecided slots, while
  the event carries a `rel=bracket` link. That link names a competition type and is exposed
  only when it matches the selected grouping (the shared event currently advertises its
  men's link on the WTA response too). No second publisher endpoint is needed.
  The ingest persists the whole validated grouping from the already-fetched scoreboard;
  missing ids/rounds or duplicate matches preserve the last good draw and fail the refresh.
- **Rankings** is ESPN's published current ATP/WTA world-ranking document. It is
  not `competitors[].curatedRank.current`, which is the current tournament's seed.
  The world-ranking response is capped at 150 and exposes one current week, so
  every bounded capture is retained under `(tour, captured_at, espn_athlete_id)`.
  Athlete references join directly to the canonical tennis spine; names are display
  fields and never keys. The UI shows the top 50 from the persisted top-150 snapshot.
- **News** is the existing feed filtered to tennis.

**We cover majors, not the tour.** Challengers, 250s and 500s are not ingested. The hub says
so on screen rather than looking like a tour page with holes in it
(`project_lp_honest_data_ui`: an absence is labelled, never left blank).

---

## 5. What a Soccer rollup page contains

The failure mode to design away is a Soccer destination that is two buttons and
nothing else. MLS and Leagues Cup are competition tabs inside one complete hub;
each tab immediately exposes the surfaces that competition can honestly support:

```
Soccer
  [ MLS ]  [ Leagues Cup ]

  MLS:          [ Scores ] [ Standings ] [ Leaders ] [ News ]
  Leagues Cup:  [ Bracket ] [ Scores ] [ Leaders ] [ News ]
```

- **MLS** reuses the published conference tables, DB-backed season totals, persisted
  scoreboards and MLS news already carried by the league hub.
- **Leagues Cup** persists the publisher's full-season knockout rounds and its
  published goals/assists leader tables. League-phase games never masquerade as
  bracket nodes, scheduled 0-0 scores render as dashes, and later rounds stay absent
  until the publisher names their participants.
- Both competitions show their own day board. Storage keys remain `mls` and `lcup`.
- `/leagues` links to one Soccer destination. The competition split happens inside
  that destination instead of forcing the directory to stand in for the missing page.

The Props product remains sport-first and defaults to all soccer competitions; this
page is a league-information destination, not a rewrite of Props filtering.

---

## 6. Esports props, and the toggle

**RotoWire's relay already carries esports props.** Measured in the 2026-08-24 archive:

| title | props | books quoting |
|---|---|---|
| CS2 | 205 | sleeper 158, underdog 149, prizepicks 139 |
| Valorant | 3 | prizepicks 3 |

Markets are `Map 1 Kills`, `Map 1 Headshots`, `Maps 1+2 Kills`, `Maps 1+2 Headshots`, and
`Maps 1+2+3 Kills`. No LoL, no Dota, no COD in that day's relay. We ingest none of it: the
roadmap already lists `CS2 Game 205` and `Valorant 3` among the buckets the relay hands us
and we discard.

**The catch is which CS2.** The 22 teams quoted that day were tier-2 and academy sides:
`Spirit Academy`, `CYBERSHOKE Prospects`, `ex-RUBY`, `Bushido Wildcats`, `Chinggis Warriors`.
Real props on real matches, but not the tier a visitor means by "CS2". That is the actual
argument for the visibility control, and it is worth stating plainly: **the toggle exists
because the supply is uneven, not because esports is a lesser sport.**

Design:

- Esports is a sport chip like any other, with a title row (CS2, Valorant) underneath.
- **A single account preference, default on, that removes esports from the props board.** One
  switch, in settings, not a per-title matrix and not a dismissable banner.
- Whether the default should be off is a question to answer with the tier problem measured
  over a couple of weeks, not now.

Do not build the toggle before the ingest. An option that hides an empty board is untestable.

---

## 7. Open questions, in the order they block work

1. **Resolved 2026-08-24: ESPN publishes the tennis draw in the scoreboard payload.** The
   measured fields and persistence contract are in §4; the candidate implementation uses
   that same response, not another request path.
2. **How is a competition recovered from a RotoWire soccer prop?** Club name is the only
   signal in the payload, so this is a name-to-competition mapping, which is exactly the
   shape that misses silently rather than raising
   (`feedback_ambiguous_key_never_raises`). Decide whether an unmapped club is shown as
   `Soccer` with no competition label, or withheld. **Shown, labelled honestly, is the
   default per `project_lp_honest_data_ui`.**
3. **Do the four European competitions in the relay become hubs, or stay board-only?** They
   have props and no standings ingest. Board-only is a legitimate answer and the sport-first
   shape supports it, which is the point.
4. **What does the ATP/WTA consolidation do to settlement?** Tennis props settle today under
   `atp` and `wta` league keys. The consolidation is a presentation change and must not
   rewrite storage keys, for the same reason NHL season keys were left alone.

---

## 8. What this does not change

- Storage keys. `atp`, `wta`, `mls`, `lcup` stay exactly as they are in every table. This
  document is about the top of the page.
- `/scores`, which is already sport-agnostic and lists league keys directly
  (`pages/scores.tsx:101`).
- The coverage registry, which stays the authority on what is offerable.
