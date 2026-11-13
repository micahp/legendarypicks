# V1.7 penalty transition: proposal-to-enforcement bridge

The V1.7 penalty sampler can now pass a proposed foul to the bounded
enforcement engine through `scripts/nfl_sequence/penalty_transition.py`.
The caller must provide the before state, ordinary after-play state and an
explicit accept/decline ruling; defensive pass interference also requires a
foul spot. The bridge checks that the model context matches the before state,
rejects a completed play for a pre-snap foul, and refuses unsupported foul or
play types instead of silently treating them as no foul. With the sampler
disabled, it returns the unchanged ordinary after-play state.

The enforcement engine now sets a new series to goal-to-go when an automatic
first down is inside the ten-yard line. Its existing rule-bounded scope and
fail-closed half-distance and goal-line limitations still apply.

## Example

Washington has second-and-8 at its own 40 (`yardline_100=60`). The model
proposes an offensive false start. Given an explicit accepted ruling, the
bridge returns second-and-13 at Washington's 35 (`yardline_100=65`), records
five enforced yards, and retains the proposal's model and source identifiers.
The ball was never snapped, so the caller supplies the same before and
after-play states. This is a deterministic unit-test fixture, not a result
from a calibrated model or a full-game simulation.

## Verification and remaining work

The focused sampler, fit, training, enforcement and transition suites passed
36 tests. Tests cover the example, disabled sampling, missing rulings,
unsupported fouls and goal-to-go after defensive holding.

**This is not yet integrated into full-game transitions.** The drive engine
still blocks sampled penalties. Before that guard can be removed, the game
engine needs explicit penalty event records, clock and down handling,
acceptance decisions, player/team statistical accounting, score and turnover
handling, and end-to-end validation. The proposal model covers more foul
types than the current enforcement engine; unsupported cases must continue to
block. Penalty-off games must also be checked against the frozen V1.6 baseline.

The historical descriptions and extracted rows remain research evidence, not
verified adjudications or independent training opportunities. No fitted model,
calibration claim, full-game example, or V1.7 freeze is asserted here. NFL rule
reference: [2026 NFL Rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook).
