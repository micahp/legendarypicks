# Proposal: Phase 2C game-state dispersion work

Status: proposal for review only. No generator code, adoption gate, or Phase 2A artifact is changed by this proposal.

Amendment: manager-requested documentation update; priority wording only, scope unchanged.

## Evidence to address

- Attempts have observed variance 119.73 versus a full forecast-mixture variance of 75.09. The within-team gap is +27.76 (95% game-cluster interval +20.78 to +32.65); the between-team gap is another +16.88.
- Official SOG has observed variance 47.79 versus forecast-mixture variance 34.63. The within-team gap is +6.70 (+3.87 to +8.42); the between-team gap is +6.46.
- Team count dependence is also wrong. Observed home-away attempt covariance/correlation is −44.71/−0.382; generated is −8.82/−0.119. For official SOG it is −11.46/−0.242 observed versus −0.66/−0.019 generated. A shared positive game-pace multiplier on its own may make this worse.
- Share dispersion is low in both outcomes. Observed/generated share variance and share index are 0.006153/2.759 versus 0.003239/1.449 for attempts, and 0.007255/1.801 versus 0.004549/1.112 for SOG. The paired moments (Var(H), Var(A), Cov(H,A), Var(H−A)) are 117.597/116.503/−44.710/323.520 observed versus 75.658/72.516/−8.820/165.813 generated for attempts; for SOG they are 47.233/47.518/−11.460/117.671 observed versus 34.845/33.876/−0.655/70.031 generated. The independent latent-margin moment fit is descriptive on 2021: attempts τ=0.1062, σ=0.3239; SOG τ=0.1341, σ=0.3504. A shared positive tempo multiplier moves covariance in the wrong direction: attempt covariance changes from −8.820 to −0.872 at CV 0.05, +22.971 at CV 0.10, and +62.709 at CV 0.15; SOG covariance is +1.760 at CV 0.05 from a generated −0.655.
- Penalties average 4.890 versus 7.390 per game. After team fixed effects, their linear association projects only 0.000 attempt-variance units and 0.011 SOG-variance units of the respective within-team gaps. The rate miss matters to manpower and scoring composition, but does not explain shot-count spread.
- Goals do not show a need for more spread in this fold: their generated within-team spread is 3.304 versus 2.975 observed. Mean scoring remains high by 0.328 goals/team-game, EVEN goals are high by 1.177/game, and 0.363 observed empty-net goals/game cannot be generated.

## Proposed scope

1. **Separate game total pace from team shot share.** Prioritize calibrating home/away allocation dispersion and dependence first, then total-game pace dispersion: observed share variance and covariance are underrepresented, and a shared positive pace multiplier moves home-away covariance in the wrong direction. Add a pregame latent rate layer to the existing event-time generator, with independently parameterized total-game intensity and home/away allocation. Keep the multiplier mean at one and estimate dispersion/coupling from training seasons only. Do not introduce one common positive game multiplier without testing the observed negative home-away dependence. Keep this experiment isolated from the penalty and goalie changes.
   Preregistration: [PHASE2C-ALLOC-PREREG.md](PHASE2C-ALLOC-PREREG.md).
2. **Model penalty/manpower state explicitly.** Replace the single-minor approximation with a seeded penalty state machine that can represent concurrent calls, durations, expiration, power-play goals, late-period calls, and the applicable OT manpower rules. Preserve the Phase 2A event clock and emit a reconciled event for every call, expiration, and manpower transition.
3. **Add score- and clock-dependent goalie pulls.** Simulate goalie presence from the game's score, time, and simulated state. This creates the currently absent empty-net shot and goal category without using target-game goalie identity or future observations. Estimate pull behavior from training data only.

Implement each item as an isolated research ablation after approval. Do not combine them before their separate effects are measured. Keep V3's generated shot, save, and goal event chain as the only path to scores.

## Expected effects and risks

- Total-pace and side-allocation variation may widen team attempts/SOG and improve their count coverage. A poor dependence model can inflate game totals, reverse the home-away covariance error, or worsen team SOG CRPS and final-score energy.
- A fuller penalty process may raise special-teams opportunities and reduce the generated EVEN share. It may also change total attempts, goal rates, period scoring, and the regulation tie rate.
- Goalie pulls will add empty-net events and goals. Adding the historical 0.363 goals/game as an independent offset would be invalid: pulls depend on the simulated score and remaining time, and their goals feed back into final margin and winner probability. Total goals already run high, so the rest of the scoring process may need to compensate.
- Each change invalidates the old simulation cache and can alter seed-to-event mappings. Validation must recheck shot-attempt/outcome reconciliation, SOG derivation, score recomputation, clock ordering, penalty service/expiry, regulation-to-OT transitions, OT sudden death, and shootout separation.

## Evaluation boundary

Use the forward 2021 development population only for exploratory fitting and isolated ablations, with training-only or forward-only features. Do not use the exposed 2022 population for tuning. Preserve the Phase 2A reference and current gates. A future adoption recommendation requires the frozen, later-season or prospective evaluation protocol; this Phase 2C proposal supplies no selection or adoption evidence.
