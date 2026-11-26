# NFL sequence model registry

[All model cards](../README.md) · [NFL league card](../nfl.md) · [Architecture](../../architecture/README.md)

Read model cards by identity, not by branch or informal version number. All entries below are research; this is not a release authorization.

| Model | Mechanism / distinction |
|---|---|
| [SLC V1](slc-v1.md) | Historical conditional row sampling; full-stack score/clock playcalling, team outcome ratios, formation, coverage, player shares/conditioning, QB and label layers, exact yardline and streak features. |
| [SLC V1.5](slc-v1.5.md) | Full-stack historical sampler; distinct frozen source policy from V1. A season-adaptation N0=4 control appears in the November 12 bounded comparison; do not assume every V1.5 package has that configuration. |
| [SLC V1.6](slc-v1.6.md) | Conditional pass labels, exact-distance yardage, season adaptation; removes coverage-outcome layer relative to V1 stack. |
| [SLC V1.7](slc-v1.7.md) | V1.6 candidate with penalty proposal and enforcement under a research ruling policy. |
| [SLC V2](slc-v2.md) | Frozen V2 statistical full-game model adds participation lineup, snap-count update, kicker-specific field goals, backoff/blocker fixes, season adaptation and RNG v2; source pin distinct from moving slc-v2 branch. |
| [PBV1](pbv1.md) | Personnel-package sampler on HPV1 historical NFL scrimmage records 2022–25. Cell = run/pass, down, distance bucket, red zone; shrink cell counts to parent (play family, down), K=20. Observed support only. Label-only and off controls are distinct; not an executable playbook. |
| [V1 Pure](slc-v1-pure.md) | Minimal historical control |
| [V2 Pure](slc-v2-pure.md) | Separate intended control; exact identity not recovered |
| [V2 Simplified / support-aware / soft](slc-v2-simplified.md) | Optional row-conditioning experiments |
| [CEG](ceg.md) | New events from conditional distributions, no historical rows at inference |
| [V1 Complete](slc-v1-complete.md) | Autonomous 22-player physical execution; incomplete |

Frozen source policy: [Executable registry at e0d3f603](https://github.com/micahp/legendarypicks/blob/e0d3f603/scripts/nfl_sequence/slc_model_registry.py). This documentation is an index, not a replacement for the manifest. V1 points / EPA / Elo and Spec B are separate NFL model families.
