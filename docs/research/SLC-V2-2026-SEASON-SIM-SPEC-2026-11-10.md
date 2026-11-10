# SPEC: 2026 NFL full-season simulation on SLC-v2

**Date:** 2026-11-10  
**Status:** Implementation spec only. Not implemented, not adopted, not a published forecast.  
**Target branch:** `slc-v2`  
**Scope:** 2026 regular season from a timestamped cutoff, 14-team playoffs, conference championships, and Super Bowl.  
**Owner decision:** Make a season-level product out of the existing SLC full-game work rather than spending the whole simulation budget on isolated 10,000-seed weekly games.

## 0. Decision and definition of done

Build **SLC-v2 Season Mode**, a reproducible Monte Carlo engine that begins with every 2026 NFL result genuinely final by an explicit `as_of_utc` and simulates **every still-unplayed regular-season matchup, official seeding, and all 13 postseason games**. Each simulated season produces one complete, internally consistent path through a champion, plus team, game, standings, and optionally player-stat distributions aggregated across paths.

The season mode **must use an explicit, versioned SLC-v2 game-outcome interface**. It must not silently relabel the older `backend/nfl_sim.py` ratings simulation as SLC-v2, and it must not reuse one game's fixed pregame snapshot as if future rosters, injury information, tactics, and workloads were known.

The first useful deliverable is **20,000 reproducible season paths from a frozen cutoff using a calibrated, SLC-derived conditional game distribution**, with correct standings/brackets and honest uncertainty. A full play-by-play rollout of every game in every path is a later research mode, **not** a requirement for the first 20K season deliverable. Any shortcut is explicit in the manifest and validated against the complete SLC-v2 engine before it can carry an SLC-v2 label.

The six acceptance outcomes:

1. A run contains every one of the 272 published 2026 regular-season fixtures exactly once, either as a frozen real final or a future simulated outcome. Each team plays 17 regular-season games; byes are not games.
2. Every complete simulated season has exactly 14 playoff entrants, 8 division winners, 2 conference champions, 13 postseason games and 1 Super Bowl champion. The Super Bowl is neutral-site under the official fixture metadata.
3. Played results never change. A hypothetical future game result affects only *later* games in **that same path**, never other paths or the frozen real-world database.
4. Every output identifies model configuration, observation cutoff, code/input hashes, random seed, complete/blocked paths, run mode and source availability assumptions. It can be regenerated exactly.
5. The release gates below pass, including official seeding and playoff/OT rules, numerical conservation, leak tests and multi-season backtests.
6. The product can show playoff/division/seed/bye/conference/Super Bowl odds, projected records, schedule outcomes and **median plus 10–90% bands**, as well as the *shortest empirical interval containing 80% of draws* when the user wants the most frequently occurring range. A missing result appears as unknown, not as invented precision.

## 1. What exists and what does not

| Existing module | Reuse / gap |
|---|---|
| `backend/nfl_sim.py` | Existing regular-season Monte Carlo and aggregate playoff-odds machinery. Its frozen team-ratings/Normal-margin and optional historical score sampler are **baseline implementations**, not the SLC full-game model. It does **not** simulate the postseason through a champion. Its default `scores="placeholder"` produces non-integer, non-football scores; do not use it for a public score forecast. |
| `backend/nfl_standings.py` and `backend/nfl_seeding.py` | Reuse standings and NFL division/wild-card seeding, after reviewing full 2026 tiebreaker coverage. The current prior spec simplified later points-based tiebreaks; never skip unresolved official steps and call the result exact. |
| `backend/nfl_bracket_check.py` | Existing historical final-seed reconciliation; extend tests to 2026 and playoff matchups. |
| `scripts/nfl_sequence/simulate_pregame_batch.py` | SLC batch engine, `--slc-v2`, per-seed box scores, scores, player categories, source hash/provenance, resume and export support. This is **one game at a time**, not an entire season. |
| `scripts/nfl_sequence/slc_engine.py` / `slc_config.py` | Shared game configuration, season adaptation, lineup/participation options and artifact identity. Current season adaptation reads real games prior to a target; it does not yet consume a simulated future path's own history. |
| `scripts/nfl_sequence/pregame_snapshot.py` and availability adapters | Frozen cutoff-safe pregame snapshots, full-depth roster provenance and availability timing. They do not establish actual future-week rosters or injury designations. |
| `scripts/nfl_sequence/playbook_prior.py` | Prior-season playbook signal for pass depth, pass location and run gap, off by default outside the selected stack. It does not by itself learn a new playbook from simulated 2026 games. |
| `scripts/nfl_sequence/game_state.py` | Full-game state transitions and regular-season overtime work, including a 600-second OT period. **Postseason OT must be implemented/validated separately.** |
| `scripts/nfl_sequence/slc_outputs.py` | Player/team per-seed records and statistical aggregates; skill-position lineup snaps are not a complete 22-player lineup. |
| Experimental workload D1/C inputs | Research arms, **not** presumed adopted. V1.5 has outperformed V2 on most audited player-stat errors; better snap-share realism alone is not a gate for promoting D1/V2. |

**Do not conflate:** SLC V1/V1.5/V2 are full-game model stacks; the historical `nfl_ratings` v1/v2 naming refers to separate team-rating experiments. Existing player-prop Brier evaluations are also separate, not a measured SLC-v2 seasonal prop Brier score.

### Non-goals for the first merge

Do not build a new 3D game engine, assume full tracking, simulate a 2027 schedule, infer an unpublished future inactives list, promise accurate fantasy/prop prices before grading, alter `dev`/production forecasts, or demand perfect implementation of every NFL edge rule before the bounded research deliverable. A skipped/blocked rule path must, however, be visible and **must never be quietly counted as a valid season**.

## 2. 2026 input contract: one immutable world at the cutoff

The entry point takes `season=2026` and an exact timezone-qualified `as_of_utc`, preferably the latest frozen weekly roster/schedule capture, not merely a week number. Use published `nfl_schedule` IDs, `game_type`, home/away, kickoff UTC, location, neutral flag and league mapping. The 2026 fixture census must contain 272 unique regular-season games and 32 teams; compare to a captured official schedule. Preserve reschedules and international games. Order future games by verified kickoff instant, then stable game ID; a same-time group sees only real data available **strictly before** its cutoff. Handle same-week results by actual completion/availability time, not by `week <= target_week`.

**Frozen actuals:** Include an actual score only if status is final and the final result was available by the cutoff. Store the score, final-status source and source availability time. A final played *after* the requested historical cutoff is **not** an input. Unscored older fixtures are neither silently treated as upcoming nor guessed; fail the completeness check or explicitly mark the run incomplete with its exact missing IDs.

**Pre-event sources:** Hash and pin schedule version, depth chart, full-depth roster, availability snapshots, injury evidence, 2022–2025 reference pools, 2026 observed plays, SLC-v2 playcall artifact, lineup/participation fields, current-season snap-count table and kick tables. Distinguish (a) source publication time, (b) ingestion time and (c) the asserted cutoff. If publication time is missing, label it unverified/exploratory rather than treating `date_modified` as proof of earlier availability.

**Availability rule at known upcoming kickoff:** Before official inactives, Out/Doubtful excluded, Questionable included, with the existing conditional three-consecutive-practices-DNP workload reduction capped at 20% where an eligible report supports it. Freeze each rule and its provenance. At future hypothetical weeks, **do not fabricate Questionable/Out, game-day inactives, trades, QB announcements or medical recoveries**. Continue from the last cutoff-known eligible roster and model future availability uncertainty only in a separately calibrated and labelled scenario arm. Provide conservative flags/intervals for unknown lineup-dependent player outputs.

**Identity:** Validate published team code translations and GSIS/LP player IDs before simulation. A simulated player cannot generate a target, carry, snap or stat if the pinned roster state marks them ineligible. Missing player identity does not become the nearest depth-chart name.

## 3. State propagated within each simulated season

A full-season path is a chronological Markov-style rollout with an explicit state, **not** 100+ independent fixed game picks.

Suggested immutable base + copy-on-path mutable state:

- `frozen_world`: cutoff, actual results, schedule and known eligibility; hashes never change during a run.
- `season_path`: path ID, RNG root, ordered simulated game outcomes, regular-season W/L/T and points, opponent/tiebreak ledgers, postseason bracket and eventual champion.
- `team_state[team]`: recency-weighted offense/defense strength, strategy tendencies by down/distance/score, run/pass and situation mix, game/drive scoring residuals, rest and schedule context, and a **within-path** past-results ledger.
- `player_state[id]`: eligibility assumption, role/depth, prior and within-path snap/carry/target exposures, usage posterior/confidence and workload load history. Future injuries are unknown in the base case.
- `playbook_state[team]`: observed historical concepts and optional within-path discoveries/opponent response. Never rewrite real historical evidence with synthetic plays without an explicit simulation-evidence tag.

After game `g`: append its valid outcome to this path, update both teams' standings and opponent ledgers, update any model-specific latent state through a versioned `apply_simulated_game` adapter, and then simulate `g+1`. A Week 15 opponent adjustment may see a simulated Week 13 game *from its own path*; it may not see actual Week 15 data, a different path or the evaluated game itself.

**Critical integration task:** `slc_engine.load_reference`/`season_layers.Evidence.for_target` and current participation snap updates are built around cutoff-safe *observed* inputs. Introduce a separate typed in-memory synthetic-context adapter; do **not** insert synthetic games into `picks.dev.db` or re-query the real DB with a future `as_of` and mistake later real results for simulated knowledge. Distinguish observed-vs-synthetic exposure weights. Use an adaptation shrinkage `N0` and decay frozen before backtest; research it against a no-update control.

Two defensible modes must coexist:

- `frozen`: SLC-derived matchups and real-world priors frozen at run cutoff; only standings, bracket and mandatory schedule variables change.
- `path_adaptive`: future simulated results, role shares, tactical tendencies and latent team strength update later game distributions in that path. This is a new model requiring its own tests, not an unlabelled default.

Add a third **counterfactual** switch for a specific proposed injury, quarterback, player role or playbook change, never as if it were published fact.

## 4. Game outcome interface and computational plan

**Do not call 10K full game seeds for every future matchup in each of 20K seasons.** That multiplies work unnecessarily and misses the benefit of coherent, per-path updates. Benchmark actual cost before choosing path count.

Define a small shared contract:

    GameContext = {
      game_id, season, stage, kickoff_utc, home, away, neutral,
      as_of_utc, path_id, freeze_hashes, roster_assumptions,
      team_state, player_state, model_arm
    }
    GameOutcome = {
      game_id, status, valid_complete, home_score, away_score,
      winner_or_tie, regulation_and_overtime, team_stats,
      optional_player_stats, state_update_sufficient_stats,
      seed, input_hashes, blocker, capability_limitations
    }

A `GameOutcome` represents a **legal final score or a named failure**, not a partial state smuggled into the standings. Keep completed *regular-season ties*, which count 0.5 win/0.5 loss, separate from incomplete/guarded seeds. Preserve player-game accounting and each team's drive/score totals when the result was obtained from full SLC. Never promote sampled participation appearances to fully measured snap counts.

### Explicit execution modes

**Mode A: `baseline_ratings` (control).** Run the existing season algorithm with its historical score sampler, not the placeholder score option. Complete the postseason wrapper for a genuine like-for-like control. Label output `ratings_history_baseline`, never SLC-v2. This gives a working 20K season/bracket path before the SLC kernel is ready.

**Mode B: `slc_kernel_frozen` (first SLC deliverable).** Using the pinned SLC-v2 implementation, generate and validate **conditional matchup sample banks** for all future known regular-season fixtures plus a reusable conditional interface for postseason pairings not yet known. Condition on home/neutral location, team strength/rest, plausible score-state, opponent, and any context the game engine demonstrably supports. Store each bank's finite seed coverage and blocked reasons. Fit/reweight or select only in supported context cells; if the path's context is outside trained coverage, fail the cell rather than silently serving a default. Distinguish empirical resampling from a newly trained surrogate, and validate both against held-out full-engine samples. Common-path latent team-strength uncertainty or a calibrated joint mechanism must prevent misleading independence/underdispersion across weeks. Report the exact limits of `frozen`: it does not claim that synthetic weekly workloads affect future games.

**Mode C: `slc_path_adaptive` (research gate after Mode B).** Supply the path state to a conditional game predictor and propagate modeled team/player adaptations. One of: (1) direct full SLC game draws for selected paths; (2) a validated conditional emulator whose inputs include all changed state; or (3) stratified conditional sample banks proven to represent the needed update axes. A bank computed from a fixed Week 10 roster is not a valid surrogate for arbitrary Week 17 injury states. If that fidelity is unavailable, keep the arm research-only rather than pretending the path has adapted.

**Mode D: `slc_full_trace` (audit).** Run a smaller, configurable number of full play-by-play end-to-end paths, retaining per-play traces. Use for causal realism, roster/drive conservation and Gridiron Physics playback, not as the only means of producing 20K season probabilities. Do not claim 20K full-trace paths until measured compute and storage support it.

Use common random numbers/paired seeds to compare frozen vs adaptive, V1.5 vs V2 and optional D1. Keep independent, stable RNG streams for path season shocks, game simulation, roster-scenario uncertainty and postseason coin tosses; scheduling or parallel worker order must not change results.

### Promotion discipline

V1.5 is the empirical benchmark to beat for player-stat performance. V2 lineup/snap improvements and experimental D1 are not sufficient evidence. Before selecting the production SLC kernel, show paired results for score-bin calibration, team-score CRPS/MAE, winner Brier/log loss, player-stat MAE/CRPS, failure coverage and resource use; do not invent a V1/V1.5/V2 prop Brier result.

## 5. Regular season, standings and tiebreakers

Every path starts from frozen actual games and plays the remaining 2026 fixtures by published kickoff. At the end build W/L/T, conference, division, head-to-head, common-opponent, strength-of-victory, strength-of-schedule and net points/TD facts **from the entire completed path's game ledger**. Half-wins from ties are for standings; do not change score results to fabricate a winner.

Use the existing `nfl_standings`/`nfl_seeding` implementations if they reproduce official outcomes, but **audit all steps against the 2026 NFL tiebreaking procedure**. The published order includes points-based ranking, net points and net TD steps before coin toss. Do not treat an omitted step as a deterministic tie. Multi-team division ties and wild-card division reductions must be implemented exactly, with restarts after elimination. Record the deciding tiebreak step and any genuine coin toss. Do not infer conference/division metadata from team-name strings.

NFL 2026 playoff format: four division winners per conference seeded 1–4; three wild cards seeded 5–7; only seed 1 receives a first-round bye. The 14 playoff-team probabilities must sum correctly (subject only to disclosed failed-path coverage).

## 6. Postseason bracket to the Super Bowl

Per complete season path, dynamically create **13 games**:

| Round | Games | Matchup/rule |
|---|---:|---|
| Wild Card | 6 | In each conference: 2 hosts 7, 3 hosts 6, 4 hosts 5; seed 1 has a bye. |
| Divisional | 4 | Conference seed 1 hosts the **lowest surviving seed**; other two survivors meet with the higher seed hosting. Re-seed after Wild Card, not a fixed bracket. |
| Conference Championship | 2 | Higher surviving seed hosts. |
| Super Bowl | 1 | AFC champion vs NFC champion on a **neutral field**, with published game/venue metadata when available. |

Set rest days, travel and venue from actual published dates when known; if future kickoff times are not published at the cutoff, apply a **declared schedule-assumption policy** and mark this metadata as assumed. Do not assert exact dates or weather that were not published. A postseason simulator must handle unfamiliar pairings; it cannot be limited to a bank of scheduled regular-season games.

**Postseason overtime is not regular-season overtime.** A postseason game must have a winner, with 15-minute overtime periods continuing as necessary and the relevant possession-opportunity provisions under Rule 16. The existing `game_state.py` regular-season 600-second OT behavior is **not** a legal playoff fallback. Implement a postseason mode with rule-checked possession and timing transitions; until it passes, an OT playoff path is **blocked**, not decided by a coin toss or invented score. Regular-season games may finish tied under their distinct OT rules. Validate against the [official 2026 rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook).

Derived postseason data per path: seven seeds per conference, byes, winning games by round, conference champions, Super Bowl matchup, winner and championship score. For matchups/rounds with unmodelled game-state capability, preserve unsupported-rule evidence and reduce valid-path coverage rather than concealing it.

## 7. Public and research outputs

Write one versioned run directory:

    runs/nfl/season/2026/<run_id>/
      manifest.json
      schedule_at_cutoff.json
      frozen_actuals.json
      seed_coverage.json
      seasons.jsonl.gz                 # one record per COMPLETE/blocked path
      games.jsonl.gz                   # optional normalized path/game rows
      team_summary.json
      matchup_summary.json
      playoff_bracket_summary.json
      model_comparison.json
      audit.json

These are **proposed paths and schemas**, not existing commands. The run registry and any externally served outputs are append-only; a later run cannot overwrite an earlier published cutoff.

Minimum team summary:

- P(playoffs), P(division), P(seed 1–7), P(first-round bye), P(win Wild Card), P(reach divisional), P(reach conference championship), P(win conference), P(reach Super Bowl), P(win Super Bowl).
- Regular-season wins mean/median/p10/p90 and projected W-L-T; finish-position probabilities and division/conference ranks.
- Team points-for and against distributions with median, p10/p90, shortest 80%-mass interval, and separately **P(team scores under 17)** and **P(team scores over 27)** for each future game.
- Per-game winner, tie (regular season), spread/total and score-band probabilities only from supported outputs; effective samples and Monte Carlo error, with no unvalidated postseason price implied.
- Change from previous **timestamped published run** when comparable, including explicit model-version/cutoff differences. Do not attribute a change to a game without an actual paired/marginal attribution experiment.

Research-only player outputs: per-game and remaining-season totals for passing attempts/yards/TD, rush attempts/yards/TD, targets/receptions/yards/TD and fantasy point distributions using published scoring rules. Track snap/carry/target share, availability assumptions and role confidence. Omit or flag any full-season player distribution whose future opportunity assumptions are not validated. SLC's generated stat line is **not** automatically a calibrated prop probability.

A user-facing path explorer can choose one seeded season and traverse its game list, bracket and selected per-play SLC traces. Keep it compatible with the low-fidelity 2D replay contract; do not make visual playback a prerequisite for probability calculations.

## 8. Leakage, quality and evidence rules

**Cutoff wall:** A run as of 2026-11-10 must not read the outcome of any later real game, even if today's database contains it when the same cutoff is replayed in December. All query adapters enforce `source_available_at <= as_of_utc` and exclude future versions. For staged future games, draw from the path's synthetic ledger, not real future data. Explicitly test re-running an old snapshot with a database that has subsequently gained new results: byte-identical forecasts expected.

**Existing SLC issues remain blockers to public certainty:** wrong tails for low/high scoring teams (especially under 17 and over 27), fourth-down decision overshoot, kicker/blocked-kick states, some clock and OT/field-goal transitions, player identity, and role/workload allocation. A season Monte Carlo wrapper **magnifies**, not fixes, systematic score or workload error. Continue the bounded game-level legality and score-distribution audits alongside the season simulator.

**No fake “valid” filter:** Count requested, completed, tied, blocked and failed games/seasons separately. Failed paths may not be silently removed then probabilities rescaled to 100%. A fail-closed path has a typed error and enough manifest detail to reproduce the problem. If an explicitly separate fallback baseline completes a blocked path, it must be labelled `mixed_model_fallback`; do not include it in a pure SLC-v2 estimate. Show coverage and any incomplete-run disclaimer.

**No unearned precision:** Show empirical distributions, effective sample counts, calibration and uncertainty. A most-common 80% band is a **shortest empirical coverage interval**, not necessarily the same as a central p10–p90 interval. Disclose multimodal outcomes where a single interval obscures multiple clusters.

## 9. Evaluation plan and launch gates

### Test fixtures and invariants (TDD before implementation)

Create `scripts/nfl_sequence/test_season_sim_2026.py` and focused tests for the bracket, provenance, kernel and reporting modules. These are proposed new test paths.

| Test | Exact expected behavior |
|---|---|
| `test_2026_schedule_census` | 272 regular-season fixture IDs, no duplicates, 32 teams, each with 17 games. |
| `test_cutoff_freezes_actuals` | Real finals by cutoff are identical in every path; later finals in the DB are invisible. |
| `test_ordering_and_byes` | Strict kickoff ordering and legal same-time handling; byes never become games or increment records. |
| `test_three_way_tie_and_restart` | Division/wild-card multi-team procedure, division reduction and restart match official cases, including all remaining tiebreak steps. |
| `test_seed_sum_and_record_conservation` | Exactly eight division winners, seven playoff teams per conference, each seed once, points/WLT conservation. |
| `test_reseed_upsets` | If seeds 7, 6 and 5 all advance, seed 1 hosts seed 7 in Divisional; no stale static bracket pairing. |
| `test_postseason_ot_not_regulation_ot` | A tied playoff regulation game triggers 15-minute postseason periods and legal possessions, never the 600-second regular-season rule or tie/coin-flip shortcut. |
| `test_postseason_champion_conservation` | Exactly 6+4+2+1 playoff games, one conference champion each and one Super Bowl champion per completed path. |
| `test_snapshot_and_identity` | Wrong/late roster source, unresolved IDs and absent snap-table hash fail loudly. |
| `test_synthetic_path_isolation` | Changing one path's Week 11 simulated game only affects later games in that path; does not affect other paths, DB or frozen observations. |
| `test_worker_order_and_seed_replay` | Single-worker vs sharded/resumed jobs produce the same ordered outputs and aggregates; repeat seeds reproduce bytes. |
| `test_blocked_game_reporting` | Illegal score/failed OT/unsupported transition produces an explicitly blocked path, not a made-up winner. |
| `test_summary_probability_conservation` | Sum P(playoffs)=14, sum P(division)=8, each conference's P(seed k)=1, sum P(conference winner)=2 and sum P(Super Bowl champion)=1 over fully valid paths, with denominator/coverage stated. |
| `test_distribution_bands` | Quantiles and shortest 80% interval are computed from empirical draws; ties/blocked seeds are handled according to published rules. |
| `test_no_future_player_status` | No real future injury report, starter or inactives can enter a cutoff-frozen path. |

Validate `nfl_seeding` against published 2024/2025 final seeds and (once available) 2026. Also validate published playoff hosts and reseeding from historical wild-card upsets. Postseason winner, overtime and bracket identities should have golden synthetic fixtures independent of SLC random draws.

### Statistical backtest (walk forward, not retrospective cherry-picking)

1. Replay complete 2024 and 2025 seasons from each post-week snapshot using only cutoff-known data. 2025 is **not untouched validation**: some prior playcall/penalty choices saw that season. Label training, known folds and truly untouched folds accurately; do not tune thresholds on the reported holdout.
2. Against the existing `nfl_sim.py` `history` score baseline, V1.5, V2 and optional D1, compare: game winner Brier/log loss, team score MAE and CRPS, joint score/totals and tail calibration, game-level completion/blocked rate, season projected-wins accuracy, interval coverage, playoff qualification/division/seed accuracy and event-log loss where defined. Use as-of market probabilities as an **observational benchmark** when available, not a hidden model input.
3. At a minimum explicitly show calibration for team scores **<17** and **>27**, plus passing/rushing and workload quantiles. Do not allow improved mean/median to mask missing tails. Compare regular season, playoff-like contexts and early season separately.
4. Test `frozen` vs `path_adaptive` using paired path seeds. Measure whether same-season evidence actually improves future-game forecast skill versus last-season priors. Include ablation for synthetic-update shrinkage/decay and prevent compounding synthetic noise from appearing as real learning.
5. Benchmark full SLC game throughput, conditional-kernel construction, 1K/5K/20K paths and memory/disk cost on the actual host. Record blocked coverage, seeds, duration, CPU and output size. Do not promise 20K fully expanded game traces within the older ratings model's five-minute budget.

**Gate to mark SLC-derived season probabilities research-ready:** all deterministic legality/leak/conservation tests pass; no silent fallback; the surrogate/kernel has held-out conditional calibration and error compared with full SLC; reproducible 20K paths with audited effective sample counts; historical playoff seeding/bracket reconciled; tails and model-vs-baseline grade table published with failures visible. If those gates fail, ship only an explicitly labelled `ratings_history_baseline` season demo or keep the SLC run internal.

**Gate to publish an SLC-v2 forecast as adopted:** separate, forward-looking calibration evidence and a user-approved model selection decision. Passing code tests alone does not imply forecasting accuracy.

## 10. Implementation slices, in order

**P0: bounded baseline skeleton (one reviewable PR).** Create `scripts/nfl_sequence/season_sim_2026.py`, `season_schedule.py`, `season_path.py`, `season_postseason.py` and TDD fixtures. Wrap the existing ratings-history game draw first for end-to-end scheduling, 2026 record conservation, official seeds, full bracket and output manifest. No modifications to `backend/nfl_sim.py` unless isolated bug fixes have their own tests. A playable complete-season result is better than 20K unconnected weekly seed files.

**P1: bracket and temporal provenance gate.** Test all 13 postseason fixtures, upsets/reseeding, venue mapping, regular/postseason OT distinction, source cutoff and 2024/2025 published seed reproduction. Block unsupported postseason OT until legal. A frozen past cutoff must remain reproducible after the DB changes.

**P2: SLC-v2 game-kernel integration.** Add `season_game_model.py` and a deterministic, versioned loader for full-game SLC outcomes/conditional kernels. Expose the same roster/eligibility/identity validations as `simulate_pregame_batch.py`. Report cells with inadequate coverage. Produce a paired baseline-vs-SLC 1K-path audit before 20K.

**P3: 20K frozen SLC season Monte Carlo.** Implement worker shards, stable per-path seeds, streaming gzip records, checkpoints/resume and exact aggregation. Pin outputs/host benchmarks. Show playoff odds, team win distributions and 80% score bands, with blocked coverage.

**P4: path-adaptive research.** Implement `apply_simulated_game` without touching the real DB, with optional team-strength, 2026 game outcomes, playbook/tendency and player-workload updates. Compare frozen vs adaptive and V1.5 vs V2; D1 stays an experimental flag until validated.

**P5: publish/UI and Gridiron replay.** Expose a versioned read-only results API; add a 32-team season/playoff view, round advancement and sample-path viewer. Store prior weekly snapshots to power odds movers and public grading; link specific SLC play traces to the 2D football visualizer where available. Promotion to production remains a separate decision.

### Proposed CLI (not implemented by this spec)

    python3 scripts/nfl_sequence/season_sim_2026.py \
      --season 2026 \
      --as-of-utc "$AS_OF_UTC" \
      --mode slc_kernel_frozen \
      --paths 20000 \
      --seed-start 1 \
      --manifest pinned-inputs.json \
      --out runs/nfl/season/2026/<run_id>

Use `--mode baseline_ratings` as the first executable test; use `--mode slc_full_trace` only with a deliberately smaller configured path count. The engine must refuse missing required fingerprints and mismatched input sources, not quietly choose defaults.

## 11. Review deliverables, not subjective completion claims

Each slice must push an explicit diff with: (a) exact changed paths, (b) unit/integration test command and unedited output, (c) a tiny deterministic 2026 season fixture that can be inspected, (d) a sample run manifest and one complete path, (e) the current count and causes of failed/blocked paths, (f) an honest comparison to the ratings baseline, and (g) a list of remaining blockers and accepted limitations. Do not run a production forecast, modify live DBs, or silently merge without a separate instruction.

First practical milestone: **from a frozen November 2026 cutoff, run and inspect one complete 2026 regular-season-plus-13-game-playoffs path, then 100 paired paths, then 1,000 audited paths, then 20,000 only after gates.** Demonstrate a full bracket and champion on the first path while preserving every actual 2026 result at that cutoff. No single-game 10K exercise counts as completing this milestone.

## 12. References and code touchpoints

Repository (read on `slc-v2` at spec time):
- [Season Monte Carlo, older ratings baseline](https://github.com/micahp/legendarypicks/blob/slc-v2/backend/nfl_sim.py)
- [NFL standings](https://github.com/micahp/legendarypicks/blob/slc-v2/backend/nfl_standings.py), [NFL seeding](https://github.com/micahp/legendarypicks/blob/slc-v2/backend/nfl_seeding.py), [historical bracket check](https://github.com/micahp/legendarypicks/blob/slc-v2/backend/nfl_bracket_check.py)
- [SLC-v2 batch runner](https://github.com/micahp/legendarypicks/blob/slc-v2/scripts/nfl_sequence/simulate_pregame_batch.py), [SLC engine](https://github.com/micahp/legendarypicks/blob/slc-v2/scripts/nfl_sequence/slc_engine.py), [configuration](https://github.com/micahp/legendarypicks/blob/slc-v2/scripts/nfl_sequence/slc_config.py)
- [Cutoff-safe pregame snapshot](https://github.com/micahp/legendarypicks/blob/slc-v2/scripts/nfl_sequence/pregame_snapshot.py), [playbook prior](https://github.com/micahp/legendarypicks/blob/slc-v2/scripts/nfl_sequence/playbook_prior.py), [game state](https://github.com/micahp/legendarypicks/blob/slc-v2/scripts/nfl_sequence/game_state.py), [SLC exports](https://github.com/micahp/legendarypicks/blob/slc-v2/scripts/nfl_sequence/slc_outputs.py)
- [Earlier team-rating/playoff-odds spec](https://github.com/micahp/legendarypicks/blob/slc-v2/docs/SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md) and [2025 replay provenance note](https://github.com/micahp/legendarypicks/blob/slc-v2/docs/research/SLC-2025-REPLAY-RUN-PREP-2026-11-05.md)

External normative sources:
- [NFL 2026 schedule announcement / playoff format](https://media.nfl.com/football-information/2026/news/2026-nfl-schedule-announced)
- [NFL official tiebreaking procedures](https://www.nfl.com/standings/tie-breaking-procedures)
- [NFL 2026 rulebook, Rule 16](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook)

**Bottom line:** Build season continuity, standings and a genuine Super Bowl path first. Then plug in a measured SLC-derived conditional game model. Finally test within-path team and player adaptation rather than assuming that a sophisticated full-game engine automatically makes better future-season predictions.
