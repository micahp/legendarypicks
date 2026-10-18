# SPEC: NFL rushing carries distribution v1

Status: PRE-REGISTERED 2026-10-17, before any fit or holdout number was computed on this branch.
Branch `feat/nfl-rushing-carries-dist-v1`, based on `scratch/spec-b-rebase`.

## The question

Spec B projects a rushing-carry **point estimate** conditional on the player appearing:

    car = team_volume('car', K_T=8) * script_factor * share_v20

and publishes `p_plays` beside it, but it has **no carry-count distribution at all**. The receiving
side has one (`simulate()`: NegBin targets, Binomial receptions, Gamma-sum yards). Rushing does not.

Question under test: does modeling **participation** and **carry-count uncertainty** explicitly beat
the distribution Spec B produces today?

The point estimates do not move. Every candidate below is anchored on the frozen Spec B `car` mean for
that player-game. Only the shape of the distribution around it changes. Rushing efficiency
(`rush_yds`, `rush_td`) is not touched in this experiment, so any difference is attributable to the
count layer.

## Population (pre-registered)

- Regular season, weeks 3 to 18, seasons 2025 (holdout) and 2026 (development evidence).
- Candidates: `History.candidates(season, team, week)` — the players who logged for the team in its last
  three games before the target week. This is Spec B's own candidate set, so a player who has missed
  the last three games is out of scope; within scope, participation is exactly the injury-report
  question.
- Positions RB and FB (FB folded into RB by `History.load`). **QB is reported separately and is not part
  of the adoption gate** (see the audit below). WR/TE are out of scope.
- A candidate enters the population when Spec B returns a carry mean `m > 0` for him. No post-game
  filter of any kind: whether he played, and whether he carried, is the outcome.
- Outcome: `carries` from the weekly box score, **0 when he has no log row that week**. The population
  therefore contains genuine zero-carry games (played, no carry) and inactive games (did not play).

## The target is the box score, and the audit says what it counts

`backend/audit_nfl_rushing_attempts.py` reconciles the weekly `carries` with `nfl_pbp` per player-game.

- Weekly `carries` **includes quarterback kneels** and **excludes two-point tries**. With two-point
  rushing plays removed, the two sources agree **exactly on every player-game** in all 17 audited
  seasons (2010-2026: 26,740 RB player-games, 10,059 QB player-games, 0 mismatches).
- QB carries are not RB carries: **43.9% of QB box-score carries are scrambles and 21.3% are kneels**,
  against 0% of either for running backs. Mixing them would fold a designed run, a broken play and a
  victory formation into one count. Hence QB out of the gate.

## The four distributions

Let `m` be the frozen Spec B carry mean for the player-game (conditional on playing), `p` the fitted
probability that he appears, `q` the fitted probability that he carries at least once given that he
appears, `R` a NegBin dispersion (`var = m + m^2 / R`), `R_t` the dispersion of a zero-truncated
NegBin (`ZTNB`).

| id | distribution | what it adds |
|---|---|---|
| B0 | `NB(m, R)` | nothing: the incumbent shape, no participation, no hurdle |
| B1 | `(1-p) * [0] + p * NB(m, R)` | participation |
| B2 | `(1 - p*q) * [0] + p*q * ZTNB(m/q, R_t)` | participation + role-aware hurdle |
| B2' | `(1-q) * [0] + q * ZTNB(m/q, R_t)` | hurdle only; reported on the played-only subset, not gated |

`ZTNB(m/q, R_t)` has mean `m/q`, so `q * ZTNB` has mean `m` and B2 keeps the unconditional mean of the
conditional model. B2' exists to separate the two mechanisms: B2 - B1 is the count-shape contribution,
B1 - B0 is the participation contribution.

PMFs are computed analytically (NegBin and zero-truncated NegBin), not by Monte Carlo. CRPS, coverage
and quantiles are exact for the stated distribution; there is no simulation error in the comparison.

## Fitting: forward only, training seasons only

For each evaluation season, every parameter is fitted on **seasons strictly before it**:

- `R`: method of moments on the training player-games **he played**
  (`played = 1` from the availability table, so a played game with no box-score row counts as a zero
  carry), `R = sum(m^2) / sum((k - m)^2 - m)`, floored at 0.5.
- `q`: by usage tier of the projected mean (`m < 3`, `3 <= m < 8`, `m >= 8`), the share of played
  training player-games with at least one carry.
- `R_t`: grid `{0.5, 1, 2, 3, 5, 8, 13, 21, 34, 55}`, selected by minimum mean CRPS on the training
  player-games **with at least one carry** (the zero-truncated component is fitted on the truncated
  population).
- `p`: by `report_status` (`Questionable`, `Doubtful`, `Out`, no designation), the share with
  `played = 1` among **candidates** in training. Availability exists only for 2024 onward, so the 2025
  evaluation fits `p` on 2024 and the 2026 evaluation fits it on 2024-2025. All four parameters therefore
  live on the same played/not-played event and the same population as the graded items.
- Spec B's own constants are frozen at their current values. Nothing in the engine is refitted here.

### Correction to this section, made before any valid holdout number

The first draft said `R`, `q` and `R_t` were fitted on training player-games **with a box-score row**.
That is wrong for a participation model: a player can play and record nothing, so the box-score row is
not the participation event, and conditioning on it inflates both `q` and the dispersion. The parameters
are fitted on `played = 1` from the availability table, which is the same event `p` predicts. The
correction was made after the first harness run returned a `p` of 0.65 for undesignated players (a
definitional artifact) and before any number from the corrected harness was computed. The invalid first
run is not reported.

## Metrics

Primary: **CRPS** on the carry count, over the full pregame population. Secondary: 50/80/90% central
interval coverage (exact discrete quantiles), mean bias, MAE of the predictive mean, and the Brier score
and AUC of `P(carries >= 1)`. Per position (RB, and QB separately), and split by played/inactive.

Paired comparisons are per player-game, differenced against B0, with a 95% interval clustered by game
(team-games share a game id, and both teams' carries come from the same game script).

## Adoption gate (pre-registered)

B2 is adopted only if **all** of the following hold:

1. CRPS is lower than B0 with a paired game-clustered 95% interval that **excludes zero**, on the 2025
   holdout **and** on the 2026 development season.
2. Coverage at 50%, 80% and 90% is closer to nominal than B0's on both seasons.
3. MAE of the predictive mean is no worse than B0's by more than 0.02 carries.

If the gate fails, the verdict is NOT_ADOPTED, the result is recorded, and the workstream moves to the
next facet. No post-hoc re-specification of the population, the tiers or the gate.

## Research discipline: 2026 is development evidence

2026 has been analysed repeatedly in this workstream, so it is **explored development evidence**, not a
fresh test. 2025 is the holdout. Once the candidate is frozen, the prospective confirmation is
**2026 weeks 7 to 18** (games not yet played as of 2026-10-17), graded once they are complete, with the
frozen parameters and no refitting. That window is the only genuinely new evidence this experiment will
produce.

## Deliverables

- `backend/audit_nfl_rushing_attempts.py` — the reconciliation above.
- `backend/nfl_rushing_carries_dist_v1.py` — the harness.
- `docs/RESULTS-nfl-rushing-carries-dist-v1.md` — results, verdict, prospective confirmation plan.
- `docs/frozen-nfl-rushing-carries-dist-v1.json` — the frozen parameters the prospective run must use.
