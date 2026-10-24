# AGENTS.md: read this before editing legendarypicks

These are the rules, short. Each comes from a real incident; the incident, the measurements and
the examples are in [docs/AGENTS-REFERENCE.md](docs/AGENTS-REFERENCE.md) (the full previous text,
section numbers unchanged). Read the matching section there when a rule touches your task.

**Guiding principle.** Before trusting a result, define what "correct and complete" requires, then
verify against ground truth: the whole population, the real data, an independent source. Assume a
gap remains until you have measured it.

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
