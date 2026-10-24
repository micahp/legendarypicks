# AGENTS.md: read this before editing legendarypicks

These are the rules, short. Each comes from a real incident; the incident, the measurements and
the examples are in [docs/AGENTS-REFERENCE.md](docs/AGENTS-REFERENCE.md) (the full previous text,
section numbers unchanged). Read the matching section there when a rule touches your task.

**Guiding principle.** Before trusting a result, define what "correct and complete" requires, then
verify against ground truth: the whole population, the real data, an independent source. Assume a
gap remains until you have measured it.

## E1 UPDATED RESEARCH HANDOFF — 2026-10-24

Latest pushed LP `feat/nfl-sequence-e1-2026-10-24` commit is [`945754080086a1f9ae6dac06740041826395b017`](https://github.com/micahp/legendarypicks/commit/945754080086a1f9ae6dac06740041826395b017). It has six authored starts × 1,200 seeds = **7,200 limited-checker passing** retrospective drive records, with eight terminal families, eight focused transition tests, ten pinned new fixtures, and Q1/Q3 change-ends continuation (not drive ending). **Scoped E1 research milestone accepted; E2 NFL game not yet built.** See [exact Gridiron drive-viewer handoff](https://github.com/micahp/gridiron-physics/blob/main/docs/research/E1-DRIVE-RECORD-HANDOFF-2026-10-24.md).

**Immediate LP work:** explicitly share/agree `mode=drive_statistical_demo`, `valid_full_game=false`, versioned field orientation, E1 terminal/event vocabulary and nullable provenance with hermes2, then support its read-only drive viewer; never coerce multi-play E1 into E0 single-play schema. Fix the E1 output's **false `gaps` claim** that quarter changes are unmodeled; fix/clarify stale `reducer.TERMINALS` containing `end_of_period`. Regenerate fixture hashes/repro proof if any emitted record changes. Keep `field_goal_attempt` **result unknown** (not scored), zero fake kickoff/score, and distinguish retrospective drive legality from play/drive frequency realism. Current clock runoff derives from historical next-snap intervals and clamps overruns; test boundary behavior before treating it as NFL-accurate. After drive-viewer handoff, **next critical path is E2 normal-game kickoff/coin-toss/score/restart engine**, with exactly two **half_start** kickoffs by different teams and no sampled same-team exception. No merges or production edits.

## NON-NEGOTIABLE KICKOFF POLICY — 2026-10-24

**Normal LP game simulations MUST have two half-opening kickoffs with different kicking teams.** The Q1 kickoff receiving team **kicks to start Q3**; the Q1 kicking team **receives to start Q3**. Record coin toss, winner's **receive or defer** decision, the two half-specific legal choice resolutions and the actual kickoff events, but **do not randomly choose kick-without-deferring, defend-a-goal-first or receive-both-halves** in normal games. **Zero probability, not simply an extremely low weight.** Unusual legally possible choices are allowed **ONLY** for source-verified historical reconstruction or an explicitly user-requested and flagged `explicit_exception_scenario`, excluded from normal forecasts, distributions and ordinary batch testing.

**Fail closed:** `normal_nfl_game` cannot set `valid_full_game=true` unless `half_start_kickoffs.length===2`, the kicking teams are opposite, kickoff event times are Q1/Q3, toss/choice ledger is consistent, and all postkickoff possession state is computed from the actual kickoff outcome. Test both opening receive and defer paths and a double-kicker rejection fixture. Distinguish kickoffs after scoring; these are not `half_start` kickoffs. The [updated canonical rules contract](docs/rules/NFL-2026-GAME-STATE-RULES.md) controls over older permissive comments about legal counterexamples. **Do not implement or authorize random exceptions.**

## NFL 2026 GAME-STATE RULES — 2026-10-24 (authoritative for E1/E2 work)

**Read [`docs/rules/NFL-2026-GAME-STATE-RULES.md`](docs/rules/NFL-2026-GAME-STATE-RULES.md) first.** It is the **single canonical LP↔Gridiron engineering rules reference**, grounded in the [official NFL 2026 rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook). NFL halves start with a kickoff determined by pregame toss choices/deferral and second-half privileges. **In normal simulated games, the opening receiver MUST kick off after halftime; the rare legal exception is excluded by the strict policy at the top of this file.** Q1→Q2 and Q3→Q4 change defended goals but **do not end the drive or cause kickoff**; Q2→Q3 ends the half and initiates a new kickoff after half-choice resolution. Team directions come from explicit **team × period** choices, not Q1/Q2=+1 for every offense or home/away. Maintain a persistent kickoff/coin-toss ledger; no inferred second-half receiver.

**Latest research status:** E1 `feat/nfl-sequence-e1-2026-10-24` [`b58a19f1`](https://github.com/micahp/legendarypicks/blob/b58a19f1350897b0ded2841bcf441e70a36449af/docs/SEQUENCE-E1-LP-DRIVE-2026-10-24.md) is pushed, with 4,396 **limited-checker** complete drives and 404 thin-cell failures from 4,800 attempts. Its heavy fourth-down-on-downs frequency (**2,075**) is sampler bias: no punt/FG decision model. No kickoff/score/halftime, no full NFL legality and retrospective outcomes only. E0 branch `166bb84f` documents a known touchdown-flag mismatch (not fixed). Continue **game-rule work** with toss/quarter/halftime transitions, punt/FG vs go-for-it, scoring and drive restarts. Do not conflate research fixture success with full-game compliance or future forecasting, and do not stall for E0b player-specific 3D replay.

## E1 AUTHORIZED — 2026-10-24: use correct NFL field ends

Read [coordinator field-direction decision](https://github.com/micahp/gridiron-physics/blob/main/docs/research/E0-FIELD-END-CONVENTION-DECISION-2026-10-24.md) and [shared delivery plan](https://github.com/micahp/gridiron-physics/blob/main/docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md). LP E0 at `693e1767` and Gridiron E0a at `15b0b34` agree on the new authored demo fixture. Q2 seed-1042 `dir=+1`, `los=12` is correct for the **explicitly authored presentation assignment** only. **The general formula all offenses +1 in Q1/Q2, −1 in Q3/Q4 is NOT NFL-correct**. Team ends flip between Q1/Q2 and Q3/Q4; halftime gets an explicit independent second-half choice. Implement a versioned **per-team/per-quarter** attacking-end mapping and transition tests in E1; do not derive direction from quarter alone or home/away. A possession change flips which team attacks but does not spontaneously move the absolute spot. Preserve source/mode label and LP event authority.

**LP sequence owner: START E1** as a research worktree now that E0a fixture transport is accepted and cross-repo fixture pin is confirmed. Focus on legal drive with clock, downs, spot, score, possession and drive endings, deterministic seed, labeled fallback and test coverage. **Do not wait for E0b** 3D participant-specific replay. Existing retrospective pool still cannot support an as-of prediction claim; keep as-of/roster gaps explicit. No push/merge/deploy without user approval under ordinary repo safety rules.

## E0a IMPLEMENTATION RECEIVED — 2026-10-24: LP signoff unlocks E1

Gridiron's [research E0a commit `629705da`](https://github.com/micahp/gridiron-physics/commit/629705da81bfc7baa75b9eb55137c9b4239ba07f) is pushed and independently inspected. It provides a working validator, read-only retrospective record viewer and focused tests; LP and Gridiron copies of seed-1042 fixture match byte-for-byte (Git blob SHA `c65a9b6699e2ca64b3e6312f9f5c64cc9e7a7a47`). **E0a is accepted for read-only demo transport**, not 3D physical replay or full `pregame_full_game` contract conformance. Read the [shared E0a gate decision](https://github.com/micahp/gridiron-physics/blob/main/docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md).

**LP sequence agent's next action:** Explicitly sign off on `single_play_statistical_demo`, `valid_full_game=false`, retrospective source labeling, no invented nulls, preserved LP outcome and state, strict unknown-event handling, and direction requiring a versioned field-end assignment (`dir=+1 → 100-yardline_100`; `dir=-1 → yardline_100`). After written acknowledgement, **start E1**: extend the authoritative LP reducer into a deterministic legal possession with clock/score/possession transitions and a valid drive-ending event; keep event types and missing metadata honest. Coordinate handoff to Gridiron E0b but **don't wait for 3D replay** to build drive logic. Source tests and viewer were inspected; server-side test execution is reported by the agent rather than independently reproduced by the coordinator. No merge, production DB write or service restart.

## E0 AGREEMENT UPDATE — 2026-10-24: acknowledge schema, unblock honest transport

Gridiron's [interface acceptance `83749b33`](https://github.com/micahp/gridiron-physics/blob/83749b33b9a3193fb87ac7a73583ad665621376a/docs/research/GRIDIRON-E0-ADAPTER-VIEWER-INVENTORY-2026-10-24.md) is committed and visible remotely. Read the [updated shared delivery-plan gate](https://github.com/micahp/gridiron-physics/blob/main/docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md): **E0a** is a truthful input-validator and retrospective state/outcome viewer, **not a fake 22-player replay**; **E0b** needs versioned field direction, actual eligible participant/roster identity and physical/visual context. LP sequence agent must explicitly acknowledge the demo envelope, null/error policy and `los` mapping (`dir=+1: 100-yardline_100`, `dir=-1: yardline_100`, otherwise unavailable). Keep LP record immutable and don't reinterpret it as completed `pregame_full_game` v1.

**After E0a adapter + joint schema signoff pass**, LP can start legal E1 drive/clock/score/possession work in parallel with E0b 3D playback prerequisites; E0 as originally scoped still needs honest actual replay. No broad new physics/Madden work, unapproved merge or production update. Gridiron's [M4d correction `433f944`](https://github.com/micahp/gridiron-physics/commit/433f944bc22f89bc568a489324a9df1baddf3b70) identifies the 99 supplemental blank-formation plays as **92 kneels / 7 spikes**, not special teams. Track these separately for future rules/clock evaluation, not in the canonical 9,289 movement cohort.

## E0 HANDOFF STATUS — 2026-10-24: pushed LP retrospective fixture

On `feat/nfl-sequence-e0-2026-10-24`, remote head [`853f46f4`](https://github.com/micahp/legendarypicks/blob/853f46f4c78c0edab8138ee4c713b35ac96b7336/docs/SEQUENCE-E0-LP-INVENTORY-2026-10-24.md) provides the seed-1042 single-play demo and reproducible transition tests. It is **not as-of eligible**, as 1,016/5,572 comparison-cell plays occur after the October 5, 2025 start game. The [shared E0 gate status and adapter contract issues](https://github.com/micahp/gridiron-physics/blob/main/docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md) are current: maintain `mode=single_play_statistical_demo`, `valid_full_game=false`, `sources_as_of_verified=false`, unknown clock/score/timeouts/participants, and immutable LP outcomes. The proposed v1 contract's full-game mode is **not yet satisfied**. LP sequence agent should await explicit hermes2 adapter/field-direction/missing-value agreement and a passing transport demo before implementing E1. No prod edits/merges.

Separately, [snap cohort reconciliation `23dfa70b`](https://github.com/micahp/legendarypicks/blob/23dfa70b563fd418ac216ab806a73f982362d0b1/docs/research/BDB2025-SNAP-COHORT-RECONCILIATION-2026-10-24.md) verifies 9,289 canonical plays, 99 extra **unknown-formation** plays in Gridiron (not confirmed special teams), and 68 LP exclusions outside its manifest (27 history, 24 blank formation, 17 snap definition). This supports movement research; it **does not block** E0/E1 game delivery.

## MOVEMENT RESEARCH STOP RULE — 2026-10-24

Read [the coordinator's movement-policy materiality decision](https://github.com/micahp/gridiron-physics/blob/main/docs/research/MOVEMENT-POLICY-MATERIALITY-DECISION-2026-10-24.md). Agent-reported snap-anchored results show the legacy controller beating same-history constant acceleration by only **3.72 mm at 1 s**, despite statistically passing the prior threshold-free prereg rule. **Do not build a more complex movement model or spend weeks 6–9 holdout on this controller now.** Keep the original prereg, per-play artifacts, and this **post-development** materiality policy distinct: a future policy must deliver ≥0.05 m AND ≥5% paired game-weighted 1-second MAE lift plus a game-clustered interval below zero, without meaningful coherence/performance regression.

LP tracking owner should reconcile **9,456 local manifest rows, 9,388 included snap plays, and 9,289 scored plays** by exact ID/eligibility *before* any further comparison, and preserve weeks 6–9 for a frozen confirmation at an appropriate time. Incoming research deliverables were reported **uncommitted/unpushed** and must not be described as verified GitHub results. LP sequence/reducer remains the **critical path E0–E2** for a complete generated game. Historical 2022 tracking / rights / provenance caveats still apply.

## ACTIVE TOP PRIORITY — 2026-10-24: finish an end-to-end NFL game simulator

**Required:** [Shared End-to-End Football Simulator Delivery Plan](https://github.com/micahp/gridiron-physics/blob/main/docs/END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md). It supersedes older *next-task* tracking/physics experiments but preserves their reports and all safety/verification/identity rules below.

**Deliverable:** A reproducible **hypothetical full game** using existing LP statistical play/drive/game generation as the outcome authority and Gridiron Physics' Three.js viewer as playback, with legal score/downs/distance/clock/possession and reconciled team + player statistics. Then test observed NFL play/drive/game distributions and eventual future forecast skill. **Statistical-script playback is not physically resolved football**; a physics/hybrid v2 is a separate experimental mechanism, not required to finish the first game.

**LP sequence agent is critical-path owner.** First inventory existing statistical sequence branches, run commands, reducer tests and the mirrored proposed `GRIDIRON-CONTRACT-v1.md` before coding. E0 = one generated play and immutable record consumed by Gridiron; E1 = one complete legal drive; E2 = complete game with all required rules or disclosed fallbacks, deterministic seed and score/player-stat reconciliation; E3 = distribution and later holdout forecasting tests. Own play/game state, event legality and player statistics. Do not make Gridiron silently pick the outcomes in v1 or change the mirrored v1 contract in only one repo.

**LP tracking/behavior agents are supporting, not blockers.** Preserve the completed 2022 Big Data Bowl tackle audit and 40-play conditional movement study. Continue a fair from-snap study only where it resolves a specific observed-play limitation in E3; do not delay E0–E2 for more centimeter-level motion or synthetic contact physics. Madden ratings and 3D tackle calibration remain research-only.

**Cross-agent handoff:** Deliver exact pinned play/game payload, source and code commits, pregame eligibility, reproducible run command, reducer assertions, clearly labeled sampled/physical/fallback mechanism and a versioned example to the Gridiron viewer owner. Publish one shared integration manifest and clear per-gate failures. Do not push, merge, restart services or modify production picks/grades/DB absent explicit approval.

## Current NFL simulation direction (2026-10-23; supersedes older next-task priorities)

The active cross-repository brief is [Gridiron Physics Football-first Agent Directive](https://github.com/micahp/gridiron-physics/blob/main/docs/FOOTBALL-FIRST-AGENT-DIRECTIVE-2026-10-23.md). Read it before working on NFL simulation, tracking, movement, game-state modeling or Madden ratings. Its **priorities** supersede older “next experiment” advice; existing `AGENTS.md` safety, verification, identity, ops and commit rules still apply.

**Optimize for observable NFL football, not self-generated synthetic physics benchmarks.** Prefer published tracking/models and existing Rapier/Jolt/movement systems. Stop broad new synthetic contact sweeps or 35/60-attribute Madden training until a specific real-play mismatch demonstrates the need. Keep past M4c/M4d/legacy failures and reports intact.

**Current handoff (2026-10-24):** The 2022-season Big Data Bowl 2025 nine-week tracking profile, tackler identity audit, and frozen [49-row manifest](https://github.com/micahp/legendarypicks/blob/c780bcc6/docs/research/bdb2025-observed-tackle-manifest-v1.csv) are completed and pushed at `c780bcc6`. The [Gridiron 40-play event-conditioned movement comparison](https://github.com/micahp/gridiron-physics/blob/b4ba357db66fa21222cd31a3b9cf7a70a5ce6956/research/physics-3d-evaluation/m4b/m4d/football-tracking-feasibility/results/observed-tackle-movement-2026-10-24/report.md) is pushed at `b4ba357`. **Do not restart their inventory or score that result as tackle prediction.** Read the [coordinator review](https://github.com/micahp/gridiron-physics/blob/main/docs/research/OBSERVED-FOOTBALL-MOVEMENT-REVIEW-2026-10-24.md). LP tracking owner next freezes a *new snap-anchored, all-22-player* cohort with no eventual tackle event, credited tackler, or post-snap data in prospective model input; preserve weeks 6–9 as model-evaluation holdout. Gridiron owner adds an equal-information constant-acceleration baseline, then evaluates existing movement response prospectively from snap. LP behavior/drive owner prepares fair independent observed-play and PBP comparisons. Keep rights and the 46 event-only / 92 unexplained label-only disagreements visible.

**LP owns** data/cutoff integrity, cheap kinematic + movement policy baselines, source-verified play outcomes and the NFL PBP sequence/drive evaluator. Gridiron owns execution and replay. Agree a stable research-only state/trajectory/play-result contract before touching shared files. Start with 5–10 correctly joined examples; expand to a preregistered 20–50-play development cohort *only when that ground truth exists*. Score trajectories, player spacing, play outcomes, drives and game distributions as distinct gates. Always include a cheaper statistical/hybrid baseline.

No LP live forecast/lock/grading updates, production writes, shared engine changes or unapproved merges. Coordinate through committed, hashed research manifests and one integrator, not unverified cross-agent status messages.

## Before you start
- Run `scripts/prior_art.py "<terms>"` before writing a new script or reporting a finding (0a).
- Load the skills in `.claude/skills/` for your task: `published-first` (anything derived, incl.
  schedules and join keys), `fail-loudly` (ingests, joins, best-effort steps), `falsify-before-merge`
  (before calling work done), `measurement-is-a-claim` (any number written down), `honest-data-ui`
  (any surface showing numbers), `resource-check` (batch work).
- Ask the two questions in order: does this code need to exist? Does this value need to be
  computed, or is it published somewhere (a definition always is)? (11)
- Live focus is NFL. World Cup code is dormant: do not touch it unless it blocks your task (0).
- Latest state: the newest `docs/CONTEXT-*.md` and any `docs/HANDOFF-*.md` for your area.

## Repo and servers (11, 12)
- `/root/legendarypicks` is the managed `dev` checkout serving :3096 and :8096. Work in your own
  worktree unless the change is small: `git worktree add /root/lp-<task> -b feat/<task> dev`. A small
  change may go directly on `dev` in this checkout. Never `git switch`; never
  `git checkout -- <path>`; never `git add -A` (stage named files); never push without Micah.
- Never run `npm`, `npx` or `yarn` from a worktree: its `node_modules` is a symlink to the main one
  and npm prunes it (took the site down 07-27). Use `/root/legendarypicks/node_modules/.bin/<tool>`.
  If `next: not found`, stop and report; recovery is `npm ci` in the main repo, by a human's call.
- Never start, kill or restart a dev server or the tunnel. Never `pkill` node or uvicorn.
- Box: 5.8 GB RAM, shared. Check `uptime` AND `free -h` before batch jobs; under ~1.5 GB available,
  do not start. Smallest unit first, single process, no hidden library parallelism. Verify a kill
  landed with `ps`. Do not run parallel worktree dev-server stacks.
- Prod is a docker stack with its own DB `backend/data/picks.db`. Read
  `docs/RUNBOOK-prod-promotion.md` before any promotion. Releases only via `scripts/release.sh`.

## Data (7, 11)
- Resolve identity before integrating sources. Join on stable ids, never names. A miss goes to the
  review queue, never a second `players` row. Merge duplicates only with `spine_merge.py`.
- Assert the id names the right person (`audit_league_stats.py` G/published-identity). Repair
  id-first, never by name match. Read a publisher's field semantics before mapping a column.
- After any ingest, reconcile the count with the publisher (`backend/reconcile_totals.py`); a
  missing oracle is a FAIL, not a skip.
- `docs/DATA-COVERAGE-CONTRACT.md` binds every surface: a missing row is `unknown`, not `missed`;
  season key is ESPN's start year; never guard on a column existing and then filter on its values.
- Do not live-scrape hostile endpoints (stats.nba.com blocks datacenter IPs). Use ESPN and published
  data releases (nflverse etc.).
- Heavy or optional libraries live in ingest scripts, never in request handlers. Persist to the DB;
  no in-memory caches as the source of truth. Serving reads the DB only, never ESPN per request.
- A comment saying data does not exist is a hypothesis: check it before building on it.

## Verifying (3, 4, 6, 11)
- Verify against the requirement and an independent source, never against the output of the code
  that produced it. HTTP 200 is not working: check non-empty real content and that the UI renders it.
- Reproduce before you fix: pin the exact surface, element, expected and actual.
- When you fix a bug, grep the codebase for the same pattern and fix or flag every instance.
- Follow `docs/DEV-STANDARDS.md`: a list must not download more than it renders; measure payloads.

## Frontend (1, 2, 5, 8, 9, 10)
- `components/Layout.tsx` owns the page shell. A page returns content only: no `min-h-screen`,
  `bg-*`, `text-zinc-100`, top-level `px-*`/`py-*`, or `max-w-*` except a deliberate narrower column.
- Two-tone is the design: page `bg-ink-900` (set by Layout), cards `bg-zinc-900`, skeletons
  `bg-zinc-800`. Never make page and card the same colour.
- Containers mark groups, never items (`docs/DESIGN-PRINCIPLES-containers-and-hierarchy.md`).
- Minimal diffs; copy an existing page's structure before adding wrappers.
- Extract strings from ESPN objects in the backend; never render an object as a React child. A new
  surface must load in a headless browser with zero page errors and real data, per league family.
- Search components own their open/close state. Mobile: `overflow-x-auto` with `min-w` cells
  instead of fixed `grid-cols-N`.
- Lint and type errors must not block a build. In-container API proxy targets the service name.

## Ops (6)
- Shared server, 8+ sites behind one nginx. `ss -tlnp` before choosing a port; bind 127.0.0.1.
- SQLite is a bind mount (`./backend/data:/app/data`), never a named volume; keep DBs out of images.
- `nginx -t` before every reload and check its exit code directly. Old nginx: `listen 443 ssl http2;`.
- certbot: use docker certbot with webroot, renewals scoped per cert.
- Finish and verify the primary task before peripheral work.

## Commits
- No AI attribution. Plain messages saying what and why. Do not commit `__pycache__` or `venv`.
