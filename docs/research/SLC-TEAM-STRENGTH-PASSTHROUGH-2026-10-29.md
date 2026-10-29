# SLC team-strength pass-through, 2026-10-29

Status: exploratory research. The small paired-seed ablation does not establish calibrated team-strength effects. Keep all optional layers research-only and off by default.

## Finding

Player shares change who receives targets and carries, but the default score-clock sampler does not use those selected identities when it chooses the event or source outcome row. With player-conditioned outcomes disabled, a changed receiver or rusher receives different statistical credit while the sampled event, yards, touchdown outcome, and random-number stream remain unchanged. This is why the player-share/Dirichlet layer changed player counts in all 99 paired valid games in the existing CAR–GB check while leaving each final score identical ([player-share validation](SLC-PLAYER-SHARE-VALIDATION-2026-10-29.md)).

The team-strength paths are separate. The score-clock play-call artifact can change pre-event intent. The optional team-outcome table reweights discrete event types within an intent using offense and defense splits, but does not select team-conditioned yardage or touchdown rows. The user-requested player-outcome table is the path that makes selected-player identity affect event and source-row sampling.

The code-level details are in [slc_playcall.py](../../scripts/nfl_sequence/slc_playcall.py), [pre_event.py](../../scripts/nfl_sequence/pre_event.py), and [team_tendency.py](../../scripts/nfl_sequence/team_tendency.py). For the unconditioned baseline sampler, event type is sampled from the pooled cell distribution and a source row is sampled from that event's pooled rows. The participant chooser attaches the pre-event participant to the selected row. Its participant/share draws use separate streams keyed by snapshot hash, game seed, and decision index, so changing shares does not consume or shift the game-outcome RNG stream. Unless a conditioning table is enabled, the participant does not enter either sampling weight. Team tendencies alter event weights; they do not reweight continuous yards or touchdowns within each event. Their event ratios are also shrunk with prior strength 25.

## Regression tests

Two tests were added to [test_slc_playcall.py](../../scripts/nfl_sequence/test_slc_playcall.py):

1. `test_changing_only_the_selected_receiver_preserves_the_outcome_and_rng_stream` fixes the candidate pool and outcome seed, changes a two-player share vector from 100/0 to 0/100, and uses a separate participant-draw stream. It asserts that the event, source game/play, yards, and outcome RNG state stay equal while the assigned receiver changes. It also asserts the decision is not marked player-conditioned.
2. `test_player_outcome_table_makes_the_selected_player_affect_event_sampling` is a positive control. A synthetic player-outcome table makes the selected good and bad QB/receiver identities sharply favor different event types; across 200 matched seeds, the good-player path produces over 100 more completions and marks decisions player-conditioned.

The focused suites passed: 14 `test_slc_playcall`, 4 `test_player_outcomes`, and 21 `test_share_distributions` tests (39 total), using the backend virtualenv. The tests explain the sampler mechanism; the separate 99-game held-out-share run supplies the end-to-end score evidence.

## Team-strength paired-seed ablation

Three arms were run on three frozen 2026 Week 8 snapshots with seeds 1–40:

- `team-neutral`: the pinned score-clock artifact with only the 128 `blocks.team_down` coefficients set to zero; all other artifact values were preserved.
- `off`: the pinned score-clock artifact with team-outcome splits off.
- `on`: the same pinned artifact with `--playcall-team-outcomes` on.

The model cutoff is before 2026 Week 1. The score-clock artifact was fit through 2025; team-outcome counts use source seasons 2022–2025. The three games were selected as contrasting checks using 2025 regular-season home-minus-away net-points-per-game differences: MIA–NE −14.529, SEA–CHI +9.706, and NYJ–LV −0.706. This selection calculation used the local `nfl_schedule` table in `picks.dev.db`, restricted to 2025 regular-season games with final scores (272 games, all 32 teams); each team's net points per game is (points for − points against) divided by games played. Those figures selected cases only; they were not passed to the simulator as team-strength inputs.

All runs had zero simulation/validation errors. Some seeds were blocked before a full game, so paired contrasts use only seed IDs that were valid full games in all three arms for that matchup. There were 35 common valid seeds for MIA–NE, 38 for SEA–CHI, and 37 for NYJ–LV. Valid coverage by arm was MIA–NE: 37/40 off, 39/40 on, 39/40 neutral; SEA–CHI: 39/40, 39/40, 40/40; NYJ–LV: 39/40 in each arm.

Intervals below are two-sided 95% paired t intervals over those common valid seeds. Home-win changes are percentage points. They are noisy at this seed count; every interval includes zero.

| Contrast | Matchup | Home margin, points (95% CI) | Total points (95% CI) | Home win, pp (95% CI) |
|---|---|---:|---:|---:|
| Call effect: off − team-neutral | MIA–NE | −1.03 [−7.11, 5.06] | +3.31 [−1.98, 8.61] | −8.6 [−34.1, 16.9] |
| Call effect: off − team-neutral | SEA–CHI | +3.42 [−2.16, 9.00] | +0.16 [−5.00, 5.32] | +13.2 [−8.7, 35.0] |
| Call effect: off − team-neutral | NYJ–LV | +2.14 [−4.99, 9.26] | −0.08 [−6.27, 6.11] | +8.1 [−16.0, 32.2] |
| Team outcomes: on − off | MIA–NE | +1.71 [−3.40, 6.83] | −3.77 [−8.66, 1.12] | 0.0 [−23.6, 23.6] |
| Team outcomes: on − off | SEA–CHI | +2.00 [−3.22, 7.22] | −0.26 [−5.80, 5.27] | +5.3 [−14.9, 25.4] |
| Team outcomes: on − off | NYJ–LV | +0.30 [−4.74, 5.34] | −3.86 [−8.44, 0.71] | +2.7 [−17.3, 22.7] |
| Combined: on − team-neutral | MIA–NE | +0.69 [−5.65, 7.02] | −0.46 [−6.21, 5.30] | −8.6 [−37.9, 20.7] |
| Combined: on − team-neutral | SEA–CHI | +5.42 [−0.94, 11.78] | −0.11 [−5.45, 5.24] | +18.4 [−6.8, 43.6] |
| Combined: on − team-neutral | NYJ–LV | +2.43 [−3.39, 8.25] | −3.95 [−9.40, 1.51] | +10.8 [−12.5, 34.1] |

The call effect's point estimate leans toward the home side in SEA and NYJ and toward away NE in MIA, but uncertainty is broad. The team-outcome effect's home-margin point estimate is positive in all three games, including MIA–NE where the prior PPG contrast favored the away team. These results do not show a reliable team-strength pass-through. They also do not show that team outcome splits have no effect; the experiment is too small to resolve effects of this size.

The older G4 estimate of 72.3% pass-through is not directly comparable: it came from a different simulator and measured a different quantity. No estimate of pass-through percentage is claimed here.

## Interpretation and next measurement

The evidence supports the narrow identity/share claim: identity changes alone do not change the sampled outcome when the player-conditioned outcome table is off. Team-specific play calling and event splits can affect downstream states and scores, but these ablations do not show a statistically clear score effect over three games and 35–38 paired seeds. This leaves the original team-strength question open.

Next, measure intermediate mechanisms with larger paired samples on several matchups: team-conditioned dropback/run and event frequencies; yards and touchdown rates within each event; drives, clock stoppages, possessions, and scoring chances; then final margin and win probability. Keep the excess scrimmage-play volume and red-zone conversion gaps as separate explanations to test. Do not interpret the player-share improvement as team-score improvement.

The run artifacts expose a provenance issue: off/on runs have identical `observed_reference_sha256` values because the current sampler description/fingerprint omits the team-outcome table. The separate table hash and model manifest are pinned in the run directory. The normal reference fingerprint should include this model manifest before future on/off comparisons rely on it.

## Reproduction

The seed ledgers, frozen snapshots, derived team-neutral artifact, team-outcome model manifest, analyzer output, and SHA-256 values are in [the run directory](slc-team-strength-passthrough-2026-10-29/). Each simulation command uses:

```text
/root/legendarypicks/backend/venv/bin/python scripts/nfl_sequence/simulate_pregame_batch.py \
  --snapshot-file docs/research/slc-team-strength-passthrough-2026-10-29/snapshots/{matchup}.json \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --games 40 --seed-start 1 --context-mode unconditioned --try-policy unconditional \
  --playcall-artifact {base-or-team-neutral-artifact}.json \
  --out docs/research/slc-team-strength-passthrough-2026-10-29/{matchup}-{arm}.json
```

Add `--playcall-team-outcomes` for the `on` arm. To recompute paired summaries:

```text
/root/legendarypicks/backend/venv/bin/python scripts/nfl_sequence/analyze_team_strength_passthrough.py \
  --out docs/research/slc-team-strength-passthrough-2026-10-29/paired-summary.json
```

The analyzer fails if seed ranges, source snapshots, source commit, play-call artifact hashes, or arm flags differ from this run's specification. `run-manifest.json` records command arguments, source and artifact hashes, per-run fingerprints, valid seed counts, and output hashes. Producer file hashes in the simulation outputs match the pinned commit, although the producer worktree was marked dirty at run time.
