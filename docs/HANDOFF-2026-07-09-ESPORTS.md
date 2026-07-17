# Esports work handoff — 2026-07-09

## Read this first

The repository is `/root/legendarypicks` on branch `feat/live-discounts`.

Do not discard the current working tree. Three modified files contain unfinished but intentional esports work:

- `backend/routers/esports/matcher_assertions.py`
- `backend/routers/esports/pandascore.py`
- `backend/routers/esports/slate.py`

The other untracked files shown by `git status` predate this task or belong to the user. Do not add, edit, delete, or commit them unless the user separately asks for that.

Read these before changing behavior:

- `AGENTS.md`
- `docs/ESPORTS-EXPECTED-BEHAVIOR.md` (the esports source of truth)
- the full diff of the three modified files

The backend was last running on port `8095` with the uncommitted code, but the final API check was interrupted. Treat the implementation as unverified until completing the checks below.

## Already committed and pushed

The branch already contains these commits:

- `d465094 fix(esports): resolve the EWC + minor-league result holes`
- `0137514 fix(esports): finish result aliases and scoped LP dedup`

They include:

- PandaScore past-match ordering by `-scheduled_at`.
- Retryable `ended_unknown` results and result promotion persistence.
- Shared team aliases for NIP, AG.AL, BB, and SYF.
- Per-fixture PandaScore matching that fixes MIBR/Anyone's Legend and Hero Jiujing/SYF without making unsafe global aliases.
- Scoped LP/LargadosYPelados deduplication.
- A standalone matcher assertion suite.

Before the current uncommitted work, the live API had 296 matches, 208 finished matches, and four unresolved results.

## What the four unresolved cards actually were

They were not all the same kind of failure.

### 1. Prestige Esports vs Vasteras Esport

PandaScore has finished match `1568949`, scheduled `2026-07-04T10:30:00Z`, as `Prestige Academy 1–2 Västerås`, United21 Season 52. The archived card is at 10:40 and names the teams `Prestige Esports` and `Vasteras Esport`.

This is a narrow fixture-name mismatch. Do not add a global `Prestige Esports == Prestige Academy` alias. It is only safe when United21, season, time, and the opposing side establish the same fixture.

### 2. Leo Team vs Prestige

PandaScore match `1568951` is currently `not_started`, scheduled `2026-07-10T13:30:00Z`, as `LEO vs Prestige Academy`, United21 Season 52. The local archived copy was dated July 8 at 10:30 and incorrectly became a final.

This is a reschedule problem. A stable PandaScore match ID must allow the same match to move well beyond the ordinary time window and return from an archived/unknown state to scheduled.

### 3. Metanoia Wolves vs Bounty Hunters

This was a real July 5, 2026 match in `RES Showdown South America Fall 2026: Open Qualifier #2`. The local league text incorrectly said Fall 2025. DRAFT5 reports Metanoia winning 13–11 on Ancient.

The match is absent from PandaScore. The user explicitly did **not** approve adding DRAFT5 or another qualifier-results source yet. Correct the event identity, but leave the result unresolved until a source decision is made.

### 4. Arch vs Virtus.pro

This was a real July 4, 2026 match in `RES Showdown Europe Fall 2026: East European Open Qualifier`. The local league text incorrectly said Fall 2025. Liquipedia shows Virtus.pro winning the qualifier and Arch placing 3rd–4th, but the match is absent from PandaScore.

As above, correct the event identity but do not build a new qualifier-results integration without user approval.

All four dates were within PandaScore page-one time coverage during the audit. Pagination was not the cause.

## Current uncommitted implementation

Review the diff rather than blindly replacing it. The intended changes are:

### `pandascore.py`

- `_ps_league_compatible(...)` narrowly recognizes matching United21 fixtures and rejects conflicting season numbers.
- `_ps_enrich(...)` now accepts `league`, `ps_id`, and `allow_reschedule`.
- A fixture-scoped United21 fallback permits the Prestige Esports/Prestige Academy variation only when the rest of the fixture aligns.
- A stable PandaScore ID bypasses the normal 36-hour matching limit.
- A United21 `not_started` candidate may reconcile a reschedule within seven days.
- Candidate ranking prefers the stable ID and then the closest time.

### `slate.py`

- `lmap` is no longer an allowed merge suffix.
- Rows with two team names containing `- LMap N` are treated as map markets, not series fixtures.
- Map-market archive rows are dropped, and residual `- LMap N` text is removed from team/favorite display labels.
- Exact metadata corrections map the two RES fixtures to their real 2026 qualifier names.
- `psId` is carried and persisted.
- Cluster reconciliation can unite rows with the same `psId` despite a large time shift.
- An archived unknown United21 row can be reconciled back to a future scheduled match, with its time and canonical names updated and its false-final fields cleared.
- Results-store loading/saving normalizes keys and purges stale map-market records.

The LMap problem appears to have two forms:

- Six stale, two-sided map-market rows such as `Poor Rangers - LMap 2` versus another `- LMap 2` team.
- Roughly 20 legitimate EWC series rows whose teams were clean but whose `favorite.name` was contaminated with `- LMap 2`.

The current implementation is intended to remove both forms from the emitted slate without allowing map rows to merge into series rows.

### `matcher_assertions.py`

The suite was extended to cover:

- `Team Liquid` not matching `Team Liquid - LMap 2`.
- Map-market detection and display-suffix removal.
- Stable-ID clustering across a reschedule.
- Exact RES qualifier-label correction.
- Fixture-scoped Prestige matching.
- Reconciliation of a postponed United21 fixture beyond the ordinary time guard.

It last passed all 43 assertions.

## Finish and verify this work

Do these in order.

1. Inspect `git diff` and preserve the intent above.
2. Run syntax and matcher checks:

   ```bash
   git diff --check
   backend/venv/bin/python3 -m py_compile \
     backend/routers/esports/pandascore.py \
     backend/routers/esports/slate.py \
     backend/routers/esports/matcher_assertions.py
   backend/venv/bin/python3 backend/routers/esports/matcher_assertions.py
   ```

3. Restart or confirm the development backend on `:8095` and query `/api/esports/upcoming`.
4. Verify these outcomes in the actual JSON, not only in unit assertions:

   - Prestige/Västerås is finished, with winner B and score 1–2.
   - LEO/Prestige Academy is scheduled for July 10 at 13:30 UTC and is no longer a false final.
   - Exactly two unresolved results remain: the two RES qualifier matches.
   - Both RES cards display their correct 2026 qualifier league names.
   - No emitted team or favorite name contains `LMap`.
   - There are no emitted two-sided map-market rows.

   A useful audit command is:

   ```bash
   curl -sS --max-time 60 http://127.0.0.1:8095/api/esports/upcoming | jq '{
     counts: {
       total: (.matches | length),
       finished: ([.matches[] | select(.finished)] | length),
       scheduled: ([.matches[] | select((.live | not) and (.finished | not))] | length),
       unknown: ([.matches[] | select(.resultUnknown == true)] | length),
       lmap: ([.matches[] | select(((.teamA // "") + " " + (.teamB // "") + " " + (.favorite.name // "")) | test("lmap"; "i"))] | length)
     },
     targets: [.matches[] | select(([.teamA, .teamB] | join(" ") | test("Prestige|Vasteras|Västerås|Leo Team|LEO|Metanoia Wolves|Bounty Hunters|Arch|Virtus.pro"; "i"))) | {title, league, teamA, teamB, startTime, live, finished, state, winner, score, resultUnknown, psId}],
     unknown: [.matches[] | select(.resultUnknown == true) | {league, teamA, teamB, startTime}]
   }'
   ```

5. Inspect `backend/data/esports_results.json` after the rebuild. Confirm old LMap keys are gone, RES entries are re-keyed to the corrected metadata, and the stale LEO unknown-result key was removed. This generated data file should not be committed unless repository policy clearly says otherwise.
6. Update `docs/ESPORTS-EXPECTED-BEHAVIOR.md` in the same commit:

   - Mark LMap archive purging/sanitizing as implemented.
   - Document stable `psId` reschedule reconciliation.
   - Document the fixture-scoped United21 Prestige bridge.
   - Document the two corrected RES 2026 qualifier identities.
   - Leave qualifier-result sourcing explicitly open/deferred.

7. Test the Results UI in a browser and check the console/page-error count.
8. Commit only the three code files and the updated behavior document. A suitable message is `fix(esports): reconcile reschedules and purge map markets`.
9. Push `feat/live-discounts` only after all checks pass.

If the API result differs from the expected state, diagnose it before committing. Do not weaken team identity globally merely to make the counts match.

## Next task: Scheduled tab (highest priority after the above)

The user reported that scheduled matches are not grouped correctly:

- Today is not first.
- Days are out of chronological order.
- The same day appears in multiple separate groups.

The likely cause is in `pages/esports.tsx`, in `UpcomingSlate`. It filters scheduled rows and groups only consecutive rows with the same display label. However, the backend deliberately sorts the combined slate by prominence/tier/stage before start time. Therefore the same calendar day can recur later in the list.

Fix this in the Scheduled UI without changing the backend's Live-tab prominence ordering:

1. Build scheduled rows with `!m.finished && !m.live`.
2. Sort those rows by numeric `startTime` before presentation.
3. Group by a stable local-calendar date key, not the display string and not adjacency. A local-midnight epoch or local `YYYY-MM-DD` key is appropriate.
4. Sort date groups chronologically.
5. Sort games within each group chronologically.
6. Derive `Today`, `Tomorrow`, or the formatted date separately as the display label.
7. Verify that Today is first when it has matches and that every date has exactly one heading.

The user said this grouping/order issue matters more than the logo issue below.

## Next task: possibly flipped team logos

The user reported that the first result on the tunnel page showed flipped logos and asked whether it was a one-off or a general issue. Do not patch only the first card. Audit the population.

Likely code paths to inspect:

- PandaScore's `swapped` alignment in `_ps_enrich`, which must keep score, winner, and logos on the same sides.
- Cluster display-name adoption, where canonical team names may change after a base row has already supplied logos.
- The current fill logic in `slate.py`:

  ```python
  if ps.get("logoA") and not m.get("logoA"):
      m["logoA"], m["logoB"] = ps["logoA"], ps.get("logoB")
  ```

  This couples the two sides: it only runs when A is missing, and can replace or fail to fill B inconsistently. Prefer independently aligned per-side filling after confirming the matched orientation.

Suggested investigation:

1. Identify the actual first Results row returned by the API and the first row rendered in the UI; they may differ because of frontend filtering/sorting.
2. Compare each side's displayed name and logo against the matched PandaScore opponent identity.
3. Search the full returned population for A/B reversals, missing-one-side cases, and name changes after clustering.
4. Add synthetic assertions for both normal and swapped PandaScore orientation and for cluster display-name adoption.
5. Verify the Results and Scheduled tabs visually, including the originally reported first card.

## Guardrails

- Do not introduce a global academy/base-team equivalence.
- Do not use a broad fuzzy matcher to eliminate the last two unknown results.
- Do not add DRAFT5/Liquipedia scraping or another qualifier source without user approval.
- Do not change backend slate ordering merely to fix Scheduled grouping; the frontend tab should impose its own chronological view.
- Do not commit generated logs, `.hermes`, or unrelated untracked files.
- Preserve clean-code boundaries, but treat any large cleanup as a separate task unless it is required for these fixes.

