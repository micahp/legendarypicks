# Leagues Hub review — 2026-07-12

## Review subject

- Repository: `legendarypicks`
- Branch: `feat/leagues-hub`
- Reviewed head: `39ac684` (`fix(ufc): make rankings data a release gate`)
- Feature entry commit: `34c6e4b` (`feat: Leagues hub — per-league tabbed pages + WC knockout standings`)
- Base at review time: `dev` / `v0.3.1` (`1637032`)

This document records the evaluation of the Leagues Hub work, the defects found during review,
the corrective commits, and the evidence used to accept the corrected implementation. It is a
code-review record, not a production deployment record.

## What the branch adds

The branch replaces the single Stats navigation entry with a Leagues Hub:

- `/leagues` — league directory for MLB, NBA, NHL, NFL, World Cup, and UFC.
- `/leagues/[league]` — per-league tabbed page.
- MLB/NBA/NHL/NFL — Standings, Stats, and Schedule views.
- World Cup — phase-aware group standings or the canonical knockout bracket.
- UFC — Rankings and Schedule views; it intentionally has no generic Standings or Stats tabs.
- Schedule cards retain league identity and route to `/game/<league>/<game_id>`.

The backend work adds the World Cup knockout feed/normalization and expands the games/standings
contracts needed by the new pages. The UFC ranking view continues to read persisted rankings from
SQLite; it does not scrape UFC.com on the request path.

## User-facing behavior assessment

At the product level, the PR is modest. Its primary behavior is:

1. Give each league its own `/leagues/<league>` route.
2. Put the existing standings/stats presentations inside a shared tab shell.
3. Add a Schedule tab to each league page.

That is useful information architecture, but it is not yet a complete Leagues Hub. Most league
pages are instances of the same generic template rather than meaningfully league-specific
destinations. The PR reorganizes existing surfaces more than it expands what a user can do or learn.

### The Schedule tab is not a complete schedule experience

The Schedule tab has an important UX ambiguity: **the page never says which date it is showing.**

The implementation calls `SportsService.getGames(lg)` without a date. That calls
`GET /api/<league>/games` without a `date` query parameter, and the backend silently defaults to
“today.” Nothing in the tab exposes that contract to the user.

Specific gaps:

- No selected date or “Today” heading is rendered.
- No previous/next-day controls, date picker, week selector, or calendar navigation exists.
- The URL does not encode the selected tab or date, so the schedule state cannot be shared or
  revisited directly.
- Cards show a local time but not the calendar date or timezone context.
- Games are not grouped under explicit day headers.
- The empty state says only `No games scheduled for <league>`, which can mean no games today, an
  off-season league, an unsupported date range, or failed/empty data.
- UFC intentionally hides scheduled start times in the shared `GameCard`, making its Schedule tab
  even less informative about when an event occurs.
- NFL and tournament schedules have no week, round, or stage context.
- The page fetches the schedule immediately even when the user never opens the Schedule tab.

This is especially notable because `SportsService.getGamesByDate(league, date)` already exists.
The PR adds a Schedule tab without wiring the existing date-aware capability into its UX.

### Product verdict

The branch is an acceptable route/tab foundation after its correctness fixes, but **it is not enough
as the finished Leagues Hub feature**. Engineering acceptance of the data contracts should not be
read as product acceptance. A hub should provide clear temporal navigation and enough league-specific
context to make each page more than a renamed Stats page with a one-day, unlabeled game list.

## Review verdict

The initial feature commit was **not ready to merge**. The corrected branch is structurally sound
and its primary UI contracts were exercised in a real browser, but it remains product-incomplete for
the reasons above. The important review result was not that the pages compiled; it was that several
data-shape and state-transition failures were found and fixed before promotion.

The branch should still be treated as a product change larger than a cosmetic Stats-page upgrade:
it changes global navigation, introduces a new route family, and carries production-data requirements
for UFC rankings.

## Findings and corrections

### 1. World Cup team fields were not safe React values

ESPN summary fields can be objects rather than display strings. The first implementation allowed
object-shaped home/away abbreviation values through the knockout endpoint, which could reach React
and produce `Objects are not valid as a React child`.

Correction: `225d352` extracts string abbreviations/names before returning the bracket contract.
The review assertion now requires every match side to be a nonblank `{abbrev, name}` object.

### 2. World Cup could serve stale group standings during knockouts

The initial phase gate did not fail safely. If the tournament had entered knockouts but bracket
retrieval returned no rounds, the page could fall back to group data that was no longer the correct
surface.

Correction: `500db51` makes the phase decision authoritative:

- Group phase returns group standings.
- Knockout phase returns the bracket.
- Knockout phase with an empty bracket returns HTTP 503.
- Phase lookup failure returns HTTP 503 instead of an uncaught 500 or stale groups.

### 3. UFC retained invalid tab state when switching leagues

The generic league page could preserve a previously selected tab that UFC does not support. UFC is
defined as Rankings + Schedule, but navigation from another league could leave it on a stale tab.

Correction: `500db51` resets/validates the active tab per league. The browser harness verifies that
UFC opens on Rankings and exposes neither a generic Standings nor Stats tab.

### 4. Compilation was being mistaken for UI validation

The original work lacked a browser-level acceptance pass across all league variants. That was not
enough for a route whose rendering depends on several distinct backend shapes.

Correction: `500db51` added:

- `backend/test_leagues_hub_assertions.py` for World Cup phase/shape contracts, league propagation,
  and UFC data availability.
- `backend/render_leagues_harness.js` for real rendered pages, uncaught browser errors, active tabs,
  World Cup round/team rendering, UFC tab/content rules, schedule cards, and game-detail routing.

Hermes' final correction pass reported:

- 14/14 focused backend assertions passed at that revision.
- `npm run build` exited successfully.
- 37/37 headless render checks passed.

Those counts describe the reviewed revision. The assertion suite was later expanded by the UFC
production-data work.

### 5. UFC code shipped without its production dataset

The UFC page and endpoint existed, but the original ingest populated `picks.dev.db` only. Production
uses a separate `picks.db`, and the promotion runbook did not include UFC rankings. A later endpoint
change compounded the problem by converting a missing table into HTTP 200 with empty arrays, so a
status-only release check passed while the page had no data.

Correction: `39ac684` removes that silent-empty behavior and makes the dataset part of the release
contract:

- Missing, empty, or incomplete rankings return HTTP 503.
- Ingest validates both P4P groups and all 11 populated weight divisions before replacement.
- Replacement is transactional and preserves the last known-good rows after scrape/insert failure.
- `migrate_ufc_rankings_to_prod.py` backs up SQLite online and promotes only `ufc_rankings`.
- `verify_ufc_rankings.py` fails unless the deployed endpoint contains men's P4P, women's P4P, and
  11 populated divisions.
- The production runbook and scheduled refresh were updated.

The focused UFC suite contains 11 tempfile/in-memory tests and passed after the correction. No real
database is opened by that test suite.

Operationally, production UFC data was subsequently populated from a freshly validated UFC.com
scrape: 208 rows, 16 men's P4P entries, 16 women's P4P entries, and 11 divisions. That data operation
was separate from merging or deploying this branch.

## Acceptance coverage

The corrected review covered the following behavior:

| Surface | Required result |
|---|---|
| League directory | All six supported league destinations are present. |
| MLB/NBA/NHL/NFL | Standings is valid, Schedule is clickable, cards render, and card clicks retain the league in the detail URL. |
| World Cup | Six ordered knockout rounds, 32 matches, and string-safe team objects; stale group fallback is prohibited after the phase transition. |
| UFC | Rankings is the default; unsupported tabs are absent; P4P and divisional rankings render from persisted data. |
| Browser runtime | No uncaught `pageerror` or `console.error` across the six league pages in the review harness. |
| Missing required data | The API fails visibly instead of returning a successful empty contract. |

## Remaining merge and promotion checks

Before merging or promoting this branch:

1. Define and implement the Schedule tab's date model: visible selected date, timezone, date
   navigation, date-aware empty copy, URL state, and league-appropriate week/round context.
2. Decide what league-specific value makes each destination more than the existing Stats content
   moved into a generic tab shell.
3. Confirm that replacing the global **Stats** navigation entry with **Leagues** is the intended
   product decision; it is not merely an internal route addition.
4. Rebase/merge against the chosen integration head and rerun the focused assertions, production
   build, and six-league browser harness.
5. Run the browser harness against a production-equivalent database, not only the populated dev DB.
6. Run the UFC migration/verification gate before deployment and assert nonempty content, not only
   HTTP 200.
7. Verify the real deployed domain after promotion: league directory, one standard league, World
   Cup, UFC rankings, and a schedule-card detail navigation.

## Commit trail

- `34c6e4b` — initial Leagues Hub and World Cup knockout implementation.
- `225d352` — string-safe World Cup home/away abbreviations.
- `500db51` — World Cup phase gate, UFC tab reset, backend assertions, and browser harness.
- `7f7d894` — isolate/ignore the harness build output.
- `e72900d` — attempted packaged UFC fallback; superseded because it masked the production-data
  failure instead of fixing promotion.
- `39ac684` — UFC data becomes an explicit ingest, migration, and release requirement.

## Bottom line

The review changed the branch from “pages that render against the developer's populated environment”
to a foundation with explicit phase contracts, browser coverage, and a production-data gate. It did
not turn the branch into a complete Leagues Hub. The main lesson is broader than World Cup and UFC:
a valid HTTP response, successful build, or technically working tab is not evidence that the product
behavior is clear or sufficient. The rendered state, required production data, and actual user task
must all be verified.
