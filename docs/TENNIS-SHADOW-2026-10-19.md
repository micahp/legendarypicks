# Tennis shadow forecasts, 2026-10-19: write path built and verified, endpoint wiring not yet committed

**Status.** The shadow write path is built, tested, and verified against A1 and against real upcoming matches. It is
**not yet called from the tennis endpoint.** The call site in `backend/routers/games/misc.py` is an uncommitted edit, and
its import and per-request setup are missing. The edit was denied by the auto-mode permission check, so I stopped there.
As it stands, the endpoint would raise `NameError` for any match inside its lock window, and the existing lock test fails
(1 failed, 23 passed). The pushed commits do not touch `misc.py`, so the served path is unchanged. Nothing is served or
promoted.

- **Branch:** `feat/tennis-shadow-2026-10-19`, off `e8846405` as the brief specifies.
- **Brief:** `BRIEF-TENNIS-SHADOW-2026-10-19.md`.

## What is built

- `backend/tennis_shadow.py`. It writes two shadow rows per match into `tennis_shadow_locks`, under their own labels:
  - `tennis-shadow-m2-2000-v1`: the 50/50 logit blend of global and surface Elo, ratings from 2000-01-01. This is the M2
    that A1 evaluated on ATP.
  - `tennis-shadow-m1-elo-v1`: global Elo over the same ratings. This is the reference A1 kept on WTA.
- **Inputs are the served pipeline's.** Sackmann identities come from the match identity through the same function the
  served projection uses (`_sackmann_player_ids`). The surface comes from the same map (`SURFACE_BY_EVENT`). The served
  label `tennis-global-surface-elo-blend-v2` is not reused.
- **Frozen and idempotent.** A row is written with `INSERT OR IGNORE` on the key (league, game_id, model_version). A row
  that exists is never replaced. A match whose identity is unresolved gets one `missing` row per version. A missed window
  is not written at all, which matches the served convention, where a match with no lock reads as `missed`.
- **The served lock table is never written by this code.** The served lock statement is unchanged.

## Verification

- **Replay matches A1, row for row.** `research/tennis/shadow/2026-10-19/verify_shadow_replay.py` runs an independent
  A1-style replay over the scored population, then rebuilds the backend replay from scratch for a seeded sample of 60
  dates per tour, spread over 2000 to 2026. It compares every scored row on those dates. The result is 11,582 rows
  (ATP 5,157, WTA 6,425), with a maximum difference of 0.0 for both M1 and M2 on 2000 history
  (`verify_shadow_replay.json`).
- **Unit tests.** `backend/test_tennis_shadow.py`, 10 tests, all pass. They cover same-date isolation, the cutoff, null
  surfaces, the forecast formulas, the unmapped fallback, two distinct frozen rows, idempotence, the no-replace rule, the
  `missing` rows, and that the served table is untouched.
- **Real upcoming matches, on a copy of the database.** `acceptance_write.py` copies `picks.dev.db` by the backup API and
  runs the write for the seven upcoming WTA matches in the store (BNB Ningbo Open). Identities are built the way the
  slate loop builds them. The window time is set explicitly to 2026-10-20 04:30 UTC, because the real clock is not in the
  window for these matches. This simulates the write; it is not an endpoint run.
- **Idempotence on real matches.** The second run wrote 0 rows for every match.
- **Served table unchanged.** The served lock table has 21 rows before and after, with an identical content hash.

## Row counts

| Match (game id) | Event | Rows, first run | Rows, second run | m2-2000 (status, probability) | m1-elo (status, probability) | Surface source |
| --- | --- | ---: | ---: | --- | --- | --- |
| Sara Bejlek vs Alycia Parks (185543) | BNB Ningbo Open | 2 | 0 | locked, 0.590864 | locked, 0.590864 | unmapped |
| Yulia Putintseva vs Diana Shnaider (185525) | BNB Ningbo Open | 2 | 0 | locked, 0.713813 | locked, 0.713813 | unmapped |
| Jasmine Paolini vs Anhelina Kalinina (185532) | BNB Ningbo Open | 2 | 0 | locked, 0.636466 | locked, 0.636466 | unmapped |
| Cristina Bucsa vs Polina Kudermetova (185523) | BNB Ningbo Open | 2 | 0 | locked, 0.616876 | locked, 0.616876 | unmapped |
| Jelena Ostapenko vs Belinda Bencic (185530) | BNB Ningbo Open | 2 | 0 | locked, 0.711443 | locked, 0.711443 | unmapped |
| Katarzyna Kawa vs Daria Snigur (185524) | BNB Ningbo Open | 2 | 0 | locked, 0.759181 | locked, 0.759181 | unmapped |
| Guo Hanyu vs Ekaterina Alexandrova (185528) | BNB Ningbo Open | 2 | 0 | locked, 0.757584 | locked, 0.757584 | unmapped |

Shadow rows in the copy after the run: 14. Served lock rows before and after: 21 and 21, content hash unchanged: True.

The served rows are not written by this run, because the served insert is in the endpoint, which is not wired yet. So
the three rows for a match (served, m2-2000, m1-elo) are not yet produced together by a real request.

## A coverage finding that changes what m2-2000 can show

On this branch `SURFACE_BY_EVENT` maps two events, Shanghai (315) and Wuhan (381). Every upcoming match in the store is
BNB Ningbo Open (event 963), which is unmapped. For those matches the blend has no surface term, so **the m2-2000 row
equals the m1-elo row** (the probabilities agree to about 1e-16). The two labels are distinct, but on these matches the
comparison says nothing about M2.

The dev branch has a broader surface map (`ab0080b7`, and `ae5cb074`, which adds Ningbo). Building on it would also
change the served inputs. I did not do that, because the brief fixes the inputs as the served pipeline's. Until the map
covers the tour's events, `m2-2000` can only be read against `m1-elo` on mapped events.

## Grading note: how the three versions are compared once results settle

- **Versions.** Served is the `tennis_model_locks` row, labelled with the served projection's version. `m2-2000` and
  `m1-elo` are the two `tennis_shadow_locks` rows, labelled `tennis-shadow-m2-2000-v1` and `tennis-shadow-m1-elo-v1`.
- **Settlement.** The winner comes from `tennis_model_grades`, which the served grader uses. Each frozen probability is
  scored with `_winner_brier`, the same function as for served rows. Only rows with status `locked` are scored. A match
  with no row, or with status `missing`, counts as missing for that version and is reported as missing. It is never
  reconstructed.
- **Input difference, by design.** Served ratings start from 2020-01-01, and the shadow rows start from 2000-01-01, as the
  brief specifies. The served-versus-shadow comparison therefore also measures the history start.
- **Comparisons, per tour, on identical matches.** (1) `m2-2000` minus `m1-elo`, Brier. (2) served minus `m1-elo`.
  (3) served minus `m2-2000`. Each is a paired difference with a match-clustered 95% interval (paired bootstrap, 1,000
  resamples, seed 20261019, as in A1), with the years split reported.
- **Eligibility.** Comparison (1) counts as evidence for `m2-2000` only on matches with `surfaceSource = event_map`. On
  unmapped matches the two forecasts are the same, so they are reported but not counted.
- **Decision rule, declared before any result.** A version is ahead on a tour only if its paired interval excludes zero on
  eligible matches, with at least 200 eligible matches on that tour. Below 200 the result is reported as not yet readable.
  The 200 is my proposal, for the owner to confirm. Nothing here promotes a model. This is CP4 evidence only.

## Decisions for the owner

1. **Wiring.** Approve the endpoint change in `misc.py`: the import and the per-request setup. The call site is already
   in the uncommitted edit. Until that is approved and committed, the shadow rows are not produced by the endpoint.
2. **Surface coverage.** Either build the branch on dev, to get the broader map, or accept that shadow M2 is only
   informative on Shanghai and Wuhan.
3. **ATP.** No ATP match is upcoming in the snapshot store right now (the seven tennis rows are all WTA). The ATP path has
   been tested on history only, not on a real upcoming match.
