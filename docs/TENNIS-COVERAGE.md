# Tennis coverage: which tournaments Legendary Picks tracks

What the tennis product follows, what it deliberately ignores, and how the schedule reaches the
database. Written 2026-10-18. Updated the same day for ATP and WTA 500s and for multi-tournament
storage, once the 1000-only rule had proven too narrow for the matches we need to test models on.
Updated 2026-10-21 for ATP and WTA 250s (section 2c). Before that date the 250s were excluded by name.

**Source of truth:** `backend/espn_client/scoreboard.py`, `_is_major()`, `_ATP_MAJORS`,
`_WTA_MAJORS`. If this document and that code disagree, the code wins, then fix the document.

---

## 1. The rule

> `_is_major()` returns true if the ESPN event is a **Grand Slam, Masters/1000, Finals, a 500 singles
> event, or a 250 singles event** on the tour's list.

Anything else is filtered out before it can reach the database. Only **singles** draws pass: the
grouping slug must start with `mens` (ATP) or `womens` (WTA) and must not contain `doubles` or
`mixed`.

Why 500s: the product tracked 1000s and above, which left a 2026 weekly schedule with no ATP event for
a week at a time and too few matches to test models on. The 500s are the next tier the tours publish
as main-tour singles events, and they are best of three outside the Grand Slams. See §5.

Why 250s: they fill the weeks the 500s leave empty. ESPN publishes them on the same scoreboards, so
the rule was never the publisher. ESPN's payload carries no tier field (the `major` flag is `false` for
the 2026 500s too), so the tier comes from a published calendar, and each 250 is listed by name like
the 500s. See §2c.

## 2. What we track: ATP

| category | events |
|---|---|
| **Grand Slams** | Australian Open · French Open (Roland Garros) · Wimbledon · US Open |
| **Masters 1000** | Indian Wells (BNP Paribas Open) · Miami · Monte-Carlo · Madrid (Mutua) · Italian Open (Rome) · Canadian Open (National Bank) · Cincinnati · **Shanghai** · **Paris** (Rolex Paris Masters) |
| **ATP 500** | the 16 events in §2b, including China Open (Beijing) |
| **ATP 250** | the 29 events in §2c |
| **Finals** | Nitto ATP Finals |

## 3. What we track: WTA

| category | events |
|---|---|
| **Grand Slams** | Australian Open · French Open (Roland Garros) · Wimbledon · US Open |
| **WTA 1000** | Qatar Open (Doha) · Dubai · Indian Wells · Miami · Madrid · Italian Open (Rome) · Canadian Open · Cincinnati · China Open (Beijing) · **Wuhan** |
| **WTA 500** | the 17 events in §2b |
| **WTA 250** | the 22 events in §2c |
| **Finals** | WTA Finals |

## 4. What we do not track

- **WTA 125s, and any event neither calendar lists as a 250**: for example Turk Telekom Ankara Open,
  Eupago Porto Open, Workday Canberra International, Istanbul Open and Warsaw T-Mobile Polish Open. The
  125s are not on the 250 lists, but the lists are not a measurement of tier, so absence is not proof.
- **Jiangxi Open**: tennis-db lists a 250 in Jiujiang (2-8 November). ESPN publishes no November Jiangxi
  event in 2026 (see §2c), and Wikipedia does not list it. Not tracked until one of those changes.
- The ATP 250s and WTA 250s listed in §2c are tracked. They were excluded by name before 2026-10-21.
- **Challengers**, **ITF** and **futures**: present in the historical Sackmann data but never
  tracked live
- **Doubles and mixed doubles**: filtered at the grouping slug

The historical match tables contain far more than this (they include challengers and futures). That
is training data, not tracked competition. Do not read a tournament's presence in
`tennis_atp_matches` as evidence that we cover it.

## 5. Why the scope is what it is

The tracking rule is 250s-and-above from 2026-10-21, and 500s-and-above from 2026-10-18. Before 2026-10-18 the rule was 1000s-and-above, with one
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

Only the men's Grand Slams are best of five (`FIVE_SET_MAJORS`). Every 500 and 250 is best of three. The
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
| Almaty Open | ATP | 250 | 10-19 to 10-25 | now |
| BNP Paribas Fortis European Open (Brussels) | ATP | 250 | 10-19 to 10-25 | now |
| Grand Prix Auvergne-Rhône-Alpes (Lyon) | ATP | 250 | 10-19 to 10-25 | now |
| Japan Women's Open (Osaka; ESPN "Kinoshita Group Japan Open") | WTA | 250 | 10-19 to 10-25 | now |
| Erste Bank Open (Vienna) | ATP | 500 | 10-26 to 11-01 | ~8 days |
| Swiss Indoors Basel | ATP | 500 | 10-26 to 11-01 | ~8 days |
| Toray Pan Pacific Open | WTA | 500 | 10-26 to 11-01 | ~8 days |
| Guangzhou Open | WTA | 250 | 10-26 to 11-01 | ~8 days |
| Prudential Hong Kong Tennis Open | WTA | 250 | 11-02 to 11-08 | ~15 days |
| Chennai Open | WTA | 250 | 11-02 to 11-08 | ~15 days |
| Rolex Paris Masters | ATP | 1000 | Nov 2–8 (qualifying Oct 31–Nov 1) | ~15 days |
| WTA Finals (Indian Wells) | WTA | Finals | Nov 8–15 | ~21 days |
| Bybit Stockholm Open (calendar: BNP Paribas Nordic Open) | ATP | 250 | Nov 8–14 | ~22 days |
| Nitto ATP Finals (Turin) | ATP | Finals | Nov 15–22 | ~28 days |

**The October 19–25 gap is closed.** Until 2026-10-21 the rule excluded the three ATP 250s that week
(Almaty, Brussels, Lyon), so the ATP tour had no tracked event from October 19 to 25. They are tracked
now (section 2c). Stockholm, which is on the ATP calendar as a 250, is tracked from its November week.
The WTA tour had no gap that week: Ningbo covered October 19 to 25 and Pan Pacific covers October 26
to November 1.

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

## 2c. The 250s, 2026

Added 2026-10-21. **Tiers:** the ATP's 2026 calendar (atptour.com) for the ATP, with 29 named 250s. For the
WTA, Wikipedia's 2026 WTA Tour and tennis-db, which agree on the 22 listed below. **Aliases:** the ESPN
shortName on the 2026 season list. **Surfaces:** from the same calendars.

| event (canonical) | ESPN shortName (alias) | surface | 2026 dates |
|---|---|---|---|
| Brisbane International | Brisbane International presented by ANZ | Hard | Jan 5–11 |
| Hong Kong Tennis Open | Bank of China Hong Kong Tennis Open | Hard | Jan 5–11 |
| Adelaide International | Adelaide International | Hard | Jan 12–17 |
| ASB Classic | ASB Classic | Hard | Jan 12–17 |
| Open Occitanie | Open Occitanie | Hard | Feb 2–8 |
| Argentina Open | IEB+ Argentina Open | Clay | Feb 9–15 |
| Delray Beach Open | Delray Beach Open | Hard | Feb 16–22 |
| Chile Open | BCI Seguros Chile Open | Clay | Feb 23–Mar 1 |
| Tiriac Open | Tiriac Open presented by UniCredit Bank | Clay | Mar 30–Apr 5 |
| US Men's Clay Court Championship | Fayez Sarofim & Co. U.S. Men's Clay Court Championship | Clay | Mar 30–Apr 5 |
| Grand Prix Hassan II | Grand Prix Hassan II | Clay | Mar 30–Apr 5 |
| Geneva Open | Gonet Geneva Open | Clay | May 17–23 |
| Boss Open | Boss Open | Grass | Jun 8–14 |
| Libéma Open | Libéma Open | Grass | Jun 8–14 |
| Mallorca Championships | Vanda Pharmaceuticals Mallorca Championships | Grass | Jun 21–27 |
| Eastbourne Open | Lexus Eastbourne Open | Grass | Jun 22–27 |
| Nordea Open | Nordea Open | Clay | Jul 13–19 |
| Gstaad Open | EFG Swiss Open Gstaad | Clay | Jul 13–19 |
| Umag Open | Plava Laguna Croatia Open Umag | Clay | Jul 13–19 |
| Generali Open | Generali Open | Clay | Jul 20–26 |
| Estoril Open | Millennium Estoril Open | Clay | Jul 20–26 |
| Mifel Tennis Open | Mifel Tennis Open by Telcel Oppo | Hard | Jul 27–Aug 2 |
| Winston-Salem Open | Winston-Salem Open | Hard | Aug 23–29 |
| Chengdu Open | Chengdu Open | Hard | Sep 23–29 |
| Hangzhou Open | AITO Hangzhou Open | Hard | Sep 23–29 |
| Almaty Open | Almaty Open | Hard | Oct 19–25 |
| Brussels Open | BNP Paribas Fortis European Open | Hard | Oct 19–25 |
| Lyon Open | Grand Prix Auvergne-Rhône-Alpes | Hard | Oct 19–25 |
| Stockholm Open | Bybit Stockholm Open | Hard | Nov 8–14 |

**WTA 250s, 2026**

| event (canonical) | ESPN shortName (alias) | surface | 2026 dates |
|---|---|---|---|
| ASB Classic | ASB Classic | Hard | Jan 5–11 |
| Hobart International | Hobart International | Hard | Jan 12–17 |
| Ostrava Open | Ostrava Open | Hard (indoor) | Feb 1–7 |
| Transylvania Open | Transylvania Open powered by Kaufland | Hard (indoor) | Feb 1–7 |
| ATX Open | ATX Open | Hard | Feb 23–Mar 1 |
| Bogotá Open | Copa Colsanitas Colsubsidio | Clay | Mar 30–Apr 5 |
| Rouen Open | Open Capfinances Rouen Métropole | Clay (indoor) | Apr 13–19 |
| Morocco Open | Grand Prix Son Altesse Royale | Clay | May 18–23 |
| Libéma Open | Libéma Open (Rosmalen) | Grass | Jun 8–14 |
| Nottingham Open | Lexus Nottingham Open | Grass | Jun 15–21 |
| Eastbourne Open | Lexus Eastbourne Open | Grass | Jun 22–27 |
| Iași Open | Unicredit Iasi Open | Clay | Jul 13–19 |
| Athens Open | Vanda Pharmaceuticals Athens Open | Hard | Jul 13–19 |
| Hamburg Ladies Open | MSC Hamburg Ladies Open | Clay | Jul 20–26 |
| Prague Open | Livesport Prague Open | Hard | Jul 20–26 |
| Memphis Classic | The Memphis Classic | Hard | Jul 27–Aug 2 |
| São Paulo Open | SP Open | Hard | Sep 14–20 |
| Korea Open | Korea Open | Hard | Sep 21–27 |
| Japan Women's Open | Kinoshita Group Japan Open (Osaka) | Hard | Oct 19–25 |
| Guangzhou Open | Guangzhou Open | Hard | Oct 26–Nov 1 |
| Hong Kong Open | Prudential Hong Kong Tennis Open | Hard | Nov 2–8 |
| Chennai Open | Chennai Open | Hard | Nov 2–8 |

**Where the sources disagree, and what was chosen**

- **Shared ids.** Brisbane (id 970), Adelaide (611), ASB Classic (925), Libéma (415) and Eastbourne (444)
  are one ESPN event on both tours. Each tour keeps its own alias, and the canonical name is shared where the
  surface is the same. Adelaide is an ATP 250 and a WTA 500, and both are Hard.
- **Different names, same event.** Hangzhou is "Lynk & Co Hangzhou Open" on the calendar and "AITO Hangzhou
  Open" on ESPN. Stockholm is "BNP Paribas Nordic Open" and "Bybit Stockholm Open". Rosmalen is "Rosmalen
  Championships" on Wikipedia and ESPN's "Libéma Open" on the WTA list. Each pair has the same city and dates.
- **Osaka is not Tokyo.** The WTA Osaka 250 is ESPN's "Kinoshita Group Japan Open" (WTA id 345, venue Osaka).
  The ATP Tokyo 500 has the same words in its name, "Kinoshita Group Japan Open Tennis Championships", and
  is a separate ESPN event (id 5) on the ATP list.
- **Dallas stays a 500.** toomanyrackets lists it as a 250. The ATP's own calendar lists it as a 500.

**Measured, 2026-10-21.** The ESPN season list is one year-wide request per tour (`?dates=2026`). It returned
61 ATP events and 100 WTA events. The WTA list stops at start date 2026-10-04, so it is truncated at 100. A
sweep of the same endpoint for 2026-10-05 to 2026-12-31, at 10 seconds between requests, issued 35 requests
(WTA every 4 days, ATP weekly). It added 24 WTA events, all starting on or after 10-05, and no ATP event. That
makes 39 ESPN requests in total for this change, including two single-date checks. Of the 29 ATP 250s on the
calendar, all 29 are on ESPN's list. Of the 22 WTA 250s, all 22 are on it.

**Not published, or not tracked.** The one 250 that ESPN does not show is the November Jiangxi Open, which
tennis-db lists as a 250 (see section 4). This is an observation over the sampled dates, not proof that ESPN
never publishes it. ESPN's "Grand Prix Auvergne-Rhône-Alpes" also appears as a second event (id 452) with no
groupings. It yields no draws, so it adds no matches.

**Complete brackets.** Every singles competition in the 37 fetched bodies had an id, a round, a tournament id
and exactly two competitors. `tennis_draws_from_payload` raised no error on any of the bodies. A single
incomplete 250 bracket would reject the whole day's response for that tour, so this check matters.

## 9. Adding an event

To track a tournament that is not on the list:

1. Confirm its tier from a published tour calendar, not from the event name.
2. Observe its ESPN shortName on a scoreboard for a date inside its window. One year-wide request per tour
   (`?dates=YEAR`) lists the season in one call, but the WTA part stops at 100 events. For later dates, use
   a single-date request. Add the observed name as an
   alias to `_ATP_MAJORS` or `_WTA_MAJORS`, with a comment saying **why** (the same shape as the 500 entries).
3. Add the canonical name to `SURFACE_BY_MAJOR`. `test_every_tracked_major_has_a_surface` will fail until
   you do. Add to `FIVE_SET_MAJORS` only for a men's Grand Slam.
4. Add the event to the coverage test lists in `backend/test_tennis_daily_projections.py` with its
   observed name, and confirm the draw reaches `tennis_draw_snapshots`. A name match alone does not mean
   ESPN publishes a complete bracket for it.
5. Record the change in §2 or §3, in §2b for a 500, and in §2c for a 250.

## 10. Open questions

- Whether Grand Slam total-games support was ever implemented and lost, or only ever planned.
- Whether the Projections page should state the next tracked event during a gap rather than rendering
  empty. That needs an event calendar this system does not currently hold.
- Whether one incomplete draw in an ESPN response should reject only its own tournament rather than the
  whole response. Today it rejects the response, which keeps the rule simple and fails closed.
- Whether Adelaide (500 or 250) and Linz (surface) should be confirmed from the WTA's own site.
- **`ATP Finals` matches "Next Gen ATP Finals presented by PIF"** (a substring match on an alias that predates
  2026-10-21). The Next Gen event has no groupings yet, so it yields no draws. Once it does, it would be stored
  as the Finals. Excluding it is a change to an existing alias, so it is not made here.
- **The WTA 125 tier is not measured here.** Section 4 excludes events that neither 250 list names. No source
  used for §2c names the 125s, so a WTA 250 missing from both lists would be excluded without a record.
- **Jiangxi Open (November, Jiujiang).** Confirm on the WTA's own calendar. Only if it is published by ESPN
  should it be added, under an alias that cannot match the May Jiangxi event (ESPN id 423, a non-250).
