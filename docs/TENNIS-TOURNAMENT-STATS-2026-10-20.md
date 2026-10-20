# Tennis: per-match stats on tournament websites (2026-10-20)

**Status:** finding from a manual check. One ATP event site (Shanghai) shows per-match aces and double
faults. Two more sites (365scores and tennis24) showed per-match aces and double faults in one load each
(see the six-site section). Coverage and the join to ESPN game ids are not yet established.

## Why this was checked

CP4 needs settled aces and double faults for each locked match. Our pipeline has no such source:

- ESPN scoreboards carry scores, not serve stats.
- `tennis_match_stats_overrides` holds 9 hand-verified aces rows.
- Sackmann match data stops at 2026-06.

The working hypothesis was that tournament results pages show scores but not match stats. This
doc records the checks, and the one site that contradicts the hypothesis.

## Finding

**Rolex Shanghai Masters** (official ATP 1000 tournament site, "ATP Official Tournament") publishes
per-match stats.

- Results: `https://en.rolexshanghaimasters.com/en/scores/results`. The rendered day-14 view carries
  scores, and "Match Stats" links on the two finals (see coverage below).
- Stats: `https://en.rolexshanghaimasters.com/en/scores/match-stats/2026/<code>`. In the two examples
  checked, `ms` was singles and `md` was doubles.

Stats page contents, as rendered: aces, double faults, first serve, second-serve points won, break
points saved and converted, service and return games, and total points won. Tabs cover the match and
each set.

| Match | Side | Aces | Double faults | Source |
| --- | --- | --- | --- | --- |
| Singles final, `ms001` (Davidovich Fokina d. Jodar, 1-6 7-6(5) 6-4) | Davidovich Fokina (winner) | 6 | 1 | `ms001` |
| | Jodar | 12 | 2 | `ms001` |
| Doubles final, `md001` (Miedler/Oberleitner d. Cabral/Tracy, 6-3 6-4) | Miedler/Oberleitner | 4 | 1 | `md001` |
| | Cabral/Tracy | 7 | 0 | `md001` |

Column order is the page's order, with the winner listed first. I read the first value as the first
listed player.

**Coverage seen:** one rendered load of the day-14 results page (2026-10-20) contained two "Match
Stats" links in total, one each for the singles and doubles finals. Coverage across the event is
unknown. This count describes that page at that load, not the event.

## Checks that did not show stats (one load each, 2026-10-20)

- **WTA scores page** (`https://www.wtatennis.com/scores`), rendered: "Finished" labels, no scores,
  no aces or double faults.
- **WTA tournament pages** (Ningbo, `tournaments/2092/ningbo/2026`, and Wuhan, `tournaments/wuhan-open`
  with `/draws`), rendered: navigation only, no results or stats. The Wuhan event tabs are Overview,
  Scores, Draws, Player List and Past Winners.
- **Wuhan official site** (`https://www.wuhanopentennis.com/`), rendered in both languages: no stats
  section in the tournament menus.
- **WTA stats hub** (`https://www.wtatennis.com/stats` and `/stats/2026?metric=Double_Faults`): season
  totals per player (matches, aces, double faults, serve percentages). Not per match, not per event.
- **ESPN tennis summary** (`site.api.espn.com/apis/site/v2/sports/tennis/wta/summary?event=185543`):
  HTTP 400, "Error invoking GET ... leagues/wta/events/185543". One request, one event. The route is
  unproven for other events, so this is not a finding about ESPN as a whole.
- **ATP results archive** (`https://www.atptour.com/en/scores/results-archive`): direct request
  returned HTTP 403 with a Cloudflare "Attention Required" challenge on 2026-10-20. No stats could be
  read. The earlier "no stats" reading came from a summarizing fetch, not from raw HTML, and is not
  evidence.

## Method

- Pages were rendered with Playwright (Python, headless Chromium). The stats text is in the rendered
  DOM. A plain HTTP fetch has not been tested on these pages, so it may not return the same content.
- Plain WebFetch summaries were used only to locate pages. They are not evidence for any negative.
- Scripts used are in the session scratch folder, not in the repo:
  `/tmp/claude-0/-root/2a3d8f0a-c311-4a83-b428-4754d7a521de/scratchpad/shanghai_ms001.py`,
  `shanghai_match_stats.py`, `shanghai_results.py`, `wta_render_check.py`, `wuhan_stats_page.py`.

## Six further sites checked (2026-10-20)

Each site was loaded once with Playwright (headless Chromium). Match pages were loaded once each. Results
describe those loads only.

| Site | Load | Per-match aces and double faults | What was read |
| --- | --- | --- | --- |
| 365scores (`365scores.com/en-us/tennis/league/wuhan-6177`) | 200 | Yes, one match read | The match page has a Stats section with Aces, Double Faults and Break Points Won. One match (Ann Li vs Swiatek, Wuhan): left side 1 ace and 2 double faults, right side 0 aces and 1 double fault. Side order and final status not verified. |
| tennis24 (`tennis24.com/wta-singles/wuhan/...`) | 200 | Yes, behind a STATS tab | The match page's STATS tab, clicked, shows Aces and Double Faults. The captured block was labelled SET 3 and read 0 aces and 1 double fault per side. The whole-match view is not confirmed. |
| livescore.in (`livescore.in/tennis/`) | 200 | Not found | The tennis list and match pages load. No stats tab or stat values on a match page in one load. |
| tennisabstract.com (Ann Li player page) | 200 | No per-match counts seen | Career, surface and last-52 rows show ace percentages (rates). Match rows show scores only. |
| tennis-x.com | 200 | No | News and historical records (for example Karlovic's ace records). No match stats. |
| tennisstats.com (Wuhan) | 403 | Unknown | Cloudflare bot challenge on our load. Not checked further and not bypassed. |

Not yet done: coverage for 365scores and tennis24, and the ESPN id crosswalk.

## Limits

1. **One event.** Only the Shanghai 2026 finals were rendered in full. Other matches and other years
   are unchecked.
2. **Coverage unknown.** Only the two finals had a stats link on the day-14 view. The rest of the
   draw is unchecked.
3. **Parsing and scale.** Stats are HTML text. Each event site may need its own parser unless the
   event sites share one template. A second ATP event site would test that.
4. **No join to our locks.** Our locks are keyed on ESPN game ids. Matching a stats page to an ESPN
   game needs an id-based crosswalk. Names must not be the join key (AGENTS.md).

## Coverage and crosswalk (2026-10-20)

**Denominators** come from our ESPN snapshots in the copy database, counting `status = Final`. ESPN
leaves `completed` null on most final rows, so `completed` is not a usable filter.

| Event (tour, ESPN tournament id) | Finals in snapshots | Dates |
| --- | --- | --- |
| Dongfeng Voyah Wuhan Open (WTA, 381) | 74 | 2026-10-10 to 2026-10-18 |
| Rolex Shanghai Masters (ATP, 315) | 119 | 2026-10-05 to 2026-10-18 |
| China Open (WTA, 959) | 128 | 2026-09-28 to 2026-10-11 |

Some events also appear under a second tournament id of `None` (US Open, Cincinnati, National Bank Open),
so per-event counts are approximate until those ids are reconciled.

**Enumeration on provider list pages** (one load each, 2026-10-20):

- 365scores, Wuhan league page: 0 match links on the first load. After clicking Results and scrolling
  six times, 39 match links. The full list is not yet reached, and the scrolls needed are unknown.
- tennis24, Wuhan: the draw page showed 14 match links. The RESULTS tab was not found by its label.
  Enumeration is not solved.

**Crosswalk test** (three matches, exact player names and date, database lookup only):

| Provider match | ESPN game | Date | ESPN athlete ids (home, away) |
| --- | --- | --- | --- |
| 365scores, Ann Li vs Iga Swiatek (Wuhan) | 185369 | 2026-10-16 | 3380, 3730 |
| tennis24, Maja Chwalinska vs Sonay Kartal (Wuhan final) | 185375 | 2026-10-18 | 3417, 7209 |
| Shanghai, Davidovich Fokina vs Jodar (singles final) | 184947 | 2026-10-18 | 3212, 12657 |

Each match resolved to exactly one ESPN game. The provider side has names only. The numbers in the
365scores match URL (49562, 55853) and the tennis24 slugs (for example OIxOD54s) have not been
confirmed as player ids. A reviewed table from provider player id to ESPN athlete id is still needed.
Names may propose links, but the join key must be the ids.

Not yet done: enumerate every match on each provider, measure coverage per event, and build the reviewed
provider id to ESPN athlete id table.

## Next steps (not started)

- Check one more ATP event site for the same template and stats layout.
- Enumerate the full match list on each provider, then measure coverage per event.
- Build the reviewed provider id to ESPN athlete id table before any collection.
