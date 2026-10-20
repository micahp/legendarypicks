# Tennis model learnings

The single record of gate testing, experiment results and go/no-go calls for the tennis track.
Append-only. One league, two tours, always reported separately.

**Coverage:** Grand Slam, Masters/1000 and Finals, singles only; ATP China Open is the one 500
exception. 500s are tracked but their history is short.

## Decision register

| Item | Result | Verdict |
| --- | --- | --- |
| M2 incumbent vs M1 on ATP (2000 history) | −0.0021818 Brier, CI [−0.002731, −0.001639], 12/12 years | **M2 wins on ATP only** |
| M2 vs M1 on WTA | −0.0003203, CI [−0.000788, +0.000165], 9/12 years | **null — M2 is not validated** |
| 500-level expansion | draws stored per tournament; first event live | added to tracking |
| Version-correct shadow forecasts | ATP `m2-2000` and WTA `m1-elo`, alongside served | **AUTHORISED (CP4 only)** — not CP5 |
| Locks created on page view | 4 of 5 finished Ningbo matches ungradeable | **design flaw, fixed** |

## Entries

### 2026-10-19 — The validated model is not the deployed model
**Learned:** A1's ATP incumbent is **M2 trained from 2000**. The live lock implementation uses
**M2 trained from 2020**. Those are different models, so the ATP result does not transfer to what is
actually serving picks without re-verification.
**Evidence:** A1 per-tour table; live lock path.
**Consequence:** any shadow or prospective comparison must pin the training-history start
explicitly in the model version string. "M2" alone is ambiguous and has already been read as if it
were the deployed model.

### 2026-10-19 — Shadow forecasts authorised, CP4 only
**Learned:** the owner authorised version-correct prospective shadow forecasts alongside the served
model: ATP `m2-2000` and WTA `m1-elo` (WTA M2 is not established). The historical lock table is
preserved and shadow rows carry distinct model versions.
**Evidence:** `BRIEF-TENNIS-SHADOW-2026-10-19.md`.
**Consequence:** this is a research step, not approval to serve. No promotion, no UI change, no
replacement of the served pick until the shadow record has been graded out of sample.

### 2026-10-18 — The deployed ATP model is unvalidated, and on WTA it is worse
**Learned:** on 2000-rated history, M2 beats M1 on ATP by −0.0021818 Brier
[−0.002731, −0.001639] with all 12 years negative. On WTA the difference is −0.0003203
[−0.000788, +0.000165] over 9 of 12 years — the interval contains zero.
**Evidence:** `feat/tennis-track-b-2026-10-18` `e8846405`, `a1_per_tour.json`; populations
37,196 ATP / 41,862 WTA; M1 Elo scored 0.22802 ATP and 0.21596 WTA.
**Consequence:** M2 as deployed is a validated choice on ATP and an unvalidated one on WTA. Do not
present a single tennis number as if both tours behaved the same. A per-tour decision is required.

### 2026-10-18 — A suspended match is not a finished match
**Learned:** treating `state='post'` as finished closed the day around rain-delayed matches, so
results went missing and the slate looked complete when it was not.
**Evidence:** fix `6578059e`; `needs_refresh` no longer keys on state alone.
**Consequence:** completion requires a result, not a status string.

### 2026-10-18 — Surface must key on the canonical major name, not the vendor id
**Learned:** keying surfaces on the ESPN event id left most tracked events with no surface, while
Shanghai and Wuhan worked by accident.
**Evidence:** `ab0080b7`, coverage documented in `f122ba23` and `docs/TENNIS-COVERAGE.md`.
**Consequence:** identity resolution happens on canonical names; vendor ids are aliases, not keys.
Men's Slams are `best_of` 5 and must be modelled as such.

### 2026-10-19 — A lock that depends on a page view is not a lock
**Learned:** lock creation lived only inside the projections API handler, inside a 60-minute
window. A match nobody opened was never locked, and an unlocked match can never be graded because
grading reads the frozen pregame snapshot. Evidence from the WTA Ningbo 500: `185526` 04:05,
`185541` 07:10, `185527` 08:15 and `185544` 09:50 all finished with 0 locks and 0 grades, while
`185533` 11:35 locked at 10:56 and graded normally.
**Evidence:** `backend/tennis_lock_sweep.py`, commit `eaae2736`; verified on a copy of the dev
database at a faked 2026-10-20T04:30Z, 2 locks frozen and idempotent on re-run.
**Consequence:** every pregame snapshot must be taken by a timer, never by a request. The four
missed matches are permanently ungradeable — a missed lock is recorded as missing and is never
rebuilt from post-match data.

### 2026-10-19 — Inspected data is not a holdout
**Learned:** 2023–2026 tennis results have been looked at repeatedly during development. They
cannot serve as a holdout however convenient they are.
**Evidence:** historical tables stop at tourney_date 20260601 ATP / 20260602 WTA.
**Consequence:** label any 2023–2026 result as development data. A prospective window must be
declared before it starts.
