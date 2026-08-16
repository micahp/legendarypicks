# Legendary Picks

Legendary Picks is a sports data and prediction product for following live games, player performance, props, league standings, and esports.

This repository began as an FCL / NBA Top Shot experiment. NBA Top Shot moved into the core product space, so Legendary Picks pivoted away from that dependency and became an independent, data-first sports product. The old Flow setup is historical scaffolding, not the product architecture or a supported development path.

## Architecture

```text
Publishers and data releases
        |
        v
Ingest scripts (the only data writers)
        |
        v
SQLite canonical data store
        |
        v
FastAPI /api/*
        |
        v
Next.js application
```

The browser request path is database-backed. It must not scrape ESPN, load large data libraries, or construct replacement data on demand. Source collection belongs in explicit ingest jobs; the UI and API serve published or last-known-good data honestly.

## Repository map

| Location | Responsibility |
| --- | --- |
| `pages/` | Next.js routes: scores, game detail, leagues, players, props, esports, and NFL tools. |
| `components/` | Reusable UI, including score cards, game-detail tabs, league desks, props, and mock draft. |
| `services/sports.ts` | Frontend client for the FastAPI contract. |
| `backend/sports_service.py` | FastAPI application shell; mounts the focused API routers. |
| `backend/routers/` | API endpoints for games, players, props, analytics, news, esports, and league-specific features. |
| `backend/_core.py` | Shared DB access, models, helpers, and API contracts. |
| `backend/ingest_*.py` | Explicit source-to-database ingestion jobs. |
| `backend/data/` | SQLite databases and checked data artifacts. Databases are never baked into an image. |
| `docs/` | Product specifications, runbooks, data contracts, migration plans, and handoffs. |

## Development

The normal development stack is Next.js plus FastAPI:

```bash
# Terminal 1 — from the repository root
npm run dev

# Terminal 2 — backend dependencies live in the project virtualenv
cd backend
venv/bin/python -m uvicorn sports_service:app --reload
```

The frontend proxies `/api/*` through `API_PROXY_TARGET`; use the environment configuration for the active stack rather than hardcoding a backend host in browser code.

For managed development, the shared `dev` worktree normally serves the frontend on `:3096` and backend on `:8096`. Production is a separate Docker Compose stack, normally `:3100` and `:8100`. Do not restart, deploy, or migrate either environment as part of ordinary feature work.

## Data and release rules

- Ingest scripts are the only database writers. API handlers and pages are read-only consumers.
- Resolve people, teams, and games using stable source IDs—not display names. Unresolved records go to review; they are not silently duplicated or discarded.
- Code and data promotion are separate steps. A successful build or HTTP 200 does not prove a page has real data.
- Verify a change in the rendered route and against an independent source where correctness matters.
- Keep feature work in an isolated `/root/lp-*` worktree. Preserve concurrent WIP and stage only the intended paths.

## Key documents

- [`ORIENTATION.md`](ORIENTATION.md) — current architecture and safe onboarding path.
- [`AGENTS.md`](AGENTS.md) — mandatory engineering, UI, data, and operations rules.
- [`docs/RUNBOOK-prod-promotion.md`](docs/RUNBOOK-prod-promotion.md) — required procedure before a production promotion.
- [`docs/IDENTITY-SPINE-STATE.md`](docs/IDENTITY-SPINE-STATE.md) — canonical player identity status and safeguards.
- [`docs/SPEC-player-identity-spine.md`](docs/SPEC-player-identity-spine.md) — identity model and migration design.

## Testing

Run focused tests for the surface you change. Backend tests use the backend virtualenv; frontend tests use Jest from the repository root. Before declaring a feature complete, check the real API payload and render the corresponding page in a browser.
