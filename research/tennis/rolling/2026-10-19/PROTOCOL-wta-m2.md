# WTA test of M2: protocol, written before the sensitivity run

- **Written:** 2026-10-19, before any sensitivity result was computed.
- **Question:** Does M2 beat M1 on WTA under the protocol that validated it on ATP, and is the 2026-10-19 WTA null
  (`research/tennis/rolling/2026-10-19/a1_per_tour.json`) an artefact of how M2 was built?
- **Data status:** 2015 to 2026 is inspected development data. 2023 to 2026 has been used for choices. No window here is a
  holdout, and nothing below calls one.

## 1. Was M2 trained on pooled ATP and WTA data?

No, on the evidence in the repository.

- The Elo state is per tour. `research/tennis/rolling/2026-10-18/rolling_origin.py` `winner_records(db, tour, cols)` builds
  fresh ratings for each tour. The live code `backend/tennis_daily_projections.py` `project_day(con, tour, ...)` reads
  `tennis_{tour}_matches` only.
- The M2 constants are not fitted. K = 32 and start 1500 are the standard Elo values fixed in
  `docs/TENNIS-MATCH-BACKTEST-PROTOCOL-2026-10-14.md` (Elo baseline, line 55) before any run. The 50/50 logit weight is
  the design in the live code. Neither was selected on either tour.
- The only constants selected on both tours are `FORM_PLAYER_HALF_LIFE` and `FORM_K` in
  `backend/tennis_match_backtest.py` ("chosen on the 2022 validation window ... for both tours"). They belong to the point
  model, which M2 does not use.

So the registered WTA run already is a WTA-only fit. Re-running it on WTA alone is the same test, not a new one.

## 2. Registered test (the verdict)

- **Configuration:** the shared configuration that validated ATP, unchanged. M1 is global Elo, K 32, start 1500, rows with
  a surface. M2 on 2000 history is the 50/50 logit blend of global and surface Elo over the same history. M2 as deployed
  is shown for reference only.
- **Population and rows:** the winner population of `a1_per_tour.py` (`winner_forecasts`, checked row for row against
  `rolling_origin.py`). Identical matches for every model.
- **Code path:** `research/tennis/rolling/2026-10-19/a1_per_tour.py`, `analyse_tour(db, "wta")`, which calls
  `ro.paired_intervals`. Block key `a1-wta-match` (match-clustered) and `a1-wta-tournament` (sensitivity). 1,000 resamples.
  Seed `20261018`.
- **Primary numbers:** read from `a1_per_tour.json`. They are not recomputed, so the verdict cannot drift from the record.
- **The per-tour hyperparameter question:** the registered model has no per-tour hyperparameter. The verdict therefore uses
  the shared configuration.

## 3. Verdict rule (from the brief, declared before running)

- If the WTA match-clustered interval for M2 minus M1 excludes zero in M2's favour, M2 is validated on both tours.
- If it contains zero, the honest conclusion is **M2 is ATP-only**, and the recommendation is per-tour model selection.
- Pooled numbers do not decide the question. They are reported, but they do not change the verdict.

## 4. Sensitivity (diagnostic only, declared now, cannot change the verdict)

This tests whether a per-tour K would change the picture. It is not part of the registered model.

- **Grid:** K in {16, 24, 32, 40, 48}, applied to both M1 and M2, both tours. Blend weight fixed at 0.5. Start 1500.
- **Tuning window:** 2015 to 2019 only. For each tour and each model separately, K is the value that minimises mean Brier
  on that window. Ties go to the smaller K.
- **Evaluation window:** 2020 to 2026. This is inspected development data, not a holdout. It is also the window where the
  deployed M2 has history, so it is the fair read.
- **Score and interval:** Brier. Paired difference, M2 at its tuned K minus M1 at its tuned K, on identical matches, with the
  same match-clustered bootstrap, block key `wta-k-sens-{tour}`, 1,000 resamples, seed `20261018`. Years negative counted
  over 2020 to 2026 (7 years).
- **Registered-K comparison:** the same 2020 to 2026 difference with K = 32 for both models, for a direct read.
- **Reading:** if the sensitivity interval excluded zero for WTA, it would still not validate the registered M2. It would
  be a candidate for a new registered version with its own protocol and a window that has not been inspected. No such
  window exists yet, because 2023 to 2026 is inspected.

## 5. Outputs

- `research/tennis/rolling/2026-10-19/wta_m2_check.py`, which writes `wta_m2_check.json` and `WTA-M2-TABLES.md`.
- `docs/RESULTS-tennis-wta-m2-2026-10-19.md`.
