# EWC title coverage handoff — 2026-08-09

## Objective

Make every EWC title page/tile useful from published schedule and result data. In this task,
`pending` means the schedule/results data has not been ingested or is not yet published. It is
not a branding problem.

The word `projection` is misleading in this area. The existing endpoint
`/api/esports/events/ewc-2026` returns an EWC event payload; it is not predicting anything.
Rename internal types, variables, and comments to `event data` or `event payload` while keeping
the public route stable unless there is a separately justified compatibility change.

## Repository state at handoff

- Worktree: `/root/lp-ewc-coverage`
- Branch: `fix/ewc-title-coverage`
- Clean HEAD: `a12d2e0 feat(esports): data-derived EWC title coverage — per-title published schedules + feed counts`
- Audit parent: `5eb94b3 docs(esports): EWC title coverage audit — pending tiles are a data-coverage gap, not branding`
- Base `dev`: `08d2133 fix(esports): use scrollable EWC title row`
- No uncommitted changes existed before this handoff document was added.
- Managed `/root/legendarypicks`, DEV services, production, databases, tags, and remote branches
  were not changed or restarted.

## Clarified data lifecycle

Fetching is operator-run only. Never fetch Liquipedia or another publisher in an API request.

1. A completed title is fetched and verified once, then its schedule/results snapshot is frozen
   and served locally. It should not be periodically refetched merely because a user opens the
   page.
2. An upcoming or active title may be refreshed by an explicit operator run while published
   dates, participants, brackets, or results can still change.
3. Once a title is demonstrably final, mark it final and stop routine refreshes. Do not infer
   finality from the current date alone. Require source-backed completion: all included matches
   resolved, no unpublished participants needed for completeness, and the publisher revision
   recorded.
4. If a source has not published enough data, preserve an honest `pending` or `unavailable`
   state. Never invent TBD teams, dates, scores, weeks, or matches.
5. Keep a manifest for the exact 24-title catalog. Each available per-title snapshot should have
   its identity, source revision, fetch time, lifecycle (`upcoming`, `active`, or `final`), and
   checksum validated before it is exposed.

Per-title snapshots plus a validated manifest fit this lifecycle better than rewriting one
monolithic 24-title data file: completed titles can remain immutable while active titles can be
updated independently. Publication of each file and the manifest must still be atomic, and the
reader must fail closed on any identity or checksum mismatch.

## What commit `a12d2e0` added

- `backend/fetch_ewc_title_schedules.py`: MediaWiki fetch/parser and per-title JSON writer.
- `backend/routers/esports/ewc.py`: per-title schedule metadata in the EWC response.
- Backend tests and three real wikitext fixtures for Chess, CS2, and Rocket League.
- UI metadata for schedule status/count/weeks.

The branch has no published runtime snapshots under `backend/data/esports_ewc_schedules/`, so a
clean checkout still reports all 24 schedule sources unavailable.

## Verified defects in the current candidate

1. The fetched `matches` are never returned as title match rows. The API exposes only schedule
   metadata/counts, while `pages/leagues/esports.tsx` renders games exclusively from the existing
   slate payload's `matches` buckets. The 16 no-feed titles and three aged-out titles therefore
   remain empty.
2. `scheduleCount` and `scheduleStatus` are calculated in the page but do not populate the game
   list. Passing tests do not cover the central missing-data behavior.
3. The fetcher derives ISO calendar week numbers and the UI labels them `Week N`. Those are not
   EWC program weeks 1–7 and must not be presented as such. Prefer date ranges, or map program
   weeks from an explicitly validated EWC calendar contract.
4. The parser is not truly fail-closed: malformed dates/scores and unknown templates can degrade
   silently to null/pending values.
5. The runtime reader does not fully validate event identity, title slug, checksum, source
   revision, or lifecycle/freshness policy before exposing a snapshot.
6. The bulk fetch command can exit successfully despite individual title failures. Operator runs
   need a nonzero exit for failed required targets and an exact success/failure summary.
7. The `EwcProjection` name and `projection` variables imply prediction despite carrying ordinary
   event data.

## Corrected implementation plan

1. Rename `EwcProjection` and local `projection` identifiers to `EwcEventData`/`eventData` across
   `components/Esports/EwcModule.tsx`, `pages/leagues/esports.tsx`, tests, and related comments.
   Preserve the existing HTTP route for compatibility.
2. Define and test a strict snapshot schema and exact 24-title manifest. Validate schema version,
   EWC 2026 identity, title slug, source URL/wiki/page/revision, checksum, match uniqueness,
   chronological fields, lifecycle, and finality evidence.
3. Repair the parser so unsupported templates, malformed required values, duplicate match IDs,
   wrong-event rows, and partial required output reject the candidate instead of publishing it.
   Preserve the last good snapshot on every failure.
4. Make the operator command lifecycle-aware:
   - skip frozen `final` titles by default;
   - fetch selected/upcoming/active titles sequentially through the approved API;
   - require an explicit override to refresh a final title;
   - atomically publish a validated title snapshot and then its manifest entry;
   - exit nonzero if any requested title fails.
5. Add a bounded snapshot-backed per-title API response for matches, or include selected-title
   matches in the existing event response. Do not download all historical matches on initial page
   load if the page only needs counts/status. No request-path publisher access.
6. When a title is selected, display its real local snapshot rows. Deduplicate against live slate
   rows using stable source identity first; never use time alone. Prefer live slate state for an
   actively changing duplicate, and frozen snapshot results for completed history.
7. Replace ISO-week labels with honest published dates or validated EWC program-week labels.
   `pending` remains visible when schedule/results data is absent.
8. Add assertions that a no-feed title with a valid snapshot actually shows games, an aged-out
   title shows frozen results, duplicate slate/snapshot rows render once, a missing snapshot stays
   pending, and a final snapshot is skipped by the default fetch run.

## Verification order

Run each layer independently and record exact commands/results:

1. Parser fixtures: valid published rows, TBD handling, malformed date/score, unknown template,
   qualifier exclusion, duplicate identity, and last-good preservation.
2. Snapshot/manifest contract: exact 24 slugs, checksums, wrong-event rejection, lifecycle and
   finality validation, atomic failure behavior.
3. Backend route tests: summary metadata plus selected-title schedule/results, honest missing data,
   and slate/snapshot deduplication.
4. Frontend tests: title filters, real no-feed/aged-out rows, pending state, date/program-week
   wording, loading/error states, and no duplicate games.
5. Python compile/lint checks and frontend type/build checks using repository-provided binaries;
   do not run `npm`, `npx`, or `yarn` from the worktree.
6. Exact-route browser verification on an isolated disposable preview only, desktop and mobile,
   with zero page/console errors. Do not use or restart the managed DEV stack.
7. Confirm `git diff --check`, review the complete diff, and commit only task-owned paths.

Baseline already reproduced during takeover review: 37 backend unit tests and 14 frontend Jest
tests passed, plus Python compilation and `git diff --check`. Treat that only as a regression
baseline; it does not prove the missing-title behavior works.

## Source/resource guardrails

Before a real 24-title source run, inspect host load and memory. Fetch sequentially, one page at a
time, with a descriptive user agent and bounded delay. Test one title first. A full run is roughly
one approved MediaWiki API request per mapped competition page and should be announced before it
starts. Do not scrape HTML and do not add request-time network access.

## Safety and release boundary

- Work only in `/root/lp-ewc-coverage`.
- Preserve unrelated user work and use `apply_patch` for edits.
- Do not modify a DEV or production database.
- Do not restart managed services or occupy their ports.
- Do not push, merge to `dev`, deploy, tag, or promote without explicit user authorization.
- At completion, report candidate evidence separately from DEV and production state.

## First commands for the next session

```bash
cd /root/lp-ewc-coverage
git status --short --branch
git log -3 --oneline
sed -n '1,260p' docs/HANDOFF-EWC-TITLE-COVERAGE-2026-08-09.md
git show --stat --oneline a12d2e0
rg -n "EwcProjection|projection|scheduleCount|scheduleStatus|scheduleWeeks" \
  components/Esports/EwcModule.tsx pages/leagues/esports.tsx pages/esports.tsx \
  backend/routers/esports/ewc.py backend/fetch_ewc_title_schedules.py
```

Start by writing the strict schema/lifecycle tests and the no-feed-title API/UI behavior test.
Those tests expose the actual gap before restructuring the fetcher or UI.
