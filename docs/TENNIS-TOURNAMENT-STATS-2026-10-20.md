# Tennis: per-match stats on tournament websites (2026-10-20)

**Status:** finding from a manual check. One ATP event site shows per-match aces and double faults.
Coverage, terms of use and the join to ESPN game ids are not yet established.

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

## Limits

1. **One event.** Only the Shanghai 2026 finals were rendered in full. Other matches and other years
   are unchecked.
2. **Coverage unknown.** Only the two finals had a stats link on the day-14 view. The rest of the
   draw is unchecked.
3. **Terms of use unknown.** These are the stats of an ATP tournament. We have not read the site's
   terms, so automated collection is not yet cleared.
4. **Parsing and scale.** Stats are HTML text. Each event site may need its own parser unless the
   event sites share one template. A second ATP event site would test that.
5. **No join to our locks.** Our locks are keyed on ESPN game ids. Matching a stats page to an ESPN
   game needs an id-based crosswalk. Names must not be the join key (AGENTS.md).

## Next steps (not started)

- Read the site's terms of use and robots rules.
- Check one more ATP event site for the same template and stats layout.
- Measure coverage: how many matches per event have a stats page.
- Design the ESPN crosswalk on ids before any collection.
