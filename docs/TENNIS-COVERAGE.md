# Tennis coverage: which tournaments Legendary Picks tracks

What the tennis product follows, what it deliberately ignores, and how the schedule reaches the
database. Written 2026-10-18. Updated the same day for ATP and WTA 500s and for multi-tournament
storage, once the 1000-only rule had proven too narrow for the matches we need to test models on.

**Source of truth:** `backend/espn_client/scoreboard.py`, `_is_major()`, `_ATP_MAJORS`,
`_WTA_MAJORS`. If this document and that code disagree, the code wins, then fix the document.

---

## 1. The rule

> `_is_major()` returns true if the ESPN event is a **Grand Slam, Masters/1000, Finals, or a 500 singles
> event**.

Anything else is filtered out before it can reach the database. Only **singles** draws pass: the
grouping slug must start with `mens` (ATP) or `womens` (WTA) and must not contain `doubles` or
`mixed`.

Why 500s: the product tracked 1000s and above, which left a 2026 weekly schedule with no ATP event for
a week at a time and too few matches to test models on. The 500s are the next tier the tours publish
as main-tour singles events, and they are best of three outside the Grand Slams. See §5.

## 2. What we track: ATP

| category | events |
|---|---|
| **Grand Slams** | Australian Open · French Open (Roland Garros) · Wimbledon · US Open |
| **Masters 1000** | Indian Wells (BNP Paribas Open) · Miami · Monte-Carlo · Madrid (Mutua) · Italian Open (Rome) · Canadian Open (National Bank) · Cincinnati · **Shanghai** · **Paris** (Rolex Paris Masters) |
| **ATP 500** | the 16 events in §2b, including China Open (Beijing) |
| **Finals** | Nitto ATP Finals |

## 3. What we track: WTA

| category | events |
|---|---|
| **Grand Slams** | Australian Open · French Open (Roland Garros) · Wimbledon · US Open |
| **WTA 1000** | Qatar Open (Doha) · Dubai · Indian Wells · Miami · Madrid · Italian Open (Rome) · Canadian Open · Cincinnati · China Open (Beijing) · **Wuhan** |
| **WTA 500** | the 17 events in §2b |
| **Finals** | WTA Finals |

## 4. What we do not track

- **ATP 250s**: all of them, including those played the same weeks as the 500s (ESPN's "BNP Paribas
  Fortis European Open", "Almaty Open", "Grand Prix Auvergne-Rhône-Alpes", and the rest)
- **WTA 250s and 125s**: all of them, including the Kinoshita Group Japan Open, Korea Open, Guangzhou
  Open, Ostrava Open, Turk Telekom Ankara Open and Eupago Porto Open
- **Challengers**, **ITF** and **futures**: present in the historical Sackmann data but never
  tracked live
- **Doubles and mixed doubles**: filtered at the grouping slug

The historical match tables contain far more than this (they include challengers and futures). That
is training data, not tracked competition. Do not read a tournament's presence in
`tennis_atp_matches` as evidence that we cover it.

## 5. Why the scope is what it is

The tracking rule is 500s-and-above. Before 2026-10-18 the rule was 1000s-and-above, with one
documented exception:

> *"ATP 500s Kalshi lists and the competition trades. ATP China Open (Beijing) is a 500, so the
> 1000-only list dropped it while WTA's China Open (a 1000) passed: added 2026-10-04."*

The 500 tier now belongs to the rule. Beijing remains on the list as a 500, not as an exception.
Any future exception should be recorded the same way, at the reason, in the code.

## 6. Two different scopes: do not confuse them

**Tracking** (§2–3) is broad. **Surface-dependent outputs** follow the same list.

The surface of a tracked event comes from its canonical major name. `major_for_event()` returns that
name, and `SURFACE_BY_MAJOR` in `backend/tennis_daily_projections.py` maps it to a surface. Every tracked
event has an entry, and `test_every_tracked_major_has_a_surface` fails if one is missing. A surface is
keyed by name, not by ESPN id, because most event ids are unknown until the event is first seen.

`SURFACE_BY_EVENT` remains as a fast path for ids already observed. It is not the coverage list.

Only the men's Grand Slams are best of five (`FIVE_SET_MAJORS`). Every 500 is best of three. The
projection path hardcodes `best_of = 3` for everything else, so a new 500 must not be added to
`FIVE_SET_MAJORS`; `test_every_added_500_has_its_surface_and_is_never_best_of_five` checks this.

> **Documentation defect, still open:** `docs/model-cards/tennis.md` states that total-games is available
> for *"Shanghai, Wuhan, and the four Grand Slams."* That text predates the surface map. Check the card
> against the code before quoting it.

## 7. How the schedule reaches the database

1. `ingest_scoreboards.py` fetches ESPN's scoreboard for a date (yesterday, today and tomorrow in the
   schedule run, and the live targets while a match is on).
2. `tennis_draws_from_payload()` keeps **complete major singles draws only**. Missing match ids,
   missing rounds, or duplicate ids invalidate the snapshot rather than publishing a partial bracket.
   One malformed draw in a response rejects the whole response for that date, as it always has.
3. **Every complete draw in the response is stored.** The ingest no longer reduces the response to one
   draw per tour. `current_tennis_draw()` remains for a consumer that shows one bracket, and it returns
   the first draw in display order.
4. `save_tennis_draws()` stores one row per tournament, keyed on `(league, tournament_id)`:
   - Every draw is validated before any row is written. A malformed draw rejects the whole response.
     Two draws with the same tournament id in one response are also rejected.
   - An empty response changes nothing.
   - **Retirement.** When the ingest passes the date it asked about, a stored tournament the publisher no
     longer lists is removed only if its own matches are all in the past and none is in progress. A
     tournament with a match still scheduled on or after that date is kept, even if the publisher omitted
     it. A suspended match counts as in progress, so its tournament is kept.

**Display order** (`order_tennis_draws`, applied by `/api/tennis/draws` within each tour). Tournaments
with a match not yet final come first, the one finishing soonest first. Finished tournaments follow,
the most recently finished first. A suspended match is not final. The old one-draw rule was the same
order with the first entry kept, so the order is unchanged for the cases it covered.

### Storage migration

`tennis_draw_snapshots` was keyed on league alone, so a second concurrent bracket for a tour could not
be stored. `init()` rebuilds the table to key on `(league, tournament_id)` the first time it runs. The
rebuild runs in one `BEGIN IMMEDIATE` transaction, checks the row count before dropping the old table,
and is a no-op once the key is right. Existing rows keep every value.

### Consequence: the stored `status` field goes stale

A stored draw is replaced when the publisher lists it again, and retired once its matches are over and
the publisher drops it. Between those points the snapshot can be **mid-match**. A `Suspended` or `open`
status in `tennis_draw_snapshots.payload` is a historical observation, not a live state.

**Always read `fetched_at` before treating any match status as current.**

## 8. The 2026 calendar

Tracked events from 2026-10-18 onward, as far as the sources cover them:

| event | tour | tier | dates | start |
|---|---|---|---|---|
| Rolex Shanghai Masters | ATP | 1000 | final 2026-10-18 | n/a |
| Dongfeng Voyah Wuhan Open | WTA | 1000 | ended 2026-10-18 | n/a |
| BNB Ningbo Open | WTA | 500 | listed 2026-10-18; window 10-19 to 10-25 | now |
| Erste Bank Open (Vienna) | ATP | 500 | 10-26 to 11-01 | ~8 days |
| Swiss Indoors Basel | ATP | 500 | 10-26 to 11-01 | ~8 days |
| Toray Pan Pacific Open | WTA | 500 | 10-26 to 11-01 | ~8 days |
| Rolex Paris Masters | ATP | 1000 | Nov 2–8 (qualifying Oct 31–Nov 1) | ~15 days |
| WTA Finals (Indian Wells) | WTA | Finals | Nov 8–15 | ~21 days |
| Nitto ATP Finals (Turin) | ATP | Finals | Nov 15–22 | ~28 days |

**The gap, after the 500s.** On the ATP tour, **October 19 to 25 has no tracked event**. The events
ESPN lists that week (the BNP Paribas Fortis European Open, Almaty Open and Grand Prix Auvergne-Rhône-Alpes)
are 250s, and the rule excludes them. Stockholm is not on the 2026 ATP 500 list, so it is excluded too.
From October 26 the ATP tour is covered again by Vienna and Basel. On the WTA tour, Ningbo covers October 19
to 25 and Pan Pacific covers October 26 to November 1, so there is no WTA gap until the Finals.

The Projections page therefore has nothing to show on the ATP tour from October 19 to 25. That is the
coverage rule working, not a broken feed.

## 2b. The 500s, 2026

Tiers come from published 2026 calendars: 16 ATP 500s from toomanyrackets.com/atp-500-tournaments, and 17
WTA 500s from tennis-db.com/wta/tournaments.md. The WTA count of 17 also appears in its 2026 calendar
announcement, as reported in a search result. Each alias is the
ESPN shortName observed on the scoreboard for that event's week, not a guess. Each event id is unknown
until seen, so none is written here.

**ATP 500 (15 added; Beijing already listed)**

| event (canonical) | ESPN shortName (alias) | surface | 2026 dates |
|---|---|---|---|
| Dallas Open | Nexo Dallas Open | Hard | Feb 9–15 |
| Rotterdam Open | ABN Amro Open | Hard | Feb 9–15 |
| Qatar ExxonMobil Open | Qatar ExxonMobil Open | Hard | Feb 16–22 |
| Rio Open | Rio Open presented by Claro | Clay | Feb 16–22 |
| Acapulco Open | Abierto Mexicano Telcel | Hard | Feb 23–28 |
| Dubai | Dubai Duty Free Tennis Championships | Hard | Feb 23–Mar 1 |
| Munich Open | BMW Open by Bitpanda | Clay | Apr 13–19 |
| Barcelona Open | Barcelona Open Banc Sabadell | Clay | Apr 13–19 |
| Hamburg Open | Bitpanda Hamburg Open | Clay | May 17–23 |
| Halle Open | Terra Wortmann Open | Grass | Jun 15–21 |
| Queen's Club | HSBC Championships | Grass | Jun 15–21 |
| Washington | Mubadala DC Open | Hard | Jul 27–Aug 2 |
| Tokyo Open | Kinoshita Group Japan Open Tennis Championships | Hard | Sep 30–Oct 6 |
| Vienna Open | Erste Bank Open | Hard | Oct 26–Nov 1 |
| Basel | Swiss Indoors Basel | Hard | Oct 26–Nov 1 |

**WTA 500 (17 added)**

| event (canonical) | ESPN shortName (alias) | surface | 2026 dates |
|---|---|---|---|
| Brisbane International | Brisbane International presented by ANZ | Hard | Jan 4–11 |
| Adelaide International | Adelaide International | Hard | Jan 12–17 |
| Abu Dhabi Open | Mubadala Abu Dhabi Open presented by Abu Dhabi Sports Council | Hard | Feb 1–7 |
| Mérida Open | Mérida Open Akron | Hard | Feb 23–Mar 1 |
| Charleston Open | Credit One Charleston Open | Clay | Mar 30–Apr 5 |
| Linz Open | Upper Austria Ladies Linz | Hard | Apr 6–12 |
| Stuttgart Open | Porsche Tennis Grand Prix | Clay | Apr 13–19 |
| Strasbourg Open | Internationaux de Strasbourg presented by Mammotion | Clay | May 17–23 |
| Queen's Club | The HSBC Championships | Grass | Jun 8–14 |
| Berlin Open | VANDA Pharmaceuticals Berlin Tennis Open | Grass | Jun 15–21 |
| Bad Homburg Open | Bad Homburg Open powered by Solarwatt | Grass | Jun 21–27 |
| Washington | Mubadala DC Open | Hard | Jul 27–Aug 2 |
| Monterrey Open | Abierto GNP Seguros | Hard | Aug 23–29 |
| Guadalajara Open | Guadalajara Open presentado por Santander | Hard | Sep 13–19 |
| Singapore Tennis Open | Singapore Tennis Open presented by BNP Paribas | Hard | Sep 21–27 |
| Ningbo Open | BNB Ningbo Open | Hard | Oct 19–25 |
| Pan Pacific Open | Toray Pan Pacific Open Tennis | Hard | Oct 26–Nov 1 |

**Where the sources disagree, and what was chosen**

- **Linz is Hard.** tennis-db lists it as Clay. The 2025 WTA match data lists the same event as Hard, and
  it is played indoors. Hard is used.
- **Adelaide is a 500.** One aggregator lists it as a 250. The 500 classification appears in tennis-db
  and the 2026 preview sources, and an official-calendar page that lists it as a 250 said the schedule
  was not yet released. Treated as a 500; confirm against the WTA site before relying on it.
- **Shared ids.** Dubai (id 25) and Washington (id 888) are one ESPN event on both tours, so one
  canonical name serves both. The ATP and WTA lists keep their own aliases.
- **Similar names on different events.** WTA Queen's is ESPN's "The HSBC Championships" (id 997), and
  ATP London is ESPN's "HSBC Championships" (id 129). They are separate events with separate ids.

## 9. Adding an event

To track a tournament that is not on the list:

1. Confirm its tier from a published tour calendar, not from the event name.
2. Observe its ESPN shortName on a scoreboard for a date inside its window. Add the observed name as an
   alias to `_ATP_MAJORS` or `_WTA_MAJORS`, with a comment saying **why** (the same shape as the 500 entries).
3. Add the canonical name to `SURFACE_BY_MAJOR`. `test_every_tracked_major_has_a_surface` will fail until
   you do. Add to `FIVE_SET_MAJORS` only for a men's Grand Slam.
4. Add the event to the coverage test lists in `backend/test_tennis_daily_projections.py` with its
   observed name, and confirm the draw reaches `tennis_draw_snapshots`. A name match alone does not mean
   ESPN publishes a complete bracket for it.
5. Record the change in §2 or §3, and in §2b for a 500.

## 10. Open questions

- Whether Grand Slam total-games support was ever implemented and lost, or only ever planned.
- Whether the Projections page should state the next tracked event during a gap rather than rendering
  empty. That needs an event calendar this system does not currently hold.
- Whether one incomplete draw in an ESPN response should reject only its own tournament rather than the
  whole response. Today it rejects the response, which keeps the rule simple and fails closed.
- Whether Adelaide (500 or 250) and Linz (surface) should be confirmed from the WTA's own site.
