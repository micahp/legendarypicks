# AGENTS.md: read this before editing legendarypicks

These are the rules, short. Each comes from a real incident; the incident, the measurements and
the examples are in [docs/AGENTS-REFERENCE.md](docs/AGENTS-REFERENCE.md) (the full previous text,
section numbers unchanged). Read the matching section there when a rule touches your task.

**Guiding principle.** Before trusting a result, define what "correct and complete" requires, then
verify against ground truth: the whole population, the real data, an independent source. Assume a
gap remains until you have measured it.

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
