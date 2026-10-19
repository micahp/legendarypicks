# PRE-REGISTRATION: FBS Phase 5 play-by-play simulator (2026-10-19)

Status: **pre-registration only.** No simulator has been fit, run or scored. This commit is the
gate: any fit, simulation or scoring that begins before the commit containing this file exists is
void, and the deviation is reported rather than repaired. Branch
`feat/fbs-phase5-2026-10-19`, base `feat/fbs-archive` `5397c0dc`.

This is a new track. It changes no existing FBS gate, model, production surface, scheduler or
database. 2025 is the frozen holdout; 2026 is forward only; neither is used for design.

## 0. Data-support verdict

**The data supports the play-level attribution the simulator needs, with the gaps enumerated
below.** On the relevant plays, the union of the SportsDataverse sources gives passer attribution
98.0-100%, receiver-on-completion 98.97-100%, rusher 98.12-99.33% in the merged hierarchy (the
2025 `cfbfastR` rusher *name* column is only 55.98% and its ID 94.65%, so ESPN/NCAA —
99.33%/98.12% — take precedence when the ID is the only cfbfastR field), and targets 97.67-100%
(NCAA `cfbfastR` is 100%). The union of the three PBP sources covers **6,567 of 6,568** FBS-any
regular games 2018-2025; one 2024 game has no PBP from any source. Participation is available
2018-2025 for the key skill roles, not full 11-player snap counts. The game-roster `starter` flag
is populated only in 2025 (17,616 True of 214,432 rows) and `did_not_play` is never true, so
playing time must be validated from participation and box scores. There is **no 2018-2025
player-prop market**, and the market calibration gate is **UNAVAILABLE**: the dev DB has 0 NCAAF
`prop_odds_snapshots` (3,526 total, all MLB), and the 2026 props are a live board, not a
timestamped pre-kickoff no-vig archive.

A simulator can be built on this attribution. If the merged attribution on the 2025 holdout
falls below the F1 thresholds, the track stops (section 7).

## 1. Data inventory (measured, 2018-2025)

All counts are read-only from the on-disk Parquet files under `research/fbs/parquet/` (the
SportsDataverse GitHub releases), not from the CFBD API (quota exhausted, HTTP 429). `cfb_schedules`
is the population and division source; `fbs_game=True` is both teams FBS; `fbs_participant=True`
is at least one FBS team. The derived division flags match the published flags exactly in every
season.

### 1.1 Population, regular season

| Season | FBS core (both FBS) | FBS-any (at least one FBS) | FBS vs FCS | FBS vs other non-FBS |
|---|---|---|---|---|
| 2018 | 733 | 845 | 112 | 0 |
| 2019 | 734 | 848 | 114 | 0 |
| 2020 | 508 | 542 | 34 | 0 |
| 2021 | 732 | 849 | 117 | 0 |
| 2022 | 734 | 854 | 120 | 0 |
| 2023 | 750 | 868 | 118 | 0 |
| 2024 | 753 | 874 | 121 | 0 |
| 2025 | 762 | 888 | 126 | 0 |
| **Total** | **5,706** | **6,568** | **862** | **0** |

FBS-vs-FCS is 862/6,568 = 13.1% of the FBS-any population. There are no FBS-vs-Division-II/III
regular games in this window. 2020 is the COVID season (508 core games; 542 FBS-any; 34 FBS-vs-FCS)
and is retained with a season effect, not treated as a normal design season.

### 1.2 Play-by-play row counts and FBS coverage

Rows are the file row counts. `FBS-any` is the count of distinct games in the file that are in the
FBS-any regular population for that season.

| Season | cfbfastR rows | cfbfastR FBS-any | ESPN rows | ESPN FBS-any | NCAA cfbfastR rows | NCAA FBS-any | NCAA raw rows | Union FBS-any |
|---|---|---|---|---|---|---|---|---|
| 2018 | 160,514 | 842 | 158,400 | 842 | 299,128 | 823 | 338,681 | 845 |
| 2019 | 159,920 | 847 | 157,011 | 847 | 309,965 | 836 | 350,351 | 848 |
| 2020 | 99,955 | 523 | 100,459 | 537 | 159,364 | 522 | 179,924 | 542 |
| 2021 | 163,444 | 849 | 147,512 | 801 | 280,420 | 796 | 320,319 | 849 |
| 2022 | 252,307 | 854 | 149,745 | 815 | 296,782 | 824 | 339,599 | 854 |
| 2023 | 254,090 | 868 | 153,945 | 860 | 285,304 | 828 | 326,932 | 868 |
| 2024 | 277,048 | 873 | 163,567 | 855 | 305,266 | 846 | 349,065 | 873 |
| 2025 | 293,200 | 888 | 166,371 | 887 | 309,797 | 872 | 353,879 | 888 |
| **Total** | **1,660,478** | **6,544** | **1,197,010** | **6,444** | **2,246,026** | **6,347** | **2,558,750** | **6,567** |

Source coverage of the 6,568 FBS-any games: cfbfastR 6,544 (99.63%), ESPN 6,444 (98.11%), NCAA
cfbfastR 6,347 (96.63%), **union 6,567 (99.985%)**. The one game with no PBP from any source is
`401640992`, 2024 week 5, App State vs Liberty (both FBS). The simulator excludes that game from
the play-level fit and reports it as a one-game gap; it is not imputed.

The union is the relevant number for a simulator: it can select a source per game. No single
source is complete: ESPN is missing 124 FBS-any games (48 in 2021, 39 in 2022), NCAA cfbfastR 221,
cfbfastR 24. The simulator's source hierarchy is in Appendix B.

### 1.3 Player attribution on the relevant plays

Conditional attribution, not all-play attribution. A passer is required on pass attempts, a
receiver on completions, a rusher on rushes, a target on pass attempts. Ranges are across
2018-2025; the 2025 holdout is shown separately in the text.

| Source | Passer (pass att.) | Receiver (completions) | Rusher (rushes) | Target (pass att.) |
|---|---|---|---|---|
| cfbfastR | 98.03-99.99% | 98.97-100% | 55.98-100% by name; 94.65% by ID in 2025 | 74.16-97.67% |
| ESPN PBP | 99.94-100% | 99.61-99.99% | 98.44-100% | 68.65-94.79% |
| NCAA cfbfastR | 99.75-99.99% | 99.71-99.99% | 98.12-100% | **100%** |
| NCAA raw | 99.76-100% | 99.71-99.99% | 99.89-100% | no target flag |
| ESPN participants joined to PBP (2024) | 99.27% | 99.93% | 99.91% | n/a |

The 2025 holdout values are: cfbfastR passer 98.03%, receiver 99.69%, rusher 55.98% by name /
94.65% by ID, target 97.67%; ESPN 99.997% / 99.91% / 99.33% / 94.79%; NCAA cfbfastR 99.987% /
99.994% / 98.12% / 100%. The cfbfastR 2025 rusher *name* column is the one severe outlier; the
`rush_player_id` and ESPN/NCAA columns cover it. The target gap on incompletions in cfbfastR/ESPN
is why NCAA cfbfastR is the primary target source.

### 1.4 Participation, rosters and box scores

| Season | Participant rows | Participant FBS-any games | Game-roster rows | Roster FBS-any games | Player-box rows | Player-box FBS-any games | Season roster FBS / FCS |
|---|---|---|---|---|---|---|---|
| 2018 | 148,007 | 845 | 198,633 | 834 | 40,131 | 845 | 15,463 / 8,638 |
| 2019 | 146,588 | 848 | 202,692 | 846 | 39,436 | 848 | 15,453 / 8,776 |
| 2020 | 94,204 | 542 | 131,518 | 542 | 25,715 | 542 | 15,149 / 1,798 |
| 2021 | 143,829 | 849 | 213,086 | 849 | 44,043 | 849 | 16,445 / 10,401 |
| 2022 | 145,684 | 853 | 211,705 | 854 | 40,598 | 854 | 16,048 / 10,367 |
| 2023 | 143,798 | 868 | 216,281 | 868 | 57,239 | 868 | 15,954 / 10,421 |
| 2024 | 151,764 | 873 | 231,077 | 873 | 78,993 | 873 | 16,234 / 11,243 |
| 2025 | 154,815 | 888 | 214,432 | 875 | 80,498 | 888 | 15,618 / 10,709 |

- **Participants** (`espn_cfb_play_participants`) are one row per play with the key roles
  (passer, rusher, receiver, tackler, kicker, etc.) and player IDs. 1,128,689 rows 2018-2025;
  6,566 of 6,568 FBS-any games (2022 and 2024 each miss one). In 2024, 149,706 of 151,764
  participant rows join to the ESPN PBP `(game_id, play_id)`; conditional IDs are 99.27% passer,
  99.93% receiver, 99.91% rusher. This is key-role participation, **not** a full 11-player snap
  count.
- **Game rosters** (`espn_cfb_game_rosters`) are one row per athlete per game. 1,619,424 rows;
  6,541 of 6,568 FBS-any games (27 missing, mostly 2018 and 2025). The `starter` flag is **all
  False in 2018-2024** (0 of 231,077 rows in 2024); in 2025 only 17,616 of 214,432 rows are True.
  `did_not_play` is **never True** in 2018-2025. The starter/DNP fields therefore cannot be the
  playing-time ground truth.
- **Player box** (`espn_cfb_player_box`) is the complete box-score target: 406,653 rows, 10
  categories, 6,567 of 6,568 FBS-any games (2024 misses the same game as the PBP gap). It covers
  passing, rushing, receiving, fumbles, interceptions, kicking, punting and returns.
- **Season rosters** (`espn_cfb_rosters`) are 126,364 FBS rows and 72,353 FCS rows 2018-2025, with
  position (22-24 distinct position values per season); 2020 FCS is 1,798 rows because of the
  COVID season.
- **NCAA player stats** (`ncaa_mfb_player_stats`) has only 8 columns in 2018-2019 (identity and
  category, no stat values), and 28-50 columns from 2020. It is a secondary box check from 2020,
  not a primary source for 2018-2019.

### 1.5 Market data

- **Game-level totals/spreads** (`espn_cfb_betting`): FBS-any games with a spread/total are
  112/845 (2018), 113/848 (2019), 34/542 (2020), 118/849 (2021), 121/854 (2022), 839/868 (2023),
  874/874 (2024), 888/888 (2025). Complete only in 2024-2025, near-complete in 2023, and 6-14% in
  2018-2022. The team-total market gate is therefore 2023-2025 plus 2026; 2018-2022 use actual
  totals only.
- **Player props**: as of **2026-10-19T23:46:51Z** (latest prop `captured_at`
  `2026-10-19T23:36:04Z`), the dev DB has **2026-only** NCAAF props: **87,286** prop rows,
  **366** distinct `prop_games` carrying props (424 `prop_games` rows in the league),
  **1,289** distinct players, 2026-08-29 to 2026-10-24. There are **27,391**
  `(game, player, market, line, captured_at)` groups and **27,387** have both over and under
  prices, so a board no-vig probability is computable from the live rows. **64,416** NCAAF
  `prop_results` rows exist. There are **0 NCAAF rows in `prop_odds_snapshots`**; the 3,526
  snapshot rows are all MLB, so there is **no timestamped pre-kickoff no-vig archive**; G3 is
  declared UNAVAILABLE, not run. The DB is live-ingesting week 8; these counts drift and are
  **not reproducible to the row**. There is no 2018-2025 player-prop market in the archive.
- The market is a **benchmark, not a training input**. A market-conditioned variant may be run
  as a secondary, labelled market-derived diagnostic; it is not the primary model, it is not the
  G3 gate (which is unavailable), and it cannot be used to claim an own-data edge.

### 1.6 Gaps as numbers

1. **One FBS game with no PBP**: `401640992`, 2024 week 5, App State vs Liberty. Excluded from the
   play-level fit; no imputation.
2. **cfbfastR 2025 rusher name**: 55.98% on rushes (94.65% via `rush_player_id`). The name column
   is not used alone; the ID/ESPN/NCAA sources cover it.
3. **Target attribution on incompletions**: cfbfastR 74.16% (2024) / 97.67% (2025); ESPN 68.65%
   (2024) / 94.79% (2025); NCAA cfbfastR 100%. NCAA cfbfastR is the primary target source.
4. **Starter/DNP**: `starter` True 0/231,077 in 2024 and 17,616/214,432 in 2025; `did_not_play`
   True 0 in 2018-2025. Not usable as the playing-time ground truth.
5. **Participation depth**: 6,566/6,568 FBS-any games, key roles only; 98.6% of 2024 participant
   rows join to ESPN PBP. No full 11-player snap counts.
6. **No historical player-prop market**: as of 2026-10-19T23:46:51Z, 2026 only, **87,286** props /
   **366** `prop_games` carrying props (424 `prop_games` rows) / **1,289** players; 27,391
   groups, 27,387 two-sided; 64,416 `prop_results`; **0** NCAAF `prop_odds_snapshots` (3,526
   total, all MLB). The DB is live-ingesting and these counts are not row-reproducible.
7. **Game-level lines sparse 2018-2022**: 112/113/34/118/121 FBS-any games with a spread/total vs
   845/848/542/849/854; complete 2024-2025 (874/874, 888/888); 839/868 in 2023.
8. **NCAA player stats 2018-2019**: 8 columns, no stat values; the ESPN player box is the primary
   box for those two seasons.
9. **2020**: 508 FBS core / 542 FBS-any / 34 FBS-vs-FCS, plus 1,798 FCS roster rows. Retained with
   a season effect; not a design season.
10. **2026**: reserved. The 2026 PBP/box files exist, but no fit, design choice or gate value uses
    them. The forward test is after the model is frozen.

## 2. Simulation architecture

The model is a five-stage joint simulation. The unit is one real game; each game is simulated
`M = 10,000` times. Every stage is conditioned on the previous stage's sampled state, so the QB's
passing yards, the RB's carries and the WR's targets are draws from the same simulated game, not
independent marginals.

```
team game environment  ->  play distribution  ->  player opportunity allocation
        ->  conditional efficiency  ->  joint box-score matrix  ->  prop P(over) + correlations
```

### Stage A - team game environment

State variables per game and team:

- `P_h, P_a`: expected offensive plays (`pass + rush`; the PBP `pass` flag already includes
  sacks), the pace.
- `r_h, r_a`: expected pass rate on neutral downs, `pass / (pass + rush)` (`pass` includes sacks).
- `s_h, s_a`: expected points per drive (the scoring environment).
- `h`: home-field indicator; `n`: neutral-site indicator; `rest_h, rest_a`; `weather`
  (wind/roof); `opp`: opponent strength; `is_fcs`: FCS opponent flag.

Model: a hierarchical joint prior over `(P, logit(r), log(s))`:

```
P_t       ~ LogNormal(mu_P + a_team_P + b_opp_P + c_hfa + d_rest + e_weather, sigma_P)
logit(r_t)~ Normal(mu_r + a_team_r + b_opp_pass + c_game, sigma_r)
log(s_t)  ~ Normal(mu_s + a_team_s + b_opp_def + c_hfa + d_weather, sigma_s)
```

The team effects `(a_team_P, a_team_r, a_team_s)` have a team-level covariance; the game-level
factor `c_game` is shared across pace, pass rate and scoring, which is what makes a fast game
correlate with more plays, more passes and more scoring. Team strength is initialized from the
frozen G2h ratings (no G2h refit); the Phase 5 parameters are new. The market total/spread is not
a primary input; a market-conditioned variant is a secondary, labelled diagnostic.

### Stage B - play distribution

State at play `t`: `S_t = (quarter, clock, down, distance, yardline, score_diff, possession,
timeouts, red_zone, two_minute, garbage_time)`. At each state:

- `p_pass(S_t, E) = logistic(alpha + beta_d*down + beta_dist*distance + beta_sd*score_diff +
  beta_c*clock + beta_y*yardline + beta_r*r_t + beta_g*c_game + beta_opp*opp_pass_def)`.
- `p_run`, `p_sack`, `p_penalty`, `p_punt`, `p_fg`, `p_kneel`, `p_spike` complete the multinomial;
  the special-teams branches fire at the appropriate down/field-position states.
- Pass outcome: `completion ~ Bernoulli(p_comp)`; `yards` from a completion/incomplete/sack/
  interception mixture; `p_int`, `p_sack` conditional on the pass state.
- Run outcome: `yards` from a zero-inflated/empirical rush distribution; `p_fumble`, `p_td`.
- Special teams: punt/FG/kickoff outcomes set field position and points.

The chain advances the clock, downs, yard line and score until the game ends (four quarters plus
overtime). `garbage_time = 1` when `|score_diff| >= 17` and `quarter >= 4` (the threshold is fixed;
14/21 are secondary sensitivity checks, not gates).

### Stage C - player opportunity allocation

At each play the offense has 11 players. The simulator samples the personnel package and the
active 11 from the team's depth chart, then allocates the opportunity:

- `personnel ~ Categorical(pi | down, distance, score_diff, team)` (11/12/21/10).
- `snap_share_p(g) = s0_p * m_g * a_p`, where `s0_p` is the player's baseline share (prior season
  and the player's share in **strictly games before g** — strictly earlier games, same season; no
  in-game or post-game data — Beta prior), `a_p` is availability (0/1), and `m_g` is the
  garbage-time multiplier:
  - `m_g = 1` if `|score_diff| < 17` or `quarter < 4`;
  - `m_g = 1 - delta * min(1, (|score_diff| - 17) / 14)` for `|score_diff| >= 17` and
    `quarter = 4`, with `delta = 0.5` for starters (declared; 0.3/0.7 are secondary sensitivity
    checks). Backups' shares rise so the active 11 sums to 1.
- Pass: `passer` = the QB in the active 11; `target ~ Categorical(target_share_p)` among active
  eligible receivers. Run: `carrier ~ Categorical(carry_share_p)` among active backs/QBs/WRs.
  `target_share_p` and `carry_share_p` are conditional on the baseline share, the personnel, the
  down/distance and the simulated game script (a trailing team passes more; a leading team runs
  more; a blowout reduces starter shares).
- State variables: `active_11`, `personnel`, `passer`, `target`, `carrier`, `snap_share_p`,
  `target_share_p`, `carry_share_p`, `a_p`, `m_g`, `depth_chart_p`, `availability_p`.

### Stage D - conditional efficiency

Given a pass attempt by QB `q` to target `t` at state `S_t`:

- `p_comp = logistic(a_qb + b_target + c_depth + d_pressure + e_opp_pass_def + f_game_state)`.
- `yards_if_comp` = a short/intermediate/deep mixture with player `aDOT`/`YAC` effects;
  `yards_if_incomp = 0`; `yards_if_sack` from the sack-yardage distribution; `p_int = logistic(...)`.

Given a run by RB `r`:

- `yards` = a zero-inflated/empirical distribution conditional on `rb_ypc`, `opp_run_def`,
  `box_count`, `down/distance` and `game_state`; `p_fumble`, `p_td`.

The efficiency parameters are hierarchical: player effects shrunk to positional means, opponent
effects, season effects. The fit sample is 2018-2024; 2025 is the holdout; 2026 is forward only.

### Stage E - joint prop distribution

Each simulation produces a complete box score for every active player and team:
`B[sim, player, stat]` and `T[sim, team, stat]`. The joint distribution is the empirical
distribution of the `M` box scores. It preserves within-player correlations (attempts and yards),
cross-player correlations (QB passing yards and WR receiving yards; RB carries and QB attempts;
team pace and every player), and game-script correlations (blowout -> fewer starter snaps).

For each prop, `P(over) = (1/M) * sum(sim_stat > line)`. The prop probabilities and the
cross-player correlations come from the same matrix; there are no independent marginals. The
output is `S[sim, player, stat]`, `T[sim, team, stat]`, `P(over | prop)`, and the correlation
matrix.

## 3. The substitution problem

College starters sit in blowouts. The model above handles it in three places:

1. **Playing time**: the `snap_share_p(g)` model with the garbage-time multiplier `m_g`. The
   baseline share is a Beta/Dirichlet draw around the player's prior usage; the multiplier reduces
   starter shares when the game is decided; backups' shares rise proportionally. `delta = 0.5`
   is declared before fitting, not tuned on the holdout.
2. **Opportunity allocation**: the target/carry shares are conditional on the simulated game
   state, so a trailing team's WRs see more targets and its RB fewer carries; a leading team's RB
   sees more carries. This is the same game script that moves the QB's attempts.
3. **Availability**: `a_p` is inferred from the game roster and the participation/box. A player
   with a participation or box row is active; a player with a game-roster row and no participation
   and no box row is a DNP candidate. The `starter` and `did_not_play` fields are **not** used as
   the ground truth: `starter` is all False in 2018-2024 and only 17,616 True in 2025;
   `did_not_play` is never True.

Validation:

- **Observed participation**: the fraction of team offensive plays in which a player appears in
  `espn_cfb_play_participants`, by quarter and score margin. This is key-role participation, not
  full snap count; it is the best available 2018-2025 measure.
- **Observed opportunities**: targets/carries/attempts from the player box (and NCAA player stats
  from 2020 as a cross-check).
- **Gate**: the observed starter participation rate in blowouts (`|margin| >= 17`, Q4) must be
  lower than in close games (`|margin| <= 7`); the simulated difference must be inside the
  observed 95% interval. The simulated opportunity distributions must meet the 50%/90% coverage
  bands against the actual box. If the simulator cannot reproduce the observed blowout reduction,
  the substitution model fails.

## 4. FBS-vs-FCS handling

The 862 FBS-vs-FCS regular games (13.1% of the 6,568 FBS-any games) are **retained**, not dropped.
Each game carries `is_fcs = 1`; the FCS opponent strength is a separate hierarchical offset, and
the opponent-strength fit weights FBS-vs-FCS plays at **0.5** (declared before fitting; 0.25/0.75
are secondary sensitivity checks, not gates). The FBS-vs-FCS games count in the team-total and
box gates with the flag, so the simulator is scored on the full FBS-any population. The 5,706
both-FBS games are the core sample and are reported separately.

There are no FBS-vs-Division-II/III regular games in 2018-2025, so FCS is the only non-FBS
opponent class.

## 5. NCAA statistical conventions and prop grading

**Sacks.** Under NCAA accounting, sacks reduce team and QB rushing totals and do not count as
passing yards. The play-by-play has `sack = 1` and `yds_sacked` (negative). The simulated box
computes:

- `team_rush_yards = sum(yds_rushed) + sum(yds_sacked)` (the official team rushing total includes
  sack yardage).
- `qb_rush_yards = sum(yds_rushed by the QB) + sum(yds_sacked by the QB)` (the official QB rushing
  total includes sacks).
- `passing_yards = sum(pass yards on completions)`, excluding `yds_sacked`.
- `pass_attempts`, `completions`, `passing_touchdowns`, `interceptions` exclude sacks and include
  only pass attempts/completions.

The `espn_cfb_player_box` `rushingYards`/`passingYards` and the `ncaa_mfb_player_stats`
`yds_rush`/`pass_yards` are the reference boxes. The simulator's box is compared to both; a
mismatch is counted, not smoothed.

**Prop mapping.** Each market is mapped to the exact box column and tested on the 2025 box (where
the prop settlement does not exist) and on 2026 forward props (where it does). The mapping is:

| Market | Box definition | Trap |
|---|---|---|
| `passing_yards` | passing yards, sacks excluded | laterals/YAC; sack yardage must not leak in |
| `pass_attempts` | pass attempts, sacks excluded | kneels/spikes; two-point attempts |
| `pass_completions` | completions | laterals after catch |
| `passing_touchdowns` | passing TDs | two-point conversions |
| `interceptions_thrown` | INTs thrown | tipped/deflected attribution |
| `rushing_yards` | official rushing yards | QB includes sacks; RB/WR excludes sacks |
| `rush_attempts` | official rush attempts | kneels; scrambles; two-point attempts |
| `rushing_touchdowns` | rushing TDs | two-point conversions |
| `receptions` | receptions | laterals; tipped balls |
| `receiving_yards` | receiving yards | laterals after catch |
| `receiving_touchdowns` | receiving TDs | two-point conversions |
| `targets` | PBP `target` | not an official box stat; source definition varies |
| `total_touchdowns` | rushing + receiving TDs | return TDs; two-point conversions |
| `rushing_receiving_yards` | rushing + receiving yards | the sack convention for the rushing part |
| `passing_rushing_yards` | passing + rushing yards | the sack convention for the rushing part |

Overtime is included in the simulated game and the box. Two-point conversions are tracked
separately; a market that includes them is mapped explicitly. Kneels are rush attempts with
negative yards; spikes are pass attempts with no yardage; both are in the box and the market
mapping. Laterals are credited by the publisher's `yds_receiving`/`yds_rushed` columns, not
re-derived from play text; a play-level/box discrepancy is counted as a reconciliation failure.

The 2026 forward prop source's grading convention is not assumed identical to ESPN/NCAA: the
prereg's G3 compares the simulated P(over) to the source's no-vig line and the source's settled
result. If the source's stat definition differs, the mapping is corrected only by the declared
mapping table, not by fitting on the 2026 outcomes.

## 6. Gates (declared before any fit)

All gates are evaluated on the 2025 holdout for the box/team checks; 2018-2024 is the development
sample; 2026 is forward only and is never used for design. A gate is a pass/fail at the declared
threshold, not a report, and **no gate is evaluated on a bare point estimate**.

### Sampling error (all statistical gates)

Every point estimate in G1 and G2 (and in G3 only if a future pre-kickoff archive exists) is
printed with a **95% percentile interval** from a
**game-clustered bootstrap**: resample whole games with replacement, **2,000 reps, seed
`20261019`**; every PIT/graded row stays nested in its game; for player props the player-game is
nested in the game and the bootstrap resamples **games only** (all player-game rows in a
resampled game travel together). The block key is the ESPN `game_id` (the prop's game id for G3);
the helper is `game_cluster_bootstrap` in the Step 2 code. **Market comparisons are paired on the
identical game/prop set**: report the bootstrap interval of the difference (sim - market), not two
independent point estimates. **Log loss is reported beside Brier everywhere Brier appears** (G1
market, G3); log loss is a reported diagnostic, not a new gate threshold.

**Conservative pass rule (stated once).** A gate PASSES only if the point estimate meets the
threshold AND the interval is consistent with it in the conservative direction:

- for a `<=` bound (bias, CRPS, Brier, mean bias), the interval's **upper** bound must also meet
  the bound;
- for a `>=` bound, the interval's **lower** bound must also meet it;
- for a band (coverage, slope, intercept), the **whole** interval must lie inside the band;
- for `|mean| <= b`, the 95% interval of the signed mean must lie inside `[-b, +b]`.

G4 is deterministic: its "interval" is the `1e-9` reproduction tolerance, not a sampling
interval. No threshold below is changed by this subsection.

### G1 - Team totals

- Population: FBS-any regular games 2018-2024 (development) and 2025 (holdout); 2020 flagged.
- **Bias**: `|mean(sim points) - actual points| <= 0.5` per team; total points bias `<= 1.0`.
  With the game-clustered interval, the signed mean interval must lie inside `[-0.5, +0.5]`
  (total: `[-1.0, +1.0]`).
- **CRPS**: simulated team points vs actual, compared to a baseline normal with the team's
  prior-season mean and the season SD; the simulated CRPS must be `<= baseline + 0.05`, paired on
  the same games; the **upper** bound of the (sim - baseline) interval must be `<= +0.05`.
- **PIT**: 50% central coverage in `[0.45, 0.55]`; 90% in `[0.85, 0.95]`; no more than 2 of the 7
  development seasons outside the 50% band; the 2025 holdout inside the band. The whole 95%
  interval must lie inside each band.
- **Market**: for 2023-2025 and 2026 (where a closing total exists), the simulated P(over) vs the
  no-vig market: Brier `<= market + 0.01`; calibration slope `0.9-1.1`; intercept `+/-0.02`.
  Report the **paired** (sim - market) Brier difference with its interval and **log loss beside
  Brier**; the Brier difference's point and **upper** bound must be `<= +0.01`; the slope and
  intercept intervals must lie inside their bands. The sparse 2018-2022 totals are a secondary
  check, not the gate.

### G2 - Complete player box

- Population: every player-game in the 2025 holdout (and 2026 forward) for the FBS-any games; all
  players with a game-roster or box row, including zeros for inactive/no-stat players. Twelve core
  stats: pass attempts, completions, passing yards, passing TDs, INTs; rush attempts, rushing
  yards, rushing TDs; targets, receptions, receiving yards, receiving TDs.
- **PIT**: 50% coverage `[0.45, 0.55]` and 90% `[0.85, 0.95]` per stat; at least 10 of 12 stats
  within the 50% band; no stat outside `[0.40, 0.60]`. The whole 95% interval must lie inside each
  band.
- **CRPS**: compared to the player's prior-season per-game mean (positional mean for rookies); the
  simulated CRPS `<= baseline + 0.05` for at least 10 of 12 stats, paired on the same player-game
  rows; the **upper** bound of the (sim - baseline) interval must be `<= +0.05`.
- **Opportunities**: simulated targets/carries/attempts 50% coverage `[0.45, 0.55]`; 90%
  `[0.85, 0.95]`; whole interval inside each band.
- **Substitution**: the blowout participation direction and magnitude from section 3 must be
  inside the observed 95% interval; the simulated interval is the game-clustered bootstrap
  interval.
- Sample: at least 10,000 player-games in the 2025 holdout.

### G3 - Market calibration (P(over) vs no-vig) - UNAVAILABLE

- **Status: UNAVAILABLE, not evaluable, not run.** The dev DB has **0** NCAAF rows in
  `prop_odds_snapshots` against **87,286** NCAAF props, **424** `prop_games` rows and **64,416**
  `prop_results`; the **3,526** snapshot rows are all MLB. The 2026 `props` rows (27,387 two-sided
  groups as of 2026-10-19T23:46:51Z) are a live board, not a timestamped pre-kickoff no-vig
  snapshot archive. A no-vig P(over) calibration **cannot be run** from them. This prereg
  therefore makes **no market-calibration claim**; the G3 thresholds below are retained only for a
  future, separately registered pre-kickoff snapshot archive, and are not evaluable here.
- Population (future archive only): 2026 forward props with two-sided pre-kickoff no-vig snapshots;
  the gate requires at least 1,000 props. Core markets: passing yards, rushing yards, receiving
  yards, receptions, rush attempts.
- **No-vig** (future archive only): proportional de-vig from the over/under American odds; market
  P(over) is the benchmark. The gate is calibration, not edge.
- **Calibration** (future archive only): reliability slope `0.9-1.1`, intercept `+/-0.02`; Brier
  `<= market + 0.01` for at least 4 of the 5 core markets; no market mean bias `> 0.05`. Report
  the **paired** (sim - market) Brier difference with its interval and **log loss beside Brier**;
  the Brier difference's point and **upper** bound must be `<= +0.01`; the slope interval inside
  `[0.9, 1.1]`, the intercept interval inside `[-0.02, +0.02]`, the mean-bias interval inside
  `[-0.05, +0.05]`. At least 4 of 5 core markets must pass their Brier bound.
- **Secondary** (future archive only): the paired Brier and log-loss differences (sim - market) are
  reported with intervals for every market; beating the market is not required for calibration,
  but the model must not be materially worse than the market (the `+0.01` bound is the tolerance).
- Because the gate is unavailable now, it is not a Step 2 input and no adoption decision can rest
  on it; F3 states the consequence.

### G4 - Reproduction

- Seed `20261019`; `M = 10,000` simulations per game; a fixed data manifest (`archive-coverage.csv`
  SHA-256s for every Parquet file), fixed code commit, and the exact config.
- A second run must produce the same gate metrics within `1e-9` and the same game/player sample.
  This is the deterministic G4 interval; no bootstrap is used.
- The reproduction command and output paths are in Appendix B.

**Pass rule.** G1, G2 and G4 must pass on the declared samples under the sampling rule above; G3
is **unavailable** and is not a pass, so no adoption decision can rest on market calibration. The
2025 holdout is never used in a fit. 2026 is forward only. If G1, G2 or G4 fails, the simulator is
not adopted; there is no adoption decision in this prereg.

## 7. What would make us stop (falsifier)

F1, F2 and F4 end the Phase 5 track. F3 ends any market-calibration claim and any adoption that
depends on it, but does not stop the team/box/joint work. None is a rescue for another. Each is
stated before any fit.

- **F1 (data).** On the 2025 holdout, merged attribution on the relevant plays falls below **98%**
  for passer, **98%** for rusher, **98%** for receiver on completions, or **95%** for targets. The
  track would be built on missing attribution; stop.
- **F2 (model).** On the 2025 holdout, any core stat's 50% coverage is outside `[0.40, 0.60]`, or
  the team-total CRPS is worse than the baseline by more than `0.10`. The simulator does not
  reproduce the box; stop.
- **F3 (market).** The no-vig prop calibration is **unavailable now**: **0** NCAAF
  `prop_odds_snapshots` (3,526 total, all MLB) against **87,286** props, **424** `prop_games` and
  **64,416** `prop_results`. The 2026 `props` rows are a live board, not a timestamped pre-kickoff
  no-vig archive, so no market-based P(over) calibration can be run. This ends any
  market-calibration claim and any adoption that depends on it; it does not stop the team/box/joint
  work. A future pre-kickoff snapshot archive is a new registration.
- **F4 (joint).** The observed cross-player correlation on the 2025 box (QB passing yards vs WR
  receiving yards; RB carries vs QB pass attempts; team total vs QB passing yards) lies outside
  the simulated 95% interval, or the simulated correlation is not positive. The "joint" claim
  fails; stop.

## 8. What is not done

No simulator has been fit or run. No simulation output, no prop probability, no gate value and no
adoption decision exists. No existing FBS model, gate, production table, scheduler or database is
changed. The only input to this document is read-only Parquet and a read-only dev DB. Step 2 waits
for a go-ahead; this prereg is the deliverable.

## Appendix A - data paths and manifest

Parquet roots (2018-2025, SportsDataverse GitHub releases, on disk since 2026-10-18):

- `research/fbs/parquet/cfbfastR_cfb_pbp/play_by_play_{season}.parquet`
- `research/fbs/parquet/espn_cfb_pbp/play_by_play_{season}.parquet`
- `research/fbs/parquet/ncaa_mfb_pbp_cfbfastr/ncaa_mfb_pbp_cfbfastr_{season}.parquet`
- `research/fbs/parquet/ncaa_mfb_pbp/ncaa_mfb_pbp_{season}.parquet`
- `research/fbs/parquet/espn_cfb_play_participants/play_participants_{season}.parquet`
- `research/fbs/parquet/espn_cfb_game_rosters/game_rosters_{season}.parquet`
- `research/fbs/parquet/espn_cfb_player_box/player_box_{season}.parquet`
- `research/fbs/parquet/espn_cfb_rosters/cfb_rosters_{season}.parquet`
- `research/fbs/parquet/ncaa_mfb_player_stats/ncaa_mfb_player_stats_{season}.parquet`
- `research/fbs/parquet/cfb_schedules/cfb_schedules_{season}.parquet`
- `research/fbs/parquet/espn_cfb_betting/betting_{season}.parquet`

The file-level SHA-256 manifest is `research/fbs/archive-coverage.csv` (one row per release,
season and file, with `rows`, `bytes`, `columns`, `sha256`, `downloaded_at`). The dev DB is
`/root/legendarypicks/backend/data/picks.dev.db`, opened `mode=ro`; only the 2026 prop counts were
read from it.

2026 files exist and are reserved. They are not used for any design choice, fit or gate value.

## Appendix B - source hierarchy, definitions, reproduction

**Source hierarchy (per game):**

1. NCAA `cfbfastR` for targets and rusher attribution (100% / 98.12-100%) and for the NCAA-style
   play flags; join by `espn_game_id`.
2. ESPN PBP for player IDs (passer/rusher/receiver 99.3-100% conditional) and for the ESPN box
   identity; join by `game_id`.
3. `cfbfastR` for EPA/context and the game script; use `rush_player_id` (94.65% in 2025) when the
   rusher *name* is missing, and do not use its 2025 rusher name alone.
4. `espn_cfb_play_participants` for key-role participation, joined to ESPN PBP on
   `(game_id, play_id)`; 98.6% of 2024 rows join; conditional IDs 99.3-99.9%.
5. `espn_cfb_player_box` for the complete box target; `ncaa_mfb_player_stats` as a secondary check
   from 2020.
6. `espn_cfb_game_rosters` for availability, with the starter/DNP caveat; `espn_cfb_rosters` for
   season roster identity.

**Definitions:** `pace = pass + rush` per team-game (the PBP `pass` flag already includes sacks,
so sacks are not added twice); `pass_rate = pass / (pass + rush)`; play-level exclusions are
penalties, timeouts, period markers, coin toss, two-point attempts (tracked separately), and
kneels/spikes (tracked separately). The PBP flags are disjoint: `pass & rush = 0`,
`pass & sack = sack`, `pass_attempt & sack = 0`, `rush & sack = 0` on 2024 in cfbfastR, ESPN and
NCAA cfbfastR. `FBS core` = both
teams FBS; `FBS-any` = at least one FBS; `is_fcs` = exactly one team FBS and the other FCS.
`garbage_time = |score_diff| >= 17 and quarter >= 4`. The 2024 game `401640992` is excluded from
the play-level sample and reported as the one-game gap.

**Reproduction (Step 2, not run here):**

```
python backend/fbs_phase5_sim.py --season 2025 --seed 20261019 --sims 10000 \
  --data research/fbs/parquet --out research/fbs/phase5/2025/
```

The script does not exist yet; Step 2 creates it after this prereg is accepted. A reproduction
check reruns the same command and compares the gate metrics and the game/player samples within
`1e-9`.
