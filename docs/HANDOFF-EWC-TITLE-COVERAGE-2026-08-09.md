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

## Continuation checkpoint — 2026-08-09 evening

Commit `882daa8 fix(esports): serve validated EWC title history` implements the corrected
repository-side contract:

- strict versioned title snapshots and an exact 24-title manifest;
- source URL/revision identity, checksums, match uniqueness, date/score/template rejection,
  lifecycle and finality evidence, active/upcoming freshness limits, and immutable final data;
- versioned snapshot files with the manifest as the atomic reader boundary, so failed candidates
  preserve the last good publication;
- a bounded `/api/esports/events/ewc-2026/titles/{slug}/matches` route that loads only the selected
  title, merges local snapshot history with current slate rows, and prefers the live slate only
  when stable source identity or participant-plus-time/result evidence proves a duplicate;
- selected-title UI loading/error/pending behavior and published date ranges instead of ISO week
  labels;
- `EwcEventData` / `eventData` naming while preserving the public event route;
- a committed manifest whose 24 entries are explicitly `unavailable` until validated snapshots
  are published.

Verification at this checkpoint:

- `104` EWC backend tests passed, including operator nonzero exit, frozen-final skip, tamper and
  stale-snapshot fail-closed behavior, no-feed history, and slate/snapshot deduplication;
- `29` focused frontend tests passed;
- Python compilation and `git diff --check` passed;
- repository-wide `tsc --noEmit` remains blocked by pre-existing unrelated Flow package, CSS
  module, removed service, and `pages/scores.tsx` target errors; no reported error named an EWC
  task file;
- build and isolated browser verification were not run because the host had only `1.2 GiB`
  available, `2.7 GiB` swap in use, and an unrelated multiprocessing job consuming about 34% CPU.

Source acquisition is still pending. A one-title Chess dry run and a later single no-retry probe
both received Liquipedia HTTP 429, so no snapshot was written. The official API terms require
`action=parse` requests to be limited to one per 30 seconds; the prior candidate used roughly a
2–3 second cadence. Commit `882daa8` corrects the client to a shared opener and a 30-second parse
slot. Do not run the 24-title acquisition until the temporary publisher throttle clears and host
headroom is safe. Start with one title, verify its revision/row population and rendered selected
title, then run sequentially. Do not convert search-engine HTML or cached page summaries into
snapshots.

## Implementation checkpoint — 2026-08-10 (commit `0963be4`)

Liquipedia `action=parse` remained HTTP 429 from this host (probe transcript
`/tmp/ewc-rocket-probe-20260810T0029Z.log`; four bounded attempts, no Retry-After, zero snapshot
data). Acquisition therefore moved to the verified machine-readable providers already configured
and documented in the task brief, and 12 titles are now published with verified data. The
fixture-derived candidate snapshots from the prior preview were unproven (they reused the exact
test-fixture revisions) and were deleted, not republished.

### What was published

12 verified per-title snapshots in `backend/data/esports_ewc_schedules/` (manifest entry per
title with file/checksum/lifecycle/fetchedAt/revisions):

| Title | Source identity (revision) | Rows | Lifecycle | Dates |
|---|---|---|---|---|
| Call of Duty: Black Ops 7 | PandaScore serie 10834 | 28 | final | 08-05..08-09 |
| Chess | Lichess Play-in tour Ywo3zsIE | 7 | upcoming | 08-11 |
| Counter-Strike 2 | PandaScore serie 10846 | 56 | upcoming | 08-12..08-23 |
| Dota 2 | PandaScore serie 10728 | 76 (1 canceled) | final | 07-07..07-19 |
| EA Sports FC 26 | PandaScore serie 10831 (FC Pro World Championship) | 24 | final | 07-25..07-26 |
| Honor of Kings | PandaScore serie 10786 (KWC) | 38 | final | 07-30..08-08 |
| League of Legends | PandaScore serie 10765 | 28 | final | 07-15..07-19 |
| Mobile Legends: Bang Bang | PandaScore series 10754 (MSC) + 10787 (MWI) | 83 | final | 07-01..08-01 |
| Overwatch 2 | PandaScore serie 10807 (OWCS Midseason) | 28 | final | 07-29..08-02 |
| Rainbow Six Siege | PandaScore serie 10826 | 40 (32 finished + 8 upcoming) | active | 08-04..08-15 |
| Rocket League | PandaScore serie 10850 | 28 | upcoming | 08-12..08-16 |
| Valorant | PandaScore serie 10741 | 28 | final | 07-02..07-12 |

All 457 PandaScore rows were re-validated 1:1 against the raw API (`begin_at` → `startTime`,
`status` → `finished`/`canceled`); 100% matched. CS2's population (56) matches GRID's independent
count of 56 EWC main-event series. Chess rows equal the official Lichess broadcast's 7 published
Play-in rounds (LCQ qualifier tours excluded). Counts also match the task brief's verified scan
(r6siege 32 past + 8 upcoming, csgo 56, codmw 28, rl 28).

### Implementation notes

- `backend/fetch_ewc_title_schedules.py` — the snapshot schema is now provider-aware:
  `source.provider` ∈ liquipedia/pandascore/lichess; provider-specific URL identity and revisions
  (PandaScore serie ids as ints; Lichess tour ids as strings); `sourceMatchId` prefixes
  `pandascore:` / `lichess:`; a `canceled` row is validated as terminal (never finished, never
  carries a score) and counts as resolved for `final` finality.
- `backend/fetch_ewc_provider_schedules.py` — the current operator acquisition path. PandaScore
  serie fetch with full pagination, placeholder-zero suppression (a not_started match can carry a
  `results` score 0 with one known opponent; never published), lifecycle derived from published
  population (final only when every row resolved and participants complete), Lichess chess round
  mapping (a round with no games = one honest pending slot; a round with games = one row per game,
  a draw is finished with no fabricated score), lifecycle-aware CLI (frozen final skipped without
  `--refresh-final`), atomic publish, nonzero exit on any failure.
- `backend/routers/esports/ewc.py` — `_snapshot_match` derives the source label from the match id
  prefix; canceled rows land in `completed` (resolved terminal facts), never `upcoming`.
- Frontend — `canceled` added to the `UpMatch` contract; `UpMatchRow` and `EwcMatchRow` render a
  Canceled label; `matchKey` prefers `sourceMatchId` when present (stable snapshot identity), falls
  back to `psId` for live slate rows (pre-existing candidate fix, kept and verified).
- `backend/test_ewc_provider_schedules.py` — 17 new tests (placeholder zero, canceled-terminal,
  lifecycle derivation, provider identity, publish/read roundtrip, Lichess round/game mapping).

### Verification results

- Backend: 149 EWC-focused tests pass (132 existing + 17 new). Repository-wide discover shows 7
  `test_news` errors that are **pre-existing at the base commit** (reproduced on a detached HEAD
  worktree of `0ae8aeb`): an import-order `LP_DB_PATH` binding issue in `test_news.py` vs
  `_core._init_db()`; no EWC file is involved.
- Frontend: 30 focused Jest tests pass (29 + new canceled-row test), including the
  `mockMatchMedia` mobile suite (scrollable title row, match-status navigation).
- `tsc --noEmit`: no errors in any EWC/esports file; remaining repository errors are pre-existing
  (`@onflow/fcl`, `pages/scores.tsx` target, etc.).
- `git diff --check` clean; isolated preview on :8098/:3098 with a temp copied DB and warmers
  disabled (`LP_ESPORTS_WARMER_INTERVAL_S=0`); preview torn down, temp DB removed, ports freed,
  `esports_team_logos.json` runtime mutation reverted.
- Browser gate (desktop, isolated preview): all 24 tiles render; 12 show date ranges + tracked
  matches (464 published matches); 12 show honest `Schedule pending / Match feed pending`;
  selected-title loads real snapshot rows (Dota 2: 76 completed incl. the Vici Gaming vs PlayTime
  canceled row rendered as `Canceled`); CS2 selected title dedupes to 56 with zero duplicates;
  zero JS console errors; no horizontal overflow (`scrollWidth == clientWidth`). Mobile is covered
  by the `mockMatchMedia` Jest suite because the headless browser session blocks `window.resizeTo`
  and no CDP emulation hook is exposed.
- Club Championship: verified separately — status `stale`, visible STALE badge, 10 rows served,
  Liquipedia source label. Not hidden and no freshness threshold was extended.

### Remaining limitations (recorded, not papered over)

12 titles remain honestly `unavailable` (Schedule pending / Match feed pending): Apex Legends,
Call of Duty: Warzone, Crossfire, Fatal Fury: City of the Wolves, Fortnite Reload, Free Fire,
PUBG: Battlegrounds, PUBG Mobile, Street Fighter 6, Teamfight Tactics, Tekken 8, Trackmania. No
permitted machine-readable provider exists from this host: no PandaScore feed or EWC 2026 series
for them (all aliases 404, PUBG feed has no EWC series), GRID Open Access covers only CS2,
the official EWC API is Bearer-gated, the official site is Cloudflare-403, start.gg and FACEIT
require tokens not present on this host, and Liquipedia remains 429-blocked. These are
documented in the manifest as `unavailable` and were not cosmetically renamed.

Routine refresh: upcoming/active snapshots (CS2, RL, R6, Chess) expire per the freshness policy
(24h upcoming / 6h active) and should be re-acquired with
`backend/venv/bin/python backend/fetch_ewc_provider_schedules.py` as their events approach;
final titles are immutable. Acquire from this host only when host headroom allows.

Liquipedia throttle persistence evidence: `scripts/ewc_patient_acquisition.py` (untracked WIP)
probed the Chess page on a ~5-minute cadence for its full 21600s budget (43 probes,
2026-08-10 03:40:50Z through 07:14:32Z); every probe returned HTTP 429 and the script exited 1
("throttle did not clear within 21600s budget"). The block is sustained, not transient — keep
PandaScore + Lichess as the acquisition path for this host.

### First commands for the next session

```bash
cd /root/lp-ewc-coverage
git status --short --branch
git log -4 --oneline
/root/legendarypicks/backend/venv/bin/python -m unittest backend/test_ewc_provider_schedules.py \
  backend/test_ewc_title_schedules.py backend/test_ewc_routes.py backend/test_ewc_contract.py
/root/legendarypicks/node_modules/.bin/jest components/EsportsEwcModule.test.tsx \
  components/EsportsLeagueHub.test.tsx
```
