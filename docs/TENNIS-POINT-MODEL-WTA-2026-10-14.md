# Tennis point model, WTA main tour (step 1), 2026-10-14

Status: v2. Recent form is added and kept, as for ATP. Rest is measured but not adopted, for the same reason as ATP.
The W events from 2010 are decided one by one, not by a blanket rule. The model reads the dev DB read-only and writes
nothing. The work is on the local branch `feat/tennis-point-model`, not pushed.

## The rule

Main tour = `tourney_level` in G, F, P, PM, I, T1 to T5 in all years, and W dated before 2010. From 2010, W is decided
event by event by `tourney_id`:

- Included (main tour): WTA Finals 2015, Charleston 2, Belgrade (May), Strasbourg, Bad Homburg, Eastbourne, San Jose,
  Cleveland and Chicago 1 (2021).
- Excluded (WTA 125): Parma 2021 and Buenos Aires 125 (2024).
- Excluded, always: C and CC (ITF and low-tier circuits), numeric ITF prize-money codes, D (team competitions),
  O (Olympics), E (exhibition), J (juniors), and the +H codes.

## The eleven W events from 2010

| Event (tourney_id) | Date | Matches | Decision | Basis |
|---|---|---|---|---|
| WTA Finals (2015-W-WT-SIN-01A-2015) | 2015-10-25 | 15 | In | Main tour (user's direction). No serve stats, so it adds nothing to the model. |
| Charleston 2 (2021-2033) | 2021-04-12 | 43 | In | WTA 250 (Wikipedia; WTA page slug `charleston-250`). |
| Belgrade (2021-2035) | 2021-05-17 | 48 | In | Serbia Open, WTA 250 (Wikipedia, Grand Slam History). The 26 to 31 July Belgrade event was a 125 and is not in the data. |
| Parma (2021-2041) | 2021-05-17 | 49 | Out | WTA 125 (WTA page slug `parma-125`). |
| Strasbourg (2021-406) | 2021-05-24 | 47 | In | WTA 250 (Wikipedia). One WTA URL says 500. Main tour either way. |
| Bad Homburg (2021-2017) | 2021-06-21 | 31 | In | WTA 250 (Wikipedia). |
| Eastbourne (2021-710) | 2021-06-21 | 49 | In | WTA 500 (Wikipedia and tennis press). |
| San Jose (2021-703) | 2021-08-02 | 39 | In | WTA 500 (Wikipedia, CoreTennis). |
| Cleveland (2021-2040) | 2021-08-23 | 42 | In | WTA 250 (WTA listing, 250 ranking points). |
| Chicago 1 (2021-2047) | 2021-08-23 | 42 | In | WTA 250 (WTA page slug `chicago-250`). |
| Buenos Aires 125 (2024-2052) | 2024-11-25 | 31 | Out | WTA 125. |

Included: 356 matches. Excluded: 80. The Parma and Buenos Aires decisions rest on WTA URL slugs, the strongest evidence
available here. The other decisions rest on Wikipedia and tennis press, with one conflict noted (Strasbourg).

Effect on the results: the cumulative test log loss moved from 0.6831891 to 0.6831896, and validation from 0.6832753
to 0.6832522. The 2021 events only feed history, since they fall before the 2022 validation year. The decision
changes the history, not the test set. The test set is still 13,264 matches.

## Data

Main-tour matches from 2000, with serve stats present for the points that feed the model. Validation: 2022, 3,706
matches. Test: 2023 to 2026, 13,264 matches and 1,880,683 served points.

## Model

As for ATP: a surface baseline, serve and return rates shrunk toward it with prior strength k, and combined on the odds
scale. In v2 the player counts also carry form: a half-life of 2 years, k = 250 points. Both were chosen on the 2022
validation window. Walk-forward evaluation, with the same-date rule as ATP.

## Results on the test window

| Model | Log loss per point | Mean predicted | Observed |
|---|---|---|---|
| Surface baseline only | 0.684676 | 0.56038 | 0.56433 |
| Server's serve rate only | 0.683629 | 0.56616 | 0.56433 |
| Combined, cumulative (k = 500) | 0.683190 | 0.56503 | 0.56433 |
| Combined, form (half-life 2 years, k = 250), chosen | 0.683129 | 0.56694 | 0.56433 |
| Combined, form, with the validation shift (not used) | 0.683120 | 0.56583 | 0.56433 |

By surface, baseline against the chosen model (log loss per point):

| Surface | Baseline | Form model |
|---|---|---|
| Hard | 0.684369 | 0.682632 |
| Clay | 0.688182 | 0.686857 |
| Grass | 0.678734 | 0.677726 |

## Form: kept, with a calibration cost

Validation and test both improve, which is the rule. Validation: 0.683252 (cumulative) to 0.683168 (2-year half-life).
Test: 0.683190 to 0.683129.

The gain is small: 0.00006 per point on test (0.009%). It is not steady across half-lives. The 0.5-year half-life is worse
than cumulative on both windows (test 0.683387), and the 1-year half-life is about even (0.683209). The 2-year
half-life is at the grid edge, so a longer one was not tested.

Calibration is the real cost. The form model over-predicts the serve-point win rate on test by 0.0026 (predicted
0.56694 against observed 0.56433). The cumulative model was over by 0.0007. The validation-fitted shift (-0.0045 logit)
closes most of that on validation, but leaves +0.0015 on test. Its effect on log loss is small (0.683120 against
0.683129). The protocol uses the uncalibrated model. A level error of this size compounds in games and sets, so the
simulator's WTA probabilities should be read with it in mind.

## Rest: measured, not adopted

Both windows improve: validation in-sample 0.683168 to 0.682922, test 0.683129 to 0.682915. That passes the letter of the
rule. It is not adopted, because the feature does not measure rest. The data has no match dates. `tourney_date` is the
event start, shared by every match in that event, so the "days since last match" in the code is the days between event
starts. The 0 to 3 day bucket is empty by construction. The fitted coefficients (log-odds): server 4 to 7 days -0.015,
15 or more days -0.052, no earlier match -0.241; the returner's are -0.019, -0.072 and -0.181. The same options as ATP
apply: match dates, a round-based proxy, or an explicitly redefined feature with its own validation.

## Limits

- The held-out events: Charleston 2, Belgrade, Strasbourg, Bad Homburg, Eastbourne, San Jose, Cleveland and Chicago 1
  were classified from secondary sources, with one conflict (Strasbourg). Parma and Buenos Aires were classified
  from WTA URL slugs.
- The form half-life is at the grid edge.
- The form model's level calibration is off by 0.0026 on test (see above).
- Team competitions and the Olympics are excluded.
- No tournament-level or best-of effects.
- The loader stores the raw codes. The rule is applied in the model.

## Per-level baseline: tested, not adopted

Keying the baseline and shrinkage by tournament level made WTA worse: validation 0.68328 to 0.68363, test 0.68319 to
0.68363. The cumulative surface baseline stays, as for ATP.

## Commands

    python3 backend/tennis_point_model.py --db <dev DB, read-only> --tour wta \
      --validate-start 20220101 --test-start 20230101 --test-end 20261231

Results are in the session scratchpad as `point-model-wta-formrest-allow.json`.

## Next

1. Step 2, the simulator, is built on these point probabilities (see `TENNIS-MATCH-SIM-2026-10-14.md`).
2. Step 3, the match backtest against Elo, is frozen in `TENNIS-MATCH-BACKTEST-PROTOCOL-2026-10-14.md`.
3. Rest needs a decision: match dates, or an explicit redefinition with its own validation.
