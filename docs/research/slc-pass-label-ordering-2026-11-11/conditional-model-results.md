# Conditional A/D/E pass-outcome model

## Code change

The old sampler applied receiver role (A), pass depth (D), and pass location (E) lifts before choosing a dropback event. Those labels are unavailable when a sack occurs, so this let pass-only labels suppress sack probability.

The sampler now has a regularized conditional model for the four outcomes **after a pass attempt is selected**: completion, incompletion, interception, and fumble lost. Sacks are excluded. The model fits A/D/E effects from labeled pass outcomes, with a situation-cell baseline and L2 shrinkage. It calibrates the label effects to the existing team and situation label priors so their expected pass-outcome mix equals the baseline mix. This retains label effects while preventing them from changing the marginal event rates on average.

The default `auto` mode selects this model when decision labels are enabled. `--playcall-pass-label-mode legacy` remains available to reproduce previous runs. A/D/E still filter the sampled historical row, which carries the corresponding target role, depth, location, and yardage evidence.

## Historical conditional evaluation

Training used labeled 2022–2024 pass outcomes. Ridge strength 0.01 was selected on 2024 validation. The held-out test used 17,079 2025 pass outcomes across 272 games, scored conditional on their observed A/D/E labels. A game-clustered paired bootstrap compared the conditional model with the situation-only pass-outcome distribution.

| Metric | Situation baseline | Conditional A/D/E model | Paired delta, model minus baseline, 95% CI |
|---|---:|---:|---:|
| Log loss ↓ | 0.76482 | 0.71477 | −0.05363 to −0.04653 |
| Multiclass Brier ↓ | 0.47595 | 0.43500 | −0.04386 to −0.03800 |

The conditional model improved both scores on this observed-label holdout. The calibrated effects preserve the baseline distribution when labels are averaged over the simulator's configured label priors. This is not a full-game validation; label-prior quality and downstream game effects still need a bounded simulation check.

The earlier 3-seed experiment tested only the ordering correction and the marginal-lift conditional mode. It did not use this model. Its results are not evidence for or against this implementation.
