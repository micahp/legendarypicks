# Tennis shadow forecasts, 2026-10-19: wired into the lock window, surfaces across the tracked set

**Status.** The tennis endpoint now writes the shadow rows, inside the same pre-match window as the served lock. Nothing is
served or promoted. This is a CP4 research step. The served forecast, its lock table and its API are unchanged.

- **Branch:** `feat/tennis-shadow-2026-10-19`, off `e8846405`, as the brief specifies.
- **Commits:** `4b67e0de` (surface map across the tracked set), `f706679b` (endpoint wiring, endpoint test, endpoint
  acceptance run), `a9606c8e` (earlier write-path doc, now superseded in its status sections by this document).
- **Brief:** `BRIEF-TENNIS-SHADOW-2026-10-19.md`.

## What is written, and from what

- **Table.** `tennis_shadow_locks`, one row per match and version, keyed on (league, game_id, model_version). It is written
  with `INSERT OR IGNORE`, so a re-run adds nothing and an existing row is never replaced.
- **Versions.** `tennis-shadow-m2-2000-v1` (50/50 logit blend of global and surface Elo, ratings from 2000-01-01, the M2
  that A1 evaluated) and `tennis-shadow-m1-elo-v1` (global Elo over the same ratings). Both are written for every match,
  on both tours. The served label `tennis-global-surface-elo-blend-v2` is not reused.
- **Identity.** The Sackmann identities come from the match, through the same function the served projection uses.
- **Surface.** The whole tracked set, not the served two-event map. `backend/tennis_shadow_surfaces.py` copies, verbatim,
  dev's `SURFACE_BY_EVENT`, `SURFACE_BY_MAJOR`, the ATP and WTA alias lists and `major_for_event`. Dev covers every
  tracked event with a surface, and the copy keeps that property. Each row records how its surface was resolved:
  `event_id`, `major_name`, or `unmapped`. An unmapped event falls back to global Elo for the blend.
- **Window.** The write sits beside the served lock, under the same condition: scheduled match, start within the next hour.
  A match that no request reaches in its window has no shadow row. That is the same convention as the served lock, where
  such a match reads as `missed`.

## What differs from the served forecast, by design

Shadow and served are not the same inputs, and grading has to account for that:

1. **History.** Served ratings start from 2020-01-01. The shadow rows start from 2000-01-01, as the brief specifies.
2. **Surface.** The served projection maps two events, Shanghai and Wuhan. The shadow maps the whole tracked set. The
   served map is not changed, because that would be a served change.

So a served-versus-shadow difference mixes the model with these two input differences. The grading note covers this.

## Verification

- **Replay matches A1.** `research/tennis/shadow/2026-10-19/verify_shadow_replay.py` rebuilds the backend replay for 60
  dated samples per tour, from 2000 to 2026. It compares 11,582 scored rows with the A1 forecasts, with a maximum
  difference of 0.0 (`verify_shadow_replay.json`). This check uses row surfaces, as A1 does, so the surface change does not
  touch it.
- **Unit tests.** `backend/test_tennis_shadow.py` (11 tests) covers same-date isolation, the cutoff, null surfaces, the
  forecast formulas, the unmapped fallback, surface resolution by name, two frozen rows, idempotence, the no-replace rule,
  `missing` rows, and the untouched served table. `backend/test_tennis_shadow_endpoint.py` (2 tests) drives the real route:
  one served row and two shadow rows in the window, none added on a second call, none outside the window.
- **Existing tennis tests.** `test_tennis_model_api_parity.py`, `test_grade_tennis_model.py`, `test_tennis_daily_projections.py`
  and the two shadow files: 27 pass.
- **Wider backend.** 638 pass and 5 fail across the 51 files that touch the games router or tennis projections. The same
  5 fail on the base commit, with a clean export, so they predate this work: `test_leagues_hub_assertions.py`,
  two in `test_news.py`, two in `test_mock_draft_pool_parity.py`.
- **Endpoint, on a copy of `picks.dev.db`.** `acceptance_endpoint.py` calls the real route for the WTA slate of
  2026-10-20, with the clock set to 04:30 UTC. The served projection, the odds lookup and the identities all run as they
  do in production. Only the clock is set, because the real clock is not in the window for these matches.

| Match | Event | Served (version, probability) | m2-2000 (probability, surface, source) | m1-elo (probability, surface, source) |
| --- | --- | --- | --- | --- |
| Yulia Putintseva vs Diana Shnaider (185525) | BNB Ningbo Open | 0.634893 | 0.650527, Hard, major_name | 0.713813, Hard, major_name |
| Sara Bejlek vs Alycia Parks (185543) | BNB Ningbo Open | 0.605530 | 0.606164, Hard, major_name | 0.590864, Hard, major_name |

Two matches start inside the hour, so they are locked, each with a served row and two shadow rows at 04:30 UTC. The other
five start after 06:30 UTC, outside the window, so they correctly get no rows. A second call added nothing. The 21 existing
served rows are unchanged.

## Earlier run, superseded

`acceptance_write.json` came from a direct write on a copy, before the surface map was broadened. Every match in it was
unmapped, so its shadow rows agreed to about 1e-16. The endpoint run above replaces it.

## Grading note: how the three versions are compared once results settle

- **Versions.** Served is the `tennis_model_locks` row. `m2-2000` and `m1-elo` are the two `tennis_shadow_locks` rows,
  labelled `tennis-shadow-m2-2000-v1` and `tennis-shadow-m1-elo-v1`.
- **Settlement.** The winner comes from `tennis_model_grades`, the grader the served rows use. Each frozen probability is
  scored with `_winner_brier`, the same function as for served rows. Only rows with status `locked` are scored. A match with
  no row, or with status `missing`, counts as missing for that version. It is reported as missing and never reconstructed.
- **Comparisons, per tour, on identical matches.** (1) `m2-2000` minus `m1-elo`, Brier, the question for ATP. (2) served
  minus `m1-elo`, the question for WTA. (3) served minus `m2-2000`. Each is a paired difference with a match-clustered 95%
  interval (paired bootstrap, 1,000 resamples, seed 20261019, as in A1), with the years split reported.
- **Eligibility.** Comparison (1) counts as evidence for `m2-2000` only on matches whose `surfaceSource` is `event_id` or
  `major_name`. On `unmapped` matches the two forecasts are the same, so they are reported but not counted.
- **Served comparisons.** Comparisons (2) and (3) mix the model with the history start and the surface map (see "What
  differs"). They are reported with that caveat, and not read as a pure model comparison, unless the served map is aligned.
- **Decision rule, declared before any result.** A version is ahead on a tour only if its paired interval excludes zero on
  eligible matches, with at least 200 eligible matches on that tour. Below 200 the result is reported as not yet readable.
  The 200 is my proposal, for the owner to confirm. Nothing here promotes a model. This is CP4 evidence only.

## Limits

- **No ATP match is upcoming in the store right now.** The seven tennis rows are all WTA. So the ATP path is tested on
  history and on the endpoint's logic, not on a real upcoming ATP match.
- **The surface map is a copy.** Until this branch is rebased on dev, the copy in `tennis_shadow_surfaces.py` has to be
  kept in step by hand. The header records the source commit.
- **Request-driven.** Like the served lock, the shadow write happens when someone requests the slate in the window. A match
  nobody requests in that hour has no shadow row. Grading reads that as missing.
- **Format.** The Elo forecast does not use best-of, so Grand Slam best-of-five matches are scored on the same forecast as
  other matches. The A1 population was best-of-three only.

## Decisions for the owner

1. **Merge.** The endpoint change adds writes to a new table. It does not change any served output. Merging to `dev` and
   deploying to prod are separate steps, and both are yours. The table is created by the code on first request, so the
   prod schema change is additive.
2. **Served surface map.** The shadow maps the whole tracked set and the served projection maps two events. Aligning the
   served map would be a served change (CP5). Until then, served comparisons carry the caveat above.
3. **Threshold.** Confirm the 200-match minimum, or propose another.
