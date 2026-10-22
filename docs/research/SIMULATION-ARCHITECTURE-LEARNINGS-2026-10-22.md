# Legendary Picks: Simulation Architecture and Research Lessons
Date: 2026-10-22
Status: Design and research note only. No model adoption, production change, or physics implementation.
Scope: NHL V3, NFL / Gridiron Physics, other sports as appropriate.

## 1. Thesis and problem statement

The goal is not simply to sample plausible stat distributions. It is to forecast coherent team, player and event outcomes, understand what caused them, and learn from each real game after its results become available.

The current NHL V3 Phase 2A is a statistically fitted event generator: it samples the next shot attempt from team hazards, marks which team shoots, samples historical shot location/type, and samples one of BLOCKED/MISSED/SAVED/GOAL from fitted probabilities. State is updated for goals, a simplified penalty process and game clock. It has no player motion, puck trajectory, possession mechanics, goalie positioning or physical rebound state. Two consecutive shots can be close in time without the first physically or causally generating the second.

This is not a failure of probability modeling; it is a limitation of the chosen state representation. Improving aggregate variance alone is not equivalent to discovering the mechanism behind the variation. A visually realistic physical model is not automatically a better predictive model, either. The proposed direction is modular, hypothesis-driven and evaluated prospectively.

Key question for each mechanism: What observable or latent cause produces the event, what evidence supports it, what independently measured output should improve, and is the additional complexity worth its predictive and compute cost?

## 2. What was actually learned from NHL V3

Evidence is tied to research artifacts, not unverified public performance claims:

- Event-quality and replay foundation: 4,876 historical NHL regular-season games, 1,510,104 published PBP events; accepted scores reconcile 4,876/4,876, eligible team SOG 4,814/4,814; 62 SOG games remain quarantined. Player-stat and shift eligibility is component-specific, not all-or-nothing. Phase 1 replay commit: 2f2d1245d7459f17ed656111da5c6494d192e332.
- Phase 2A test: 2022 partial historical holdout, 343 games (341 SOG eligible). Fitted stochastic events improved team SOG CRPS by 0.227 against the simple-average baseline but worsened team goal CRPS by 0.048 and joint final-score energy by 0.082; winner Brier improvement was inconclusive. A same-window refit of v2 also beat V3 on goal CRPS and final-score energy. Phase 2A commit: 19bb60cf8997abe1368b732983a4ed2ac1904cd3. Do not promote.
- Post-hoc structural diagnosis in 2021 development: observed home attempt-share SD 0.0784 versus simulated 0.0569; real home-away attempt covariance approximately -44.71 versus -8.82 simulated. The simulator underrepresents allocation variation. An attempt-share variance match is a diagnostic, not a demonstration of better predictive probabilities.
- An attempted conditional-binomial and Beta-Binomial conversion-noise intervention worsened team SOG CRPS at sigma 0.324. Two measured sigma-zero floors (+0.023651 and +0.037670) could not explain the observed +0.106189 raw deterioration. In the Beta-Binomial variant, 1,633/2,584 game-side fits fell back to Binomial after a nonnegative correlation truncation; realized candidate variance agreed with its analytic variance. These are rejection results for tested kernels, not a proof that all conversion distributions fail. Closeout commit: b49fd565b052ea4912bb42d674ca5033f868ab94.
- A rebound is not the same as a deflection. Deflection changes an incoming shot's path; rebound follows a shot/save/block and creates a potential subsequent possession or attempt. A shot type category named DEFLECTED in PBP cannot itself encode a rebound mechanism.
- The 2018 through partial 2022 outcome/event frame is historical; current-season learning and truly new evaluation require later eligible data. Historical 2021/2022 experiments have already been inspected repeatedly; do not describe them as fresh holdouts.

Research lesson: preserve the shot-volume advance, but stop treating repeated variance/noise adjustments as a roadmap. Demand an explicit mechanistic or predictive hypothesis before another intervention. Separate statistical realism from forward forecast quality.

## 3. Proposed three-layer architecture

A. Predictive state / sequential learning layer
- Maintains as-of-time team, player, goalie, usage, availability and skill estimates, with uncertainty.
- Uses historical results, role changes and time-stamped information that was available before prediction lock.
- Provides marginal expectations and calibrated probability distributions. A simple accurate estimator may beat an elaborate physical simulator.
- Updates after games finish and their official outcomes pass eligibility checks; preserves old predictions and model versions for scoring.

B. Generative game / play-event layer
- Models game and period state, teams, rosters, matchups, line/shift deployment, possessions, opportunities and events.
- Generates shots, actions and correlations; player opportunities and goalie attempts derive from shared generated events rather than independent contradictory totals.
- Can condition on predictive-layer priors, but must not inject the actual future game or silently force all samples to match deterministic targets.
- May start as a constrained statistical state machine. Full continuous physics is optional.

C. Physical and behavioral layer
- When useful, models player bodies, motion, actions, puck/ball trajectories, collisions and rebounds, subject to decision policies and plausible initial conditions.
- Provides mechanisms and rejection/constraint feedback: feasible speeds, reachability, shot angles/elevations, chance of goalie interception, where rebounds land, who can reach the puck, pass windows, tackle angles, etc.
- Could serve as an experimental high-fidelity oracle for selected micro-events, generate training labels for a fast emulator, or produce an engaging 3D playback.
- It must be evaluated against observed sequences; a physics scene that was constrained to a known historical end spot is reconstruction, not predictive evidence.

The layers are composable but not a rigid dependency chain. Physics must not be required for every forecast. A game generator may improve joint probabilities even where no coordinates exist; a good statistical model can remain the best marginal forecaster. An illustrative animation is a separately labeled product use case.

## 4. What physics can add beyond a visual check

Potential value, conditional on evidence:
- Exclude impossible outcomes: puck or ball travel, movement speed, physical contact, goalie reach, time-to-arrival, on-ice/on-field occupancy.
- Mechanistically model event *dependence*: shot trajectory -> save type/rebound direction -> reachable players -> recovery/second attempt; pass trajectory -> contest -> catch -> tackle/YAC.
- Estimate conditional response functions not directly identified by aggregate box scores, such as rebound likelihood given shot speed/angle and goalie posture.
- Model interventions and counterfactuals, e.g. alternate shooter, goalkeeper positioning, route choice, defender distance, line combination; outputs are hypotheses until calibrated.
- Identify which latent quantities need data, and which uncertainties dominate outcomes.
- Provide a high-fidelity test bed for agent policies or learn fast surrogate models.

Costs and limits: unknown initial positions, decision policies and biomechanics may make a physically legal outcome *less* probable than reality. Unvalidated assumed motion can lead to false precision. Compare physical, event-only and marginal baselines on identical unseen games, with total uncertainty and compute cost reported.

## 5. Physics engine versus predictive generator: Gridiron Physics

Public repository: https://github.com/micahp/gridiron-physics

Current repository documents a 120 Hz, 22-player, force- and contact-limited reconstruction of a particular NFL game. Its play scripts supply historical outcomes, real final ball spots, catch points and credited tacklers; the physics/direction code fills motion between constraints. It is useful for replay and physical plausibility but is not yet an autonomous forecast of unseen plays.

The missing NFL predictive chain includes as-of-game rosters and availability -> player ability, skill and usage distributions -> personnel/formation and play-call policy -> routes, coverage, blocking and decision policies -> initial states -> stochastic physical execution -> official play/event/stat accounting -> game continuation. Do not let historical actual target, tackler or end spot enter the predictive mode. Keep reconstruction as a separate validated mode.

Assess using an existing open-source physics solver instead of owning all low-level collision and rigid-body code. Choose on required contacts, 3D ball/puck flight, deterministic replay, performance, JS/browser interoperability, and licensing. A new physics engine does not by itself supply player decisions or trustworthy trajectories.

NFL tracking reality: NFL Next Gen Stats records actual player positions, but comprehensive raw streams are generally not freely accessible. The publicly released NFL Big Data Bowl competition datasets contain sampled player/ball tracking x-y positions, speeds, accelerations and directions for covered plays, subject to competition dataset terms; assess access and rights before training/redistribution. These can measure the realism of Gridiron Physics rather than relying exclusively on invented paths.

## 6. NHL physical mechanism roadmap and data acquisition

Start with one bounded NHL case: shot -> goalie response -> loose puck -> rebound opportunity (or cover/clear/stoppage). Predict outcomes from initial information without passing the known final event. Validate baseline performance before adding contacts, stick interactions or full shifts.

A compact microstate may need shooter/puck position, direction, speed and release type; goalie location/stance/velocity/reaction; a subset of defender and rebound-player positions; obstacles, goal geometry, puck height; and an uncertainty distribution for unavailable state. Shot x/y alone does not imply shot z, speed, trajectory, or goalie location. Test an event-level rebound model as a cheaper baseline even if physics is the main research interest.

Data tiers:
1. NHL GameCenter PBP: game clocks, shot x/y and type when present, score, strength state, identity and some event descriptions; no continuous 3D tracking.
2. Official NHL EDGE Puck and Player Tracking: NHL states that puck and player location streams exist, at up to 60 Hz puck and 15 Hz players; public EDGE provides curated skating speed, shot speed/location, zone time and other metrics, not a generally available *full-game* raw XYZ export. NHL/league partners are logical licensing contacts. NHL EDGE curated public metrics begin around 2021-22. HOWEVER short per-goal 2D tracking sequences (below) are reportedly publicly viewable since 2023-24; do not conflate their restricted, goal-selected coverage with full-game tracking.
3. Licensed tracking/commercial providers: verify actual spatial/temporal schema, sport-specific use rights, cost and permitted model-training/public display.
4. Broadcast or highlight video: potential computer-vision reconstruction, useful for subsets and micro-events; difficult puck visibility, cuts, occlusion, perspective calibration and player identity. Standard highlights are biased toward goals and dramatic chances, not representative all-shot samples. Secure appropriate video rights and mark missing/unseen motion rather than hallucinating a continuous play.
5. Commentary/play descriptions: can label passes, rebounds, scrambles, screens and possession changes, but contains omissions and narrator error; use as weak or manually verified supervision, not a source of exact XYZ coordinates. Audio stick/puck contact cues are future experimental signals, not current verified evidence.

### Important update: NHL's goal-only tracking replays

Independent documentation, third-party examples, and open-source research pipelines describe NHL Goal Visualizer / ppt-replay clips with the puck and all on-ice players tracked at approximately 10 frames/sec for roughly 12-14 seconds around a goal, reportedly available for 2023-24 onward. They have puck/player **x/y** positions in rink coordinates (some interpolation where missing), not full XYZ puck flight or full-game player tracking. These records are conditional on *a goal having occurred* and thus biased toward scoring plays. They cannot directly estimate rebound/save probabilities or all-shot movement distributions without representative non-goal comparators. Do not interpret a trailing clip as proof of a causal pass, puck possession, or player intent without validation. Goal-selected samples can test mechanics of successful scoring sequences, goalie positioning, speed and path reconstruction; unbiased outcome modeling needs failures, saves, misses and blocks too. Evaluate dataset terms, NHL tracking rights, actual clip availability, joins to goal PBP event IDs, source hashes and rate limits before ingest or redistribution.

Relevant publicly documented example APIs and datasets:
- NHL goal visualizer: https://www.nhl.com/ppt-replay/goal/2025020740/95 (illustrative pattern; availability not independently checked)
- Unofficial technical documentation: https://problemxl.github.io/edgework/research/nhl-edge-endpoints/
- Example analysis and outcome detector validation: https://www.edgehalla.com/nhl/methodology/goal-anatomy
- Example goal tracking data-engineering project: https://github.com/eker3777/nhl-tracking-pipeline
- R library goal replay: https://rentosaijo.github.io/nhlscraper/reference/replay.html

NHL video/goal tracking may be copyrighted and/or subject to restrictions even if displayed on a public site. Check terms and get permission before bulk collection, training, redistribution or commercial product use.

Available research directions include hockey broadcast player tracking datasets such as VIP-HTD and published puck-tracking work; inspect their licenses and whether trajectories are actual annotation, image coordinates or rink coordinates before adoption.

EA SPORTS NHL 26 is an instructive precedent: EA/NHL announced NHL EDGE data informs in-game skating, shot power, player tendencies and goalie response. This is evidence for feasibility of data-informed behavior, not a public disclosure of EA's full engine or proof of predictive market advantage.

## 7. Sequential learning and reinforcement learning

Sequential/online learning is not synonymous with reinforcement learning:
- Sequential or Bayesian updating: observe yesterday's game, update estimates of team, player and goalie skill/usage with appropriate shrinkage, forecast tomorrow, and repeat. Observed outcomes are labels, not rewards earned by an agent choosing an action.
- Reinforcement learning: an agent chooses actions within a stateful environment and learns a policy from delayed rewards. Potentially useful later for deciding to shoot, pass, carry, press, change lines, call plays, or position a goalie, provided the simulated environment is realistic enough that learned policies transfer.

Daily loop: ingest officially finished results and availability changes -> run integrity and label gates -> evaluate immutable pregame forecasts -> update sequential player/team latent states and uncertainty -> refresh as-of features -> generate a new pregame snapshot -> run seed-controlled simulations -> lock and publish those forecasts -> continue. Structural parameters need periodic, gated refits rather than reactive retuning after a single day. Distinguish re-estimation from a changed simulator architecture and keep test populations truly forward-only.

EA Madden's published ratings-performance adjusters review weekly player performance and change ability ratings, which is analogous to frequent sequential state updates. That does not establish EA uses reinforcement learning for its ratings.

## 8. Market odds as baseline, external prior or optional blend

Do not conflate using sportsbook information with using it for every prediction. A source may help as:
- independent no-vig baseline for Brier, log loss and distribution scoring;
- an optional market-informed projection arm, with true timestamped and licensed quotes;
- a calibration/ensemble component trained and tested on past data only.

Evaluate three visible products: independent model, market benchmark, optional model-plus-market blend. Report both independent model quality and incremental lift of the blend. Never silently mix target-game market lines into a supposedly market-independent model. Markets are informative but not ground truth; forecast skill and pricing/profitability are separate tests.

Public comparator: PropSims explicitly reports fitting marginal player stat models, blending some with sportsbook lines, generating joint NFL game simulations and scaling outcome means toward its separate player projections. It reports 10,000 runs and archived pregame scoring. This is a published design pattern, not evidence that ThePropDealer or PropsEdge uses the same proprietary internals. Links below.

## 9. Next falsifiable experiments and go/no-go criteria

Priority 1: Data and state audit, not more noise kernels.
- Determine what original NHL EDGE spatial feeds are accessible/licenseable; assess recent PBP, shot velocities, goalie/player locations and video/annotation options. For NFL, audit actual Big Data Bowl trajectory coverage and permitted reuse.
- Establish durable off-host backup of existing verified NHL raw and normalized research corpus before scaling imports.
- Continue acquiring validated post-2022 game and player outcomes needed for current-season sequential updates.

Priority 2: Prove the daily learning loop on existing models.
- Freeze model, inputs, pregame forecasts and random seeds before puck drop.
- Update only permitted dynamic ratings after the next official games.
- Compare fixed/static versus daily-updated versions prospectively on matching games (Brier, log loss, SOG and goals CRPS, player-prop distributions).
- Prevent retrospective overwriting or peeking.

Priority 3: NHL shot/rebound physical proof of concept.
- A few securely sourced annotated shot sequences with known shot starting conditions and independently observed save/rebound outcomes.
- Run statistical/event-only and physical/surrogate candidates with equal information.
- Measure rebound incidence, spatial and timing errors, second-shot probabilities, end-state calibration, robustness to unknown initial conditions, and runtime. Report failure cases.
- If tracking/footage quality is inadequate, do not pretend full 3D is validated. A coarse event model may remain the best forecast.

Priority 4: Gridiron Physics predictive play prototype.
- Separate reconstruction mode from prospective mode.
- Reuse physics only if controlled experiments demonstrate measurable predictive value after the policy / play-calling generator is independently tested.
- Consider higher-fidelity physics as an auxiliary evaluator or content renderer rather than a required forecast engine.

Core acceptance principle: each new simulation detail must either improve a prespecified forward scoring metric or deliver a separately declared visualization/engineering outcome. Realism, internal consistency and forecast accuracy require separate evidence.

## Public source references (consulted 2026-10-22)

- NHL EDGE public-data and scope: https://www.nhl.com/news/nhl-edge-advanced-stats-section-brings-fans-closer-to-game and https://www.nhl.com/news/topic/nhl-edge/nhl-edge-launches-website-for-puck-and-player-tracking-data
- EA SPORTS NHL 26 integration: https://www.ea.com/games/nhl/nhl-26/news/nhl-26-gameplay-iceq2-deep-dive and https://www.ea.com/games/nhl/nhl-26/features/nhl26-gameplay-with-iceq2
- Madden weekly ratings adjusters (historical public description): https://espnpressroom.com/feature/scores-to-settle-espn-nfl-analyst-damien-woody-reviews-his-best-and-worst-madden-ratings/
- NFL Big Data Bowl 2025 public competition tracking description: https://www.kaggle.com/competitions/nfl-big-data-bowl-2025/data
- NFL Big Data Bowl 2026 tracking competition (player trajectories, passing plays; terms apply): https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-analytics/data
- PropSims game-simulation and optional market-blend methodology: https://propsims.com/how-the-simulations-work/ and https://propsims.com/methodology/nfl-projections/
- Hockey public tracking benchmark: https://openjournals.uwaterloo.ca/index.php/vsl/article/view/5858
- Broadcast puck localization research: https://arxiv.org/abs/2105.10563
- GridIron Physics repo: https://github.com/micahp/gridiron-physics

## Record of architectural decision

Direction: preserve verified NHL event quality work and predictive shot-volume progress; suspend unmotivated variance/kernel tuning as the main roadmap. Prototype daily sequential learning, test a bounded shot/goalie/rebound mechanism, investigate actual trajectories, and connect predictive priors, event simulation and optional physics with prospective evaluation. No claims that physics is automatically more predictive or that competing products have publicly disclosed proprietary internals.
