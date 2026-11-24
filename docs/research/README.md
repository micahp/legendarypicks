# Legendary Picks Research

Start here for research strategy, literature reviews, simulation architecture, experiment evidence and decisions. This is a curated navigation page, not an exhaustive inventory or a declaration that all listed candidates are production-ready.

## Start here

| Document | What it covers |
|---|---|
| [Sports Simulation and Generative Modeling Literature Review (Nov 24)](SPORTS-SIMULATION-GENERATIVE-MODELING-LITERATURE-REVIEW-2026-11-24.md) | External literature on empirical and generative sports simulation, probability estimators, team and player strength, sequential modeling, calibration and proposed experiments. |
| [Granular Prediction Modeling Strategy (Oct 26)](../STRATEGY-GRANULAR-PREDICTION-MODELS-2026-10-26.md) | Cross-sport modeling architecture, component and global evaluation gates, research process. |
| [Forecasting North Star (Oct 10)](../STRATEGY-forecasting-north-star-2026-10-10.md) | Forecasting objectives and product research direction. |
| [Simulation Learnings](../SIMULATION-LEARNINGS.md) | Accumulated findings, failures and engineering lessons. |
| [NFL Model Research Index](../INDEX-nfl-model-research-2026-10-12.md) | Existing detailed NFL research inventory and links to prior experiments. |

## NFL statistical simulation

| Document | What it covers |
|---|---|
| [Contextual NFL Full-Game Simulation](../SPEC-NFL-CONTEXTUAL-FULL-GAME-SIMULATION-2026-10-25.md) | Full-game simulation design. |
| [NFL Situational Research Matrix](NFL-SITUATIONAL-RESEARCH-MATRIX-2010-2026.md) | Factor registry, evidence requirements, interactions, sparse-cell handling and cutoff rules. |
| [NFL Rule Regime Registry](NFL-RULE-REGIME-REGISTRY-2010-2026.md) | Historical rule changes and regime handling. |
| [V2 Component Ablation](SLC-V2-COMPONENT-ABLATION-2026-11-05.md) | Previous additive component experiment and its results. |
| [V1.5 Outcome Ablation](slc-v15-outcome-ablation-121-2026-11-11/FINAL-GRADING-2026-11-11.md) | Previous 121-game outcome ablation grading. |
| [V2 Strength-First Mechanism Gates](SLC-V2-STRENGTH-FIRST-MECHANISM-GATES-2026-11-10.md) | Team-strength research design and evaluation gates. |
| [Transition-Strength Diagnostic](slc-transition-strength-diagnostic-2026-11-10/README.md) | Evidence on historical and team-adjusted transition distributions. |

## Conditional Event Generation (CEG)

- [Architecture and research plan](SLC-CONDITIONAL-EVENT-GENERATION-PLAN.md): transition from historical-row sampling to conditional event generation.
- [Project status and phase index](slc-ceg-2026-11-24/README.md): implementation and evaluation status; start here for the latest documented results.
- [Full-game evaluation](slc-ceg-2026-11-24/PHASE7-EVALUATION-REPORT.md): realism, runtime completion and forecasting results.
- [Team-strength results](slc-ceg-2026-11-24/PHASE8-TEAM-STRENGTH-REPORT.md): limits of per-play shrinkage and drive-level team differentiation.
- [Phase 9 preregistration](slc-ceg-2026-11-24/PHASE9-PREREGISTRATION.md): bounded drive-level team-strength experiment.
- [Candidate register](slc-ceg-2026-11-24/CANDIDATES.md) and [engineering backlog](slc-ceg-2026-11-24/ENGINEERING-BACKLOG.md): active, failed and pending candidates; outstanding implementation work.

## External methodology and other sports

- [DraftKings sports simulation and tennis projections](../RESEARCH-draftkings-sports-simulation-2026-10-14.md): architecture reference and tennis validation lessons.
- [Generative modeling literature review](SPORTS-SIMULATION-GENERATIVE-MODELING-LITERATURE-REVIEW-2026-11-24.md): primary reading list across NFL, basketball, soccer and baseball; also includes references for autonomous simulation.

## Maintaining this index

Add durable research plans, literature reviews, major findings, and project-level READMEs here when they land. Prefer a project README linking its phase reports and artifacts over a flat list of every experiment. Keep failed results discoverable and distinguish proposed, experimental, rejected and validated work. Do not link unmerged branch-local documents as if they exist on the current branch. When a research branch lands, update this index alongside its documentation. Production status is determined by the relevant release and evaluation records, not inclusion here.
