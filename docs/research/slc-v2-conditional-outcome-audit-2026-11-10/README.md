# SLC-v2 conditional outcome audit

Date: 2026-11-10
Scope: Offline scoring of historical plays, frozen SLC model tables, and saved BUF–MIN D1 summaries. No simulations or new seeds were run. The original 10K run was not changed.

## Findings

### Historical outcome probabilities

On the clean 2025 walk-forward test (272 games, 33,490 scored plays), the league situation-cell baseline outscored the offense, defense, and offense×defense event adjustments. Log loss / Brier score were 0.5404 / 0.2984 for the league baseline, 0.5456 / 0.2996 offense-only, 0.5462 / 0.3006 defense-only, and 0.5517 / 0.3020 matchup. Lower is better. The tested team multipliers therefore did not improve event probabilities overall.

Conditional yardage is sampled from historical situation/event cells. On 2025, SLC's conditional CRPS was 4.650 yards for completions (10,909 plays), 2.607 for runs (12,715), and 2.015 for sacks (1,130). Offense-only and defense-only team yardage baselines were slightly worse overall. Mean yardage bias was near zero for completions and runs; sack bias was −0.261 yards. Team-level adjustments to the yardage distribution did not improve overall scores.

Third-down line-to-gain probability was close by distance, with some calibration error. On 2025, observed versus predicted conversion proxies were 0.626 vs 0.656 at 1–2 yards (n=1,359), 0.457 vs 0.468 at 3–5 (n=1,570), 0.330 vs 0.357 at 6–9 (n=1,726), and 0.202 vs 0.191 at 10+ (n=1,647). These are conditional play-level gain proxies: the observed run/pass intent is held fixed, touchdowns count as a gain, and this is not a full-drive conversion rate. Penalty first downs are not represented.

### Fourth-down decisions

On 3,580 historical 2025 fourth-down decisions, SLC situation-cell probabilities scored 0.4892 log loss / 0.2829 Brier. Offense-only team rates scored 0.4855 / 0.2803, defense-only 0.4913 / 0.2835, and a flat league rate 0.8799 / 0.5440. Situation and team information are much better than a flat rate; offense-only was slightly better overall than the current situation-cell policy. Simulated go-for-it counts must be read together with the fourth-down situations reached.

### Sacks and turnovers

The 2025 overall sack rate was well calibrated: 6.594% observed, 6.580% predicted by the matchup model, and 6.544% by the league model. Team matchup gaps remain. Minnesota's offense had a 10.86% observed sack rate (n=525), versus 7.08% predicted; Buffalo's defense allowed 9.67% (n=486), versus 7.03% predicted. Buffalo offense was 7.10% observed vs 5.68% predicted. These are targeted team estimates and should be read with sample sizes; they show that a good league-wide rate can hide important matchup errors.

The saved 9,991-game D1 BUF–MIN run predicted Minnesota at 1.476 sacks/game and 3.67% sack rate per dropback; Buffalo was 0.721 sacks/game and 1.80%. The pregame 2026 Weeks 1–8 data had Minnesota at 9.01% sacks per dropback on offense and 10.64% sacks forced on defense; Buffalo was 5.39% and 5.08%, respectively. This points to Minnesota-specific sack suppression in the saved run. Saved box scores show 284 Minnesota games with 3+ turnovers and 64 Buffalo games with 4+ sacks.

The run did not enable `restore_sack_mass`. The frozen correction uses 115 cells (40 shrunk), pooled support of 76,195 dropbacks and 5,267 sacks; support is uneven, including very sparse cells. This audit does not establish that the correction is calibrated.

### Saved fourth-down mix

The saved run averages 1.885 Minnesota and 1.937 Buffalo go-for-it decisions per game. Pregame Weeks 1–8 averages were 0.857 for Minnesota and 1.143 for Buffalo. Total Minnesota fourth-down decisions were similar (about 7.42 simulated vs 7.86 actual per game), but the simulated situation mix had more fourth-and-short situations and fewer 7+ yard situations. The observed comparison covers only seven games, so it is a lead for follow-up, not proof that policy alone caused the difference. See `sim-fourth-down-histogram.json` and `saved-simulation-summary.json`.

### Penalties and 2026 data limitation

The frozen 2025 source contains 3,461 penalty-tagged plays among 46,452; 973 have a first-down-penalty flag. The 2026 Weeks 1–8 source contains 1,765 among 21,191, with 486 first-down-penalty flags. The 2026 database has NULL penalty fields in all 21,018 rows, despite flags in the source parquet. Therefore 2026 is a sensitivity analysis, not primary evidence: tagged penalties could enter the adaptation and the main test scoring. The 2025 test excludes penalty-tagged rows where source flags are present. Late-down failed-series counts in the penalty summary are association proxies, not causal penalty estimates.

## Method and provenance

The event, conditional-yardage, third-down and fourth-down audits use walk-forward training and frozen model code at `09a794f075947ed88973268e9535af6ad85c79d1`. 2025 uses 2022–2024 training data. 2026 uses historical training through 2025 plus current-season evidence available before kickoff minus 90 minutes. The pinned database SHA-256 is `1a775208bc6e38763ef59c38a6cc79bda3636007feb8c6dc44f085f668341daa`; source parquet hashes and row counts are in `penalty-source-summary.json`.

The saved simulation run is source commit `8a5d809ffaec720b3d7b8ddb487f33c55e5d0d0e`, seeds 200001–210000, with 9,991 valid games and 9 errors. It contains per-seed decision summaries and box scores, not ordered play transitions. The audit can report situation/action and box-score rates, but cannot recover exact third-down conversions from this run.

Full row-level and subgroup results are in `conditional-outcome-audit.json` and `sack-context-audit.json`. Reproduction scripts are `audit.py` and `sack-context-audit.py`; the scripts require the pinned fast-host data/code paths recorded in the JSON provenance and are not standalone on another machine.

## Conclusion

The largest supported finding is not a universal failure of yardage or sack rates. Overall event-class matchup reweighting does not improve held-out probabilities, while team-specific conditional yardage baselines do not improve yardage CRPS. The league-wide sack rate is close, but Minnesota-specific sacks are underpredicted in both the offline audit and saved BUF–MIN run. Fourth-down excess is partly entangled with the situations the simulator reaches. Fix the 2026 penalty-field loss before treating current-season walk-forward scores as clean evidence. These audits identify mechanisms to investigate; they do not establish how those errors compound through simulated games.
