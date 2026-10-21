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

Coverage and the ESPN crosswalk are measured for Wuhan WTA 2026 below. Shanghai and other events are not run.

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

## Backfill: Wuhan WTA 2026 (2026-10-20, copy database)

Run as approved, with the deviations listed below. Target: the copy `picks.tennis-cp4.db`, table
`provider_match_stats` (module-owned, created by `backend/ingest_provider_match_stats.py`). No ESPN request
was made: the crosswalk reads the snapshots already in the copy.

| Provider | Enumerated | Parsed ok | Failures | Stop rule fired |
| --- | --- | --- | --- | --- |
| 365scores (league page, Results list) | 62 | 62 | 0 | no |
| tennis24 (`/wta-singles/wuhan/results/`) | 79 | 79 | 0 | no |

**Crosswalk** (`backend/provider_espn_crosswalk.py`), against ESPN completed Wuhan matches in the snapshots
(74 Final and 5 Retired, 79 total):

| Measure | Result |
| --- | --- |
| 365scores matches linked to a unique ESPN game | 62 of 62 |
| tennis24 matches linked to a unique ESPN game | 75 of 79; 4 to review |
| ESPN games covered by either provider | 78 of 79 |
| ESPN games covered by both providers | 59 |
| Totals agreement on those 59 (aces and double faults, both players summed) | 59 of 59 |

The one uncovered game is McNally vs Starodubtseva (Round 1). tennis24 spells the second name
"Starodubtsewa", so it goes to review. The four tennis24 review cases have no ESPN final with both
surnames (spelling or pairing differences); they are listed by match id in the table.

**Read this with care:**
- The links are name proposals (exact surname pair within the event). They are not id-verified. Once a
  provider player id is reviewed against an ESPN athlete id, the id pair should replace names.
- Agreement is on totals only. Side-level values are not compared, so the home and away columns are
  not verified against each other across providers.
- tennis24's default stats block was read without confirming the MATCH tab was active. The 59-of-59
  totals agreement with 365scores is the evidence that it is the whole-match view.
- ESPN "Retired" matches are included in the links. They can carry partial stats, and RESULTS.md
  excludes retirements from grading.
- The 365scores list changed size between runs (57, then 62). Enumeration is not yet proven complete.

**Deviations from the approved parameters:**
1. List enumeration: the approved rule was "unchanged for three scrolls, cap 30". The final rule is
   scrolling with the End key (four presses, 2 s apart, after a mouse-wheel step), stopping after four
   unchanged rounds, capped at 40. The three-round rule stopped early (31 matches), and a 'Show More'
   click emptied the 365scores list, so no buttons are clicked.
2. The run was stopped and restarted once because available memory on the shared box fell below the
   1.5 GB floor. The resume skips matches already stored with status ok, which the module now does.
   Matches were stored before and after the pause; no match was parsed twice.
3. No retries were used. Pacing was 5 s between match pages, one page at a time, as approved.

## Next steps (not started)

- Confirm tennis24's MATCH tab directly on a sample, so the totals agreement does not rest on one check.
- Compare side-level values on the 59 shared matches, once the home and away orientation is confirmed.
- Move name proposals to a reviewed provider player id to ESPN athlete id table.
- Run the next event (Shanghai ATP, 119 finals in the snapshots) under the same parameters, with approval.

## Update: name collisions resolved with ESPN data (Wuhan WTA 2026)

The earlier Wuhan numbers in this doc (tennis24 75 linked, 4 to review) are superseded by the resolution
below. Current figures: tennis24 78 of 79 completed ESPN matches linked (75 proposed, 3 stats_match),
365scores 62 linked, 78 of 79 covered by at least one provider. 62 of 62 shared matches agree on totals
and on per-player values in the same orientation.

- **"Monfils" is a label error on tennis24, not a player.** Three tennis24 matches (vs Guo Hanyu, Kartal,
  and Samsonova) carry the code `jyngIesG` and the slug "monfils-elina". Our players table has an ATP
  Gael Monfils and no WTA Monfils, so the name collides. The code maps to ESPN athlete 1797, which the
  players table lists as Elina Svitolina. Each match's four stats equal the 365scores row for the ESPN
  game it resolves to (185366, 185371 and 185349). These links are stored as `stats_match`: provisional,
  backed by cross-provider stats equality, and needing a reviewer's confirmation.
- **McNally vs "Starodubtsewa" stays in review.** The ESPN game is 185318 (McNally vs Starodubtseva,
  athlete 13478, a spelling variant). Neither provider has a second row for that game, and the tennis24
  code `GlqMuuhi` appears in one match only, so it cannot be mapped. It is not inserted.

**Side orientation is not resolved.** Left and right columns agree across providers in all 62 shared
matches, so the providers agree on which column is which. Which column is the ESPN home player is a
different question. The first-listed player in the URL matches ESPN's home player in 19 of 32 mapped
matches on 365scores and in 23 of 41 on tennis24, so the URL order is not a consistent orientation. The
official Rolex Shanghai match pages show player names above their columns, so they could settle this on
a sample. That check is not yet run.

## Shanghai ATP 2026 (tennis24 only)

365scores has no Shanghai league page reachable from its navigation, so Shanghai has one provider.

| Measure | Result |
| --- | --- |
| Matches enumerated (tennis24 results page) | 131 |
| ESPN completed games in snapshots (tournament 315) | 125: 119 Final and 6 Retired |
| ESPN not completed | 6: 5 Suspended, 1 Walkover (reported separately) |
| tennis24 matches parsed ok | 130 |
| tennis24 matches with no STATS tab (walkover) | 1 |
| Parse failures | 0 after the walkover was reclassified |
| Set-tab check: MATCH confirmed and set tabs sum to it | 129 |
| Set-tab check not usable (retired match, one set tab did not parse) | 1 (C25ODU5T, Mejía vs Tseng; match total stored) |
| Completed ESPN games linked uniquely to a tennis24 match | 125 of 125 |
| Shared-provider matches | 0 (no second provider) |
| Identity codes mapped to ESPN athletes (proposed, multi-match) | 70; 59 codes appear in one match only |

Run parameters were the approved ones, with two changes. A match with no STATS tab (a walkover) is now
recorded as `no_stats_tab` instead of an error, because the one timeout in the run came from exactly
that case. The memory floor was respected: the run waited 60 seconds in total. No ESPN request was made:
the crosswalk, resolver and identity map all read the copy database.

## Next steps (updated)

- Run the official Rolex Shanghai match pages on a sample, to settle side orientation for both events.
- Get a reviewer's confirmation for the three `stats_match` links, and for the McNally review case.
- Move from name proposals to a reviewed provider-player to ESPN-athlete table. The identity codes look
  consistent across providers, but the check so far used ESPN data, so it is not independent evidence.
- Decide whether automated prospective capture should be scheduled. Any schedule would run against the
  provider sites and needs your approval first.

## Verified player-level outcomes and daily collection (2026-10-20)

Approved scope: official orientation audit, reviewed identity table, verified outcomes into a research table,
CP4 grader reading only verified rows, and a daily collection job in isolated research staging.

### Orientation audit (official Rolex Shanghai pages)

All 131 official singles pages were fetched and parsed. Each names both players above the stat columns.

- 13 sampled pages map to one ESPN game by exact name pair. In all 13, the official first-listed player is ESPN's
  home player, and tennis24's left column equals that player's aces and double faults.
- Across all 131 pages, the official tier covers 124 of 125 completed Shanghai games. 124 agree with tennis24
  (the left column is ESPN home). One Retired match disagrees: hv2d66ue, Auger-Aliassime vs Ruud, where
  official gives 2 aces to Auger-Aliassime and tennis24 gives 1. Double faults agree. It is in review.
- Header check on tennis24 pages: the first name in the page title is ESPN's home player in 10 of 10 sampled
  pages (Wuhan 6, Shanghai 4). The one "miss" (Zhizhen Zhang vs ESPN's "Zhang Zhizhen") is the same name in
  a different order.

### Reviewed identity table

`provider_player_identity` holds each provider code, its ESPN athlete id where the codes agree, the evidence,
and a verification status. Nothing has a reviewer yet (reviewed_by is empty).

| Event | id_consistent_multi_match | unverified_single_match |
| --- | --- | --- |
| Shanghai (ATP) | 70 | 59 |
| Wuhan (WTA) | 68 | 69 |

No code has a conflicting athlete. Single-match codes are never assigned an athlete.

### Verified outcomes (research table `research_player_match_outcomes`)

Each row is one player in one completed game: tour, ESPN game id, ESPN athlete id, side, aces, double faults,
verification tier, provider row key, the raw provider values, and `eligible_cp4`. Tiers, in priority order:
official_labelled, cross_provider (365scores equal in the same orientation), id_consistent (both codes map to the
game's two athletes, with a confirmed MATCH view or a cross-provider row).

| Tour | Final games | Verified and eligible | Tiers | Not verified |
| --- | --- | --- | --- | --- |
| ATP (Shanghai) | 119 | 119 | official_labelled 119 | 0 |
| WTA (Wuhan) | 74 | 63 | cross_provider 58, id_consistent 5 | 11 |

Unverified WTA finals: 10 whose codes appear in one match and have no second provider, and McNally vs
Starodubtseva (185318), which stays in review. Retired matches are stored and marked ineligible.

### End-to-end proofs

1. **Shanghai singles final** (ESPN 184947, ms001): Davidovich Fokina (athlete 3212, home) 6 aces, 1 double fault.
   Jodar (athlete 12657, away) 12 aces, 2 double faults. This matches the official page and is tier official_labelled.
2. **Wuhan WTA final with distinct values** (ESPN 185369, Ann Li vs Iga Swiatek): Li (athlete 3380, home) 1 ace,
   2 double faults. Swiatek (athlete 3730, away) 0 aces, 1 double fault. Tier cross_provider: tennis24 and 365scores
   agree on the left column, and tennis24's title lists Ann Li first, which matches ESPN's home player.
3. **The Wuhan final itself** (Chwalinska vs Kartal, ESPN 185375) has 0 aces and 1 double fault for each player, so
   it cannot show the assignment. It is stored as cross_provider and eligible, but it is not used as the proof.

### CP4 grader

The grader reads aces and double faults only from `research_player_match_outcomes` with `eligible_cp4 = 1`, and
takes total games from the ESPN final score. The override table is no longer read.

On the copy: 28 locks, 0 with a frozen distribution, so 0 graded matches and every cell is
INSUFFICIENT_PROSPECTIVE_DATA. Verified eligible finals with frozen distributions: ATP 0, WTA 0. The retrospective
finals above cannot become prospective evidence.

### Daily collection (research staging)

`backend/research_daily_collect.py` does one run:
- copies ESPN snapshots for the registered tournaments (381 Wuhan, 315 Shanghai) from the live database,
  read-only. The live database is in WAL mode, so reads do not block its writer;
- enumerates each event's tennis24 results page and fetches only matches not already stored as ok or no_stats_tab;
- rebuilds links, the review resolver, identity and outcomes inside the research database;
- writes a JSON report with fetch counts, failures, stop reasons, memory waits, the crosswalk and the tiers.

The research database is `/root/research/tennis-stats/research.db`. It is not the live database, and the live
database is never written. Unregistered completed tournaments are listed in the report as unsupported.

Smoke test: three new matches per event, all parsed ok, with links and outcomes built. No-op runs: 0 fetched,
and the outcome tiers match the copy exactly (ATP 119, WTA 63).

**The daily schedule is not installed.** Installing `/etc/cron.d/lp-tennis-research-daily` was denied by the
permission system. The entry is saved at `/root/research/tennis-stats/cron/lp-tennis-research-daily`. To enable it,
copy that file to `/etc/cron.d/` with your own permissions. The job runs under `/root/lp-tennis-cp4/backend`, which is
this feature worktree, so the worktree must stay in place.

### Limits

- The orientation rule (left = ESPN home) is verified on 124 official-labelled Shanghai games and 10 sampled
  headers. The Wuhan orientation rests on the header sample and on tennis24 agreeing with 365scores.
- Game-to-match links are still name proposals. A promotion needs a tier with independent evidence: exact official
  names and equal values, equal cross-provider values, or consistent codes plus a confirmed MATCH view.
- The identity table has no reviewer yet. The identity tier is automated, and its exceptions go to the review queue.
- No frozen prospective distributions exist for these matches. Their outcomes support audit and development only.
- Production, picks.dev.db and existing locks were not written.
