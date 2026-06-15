# HANDOFF → DeepSeek (2026-06-15): COMPREHENSIVE fix of the data-not-loading / wrong-host issue

Read AGENTS.md first — especially the **Guiding principle** (verify against ground truth, the whole,
not a proxy) and **§4 (when you fix a bug, sweep for the same mistake EVERYWHERE)**. This task is
explicitly about doing that sweep — piecemeal hot-patches are NOT acceptable.

## The issue (still open)
Pages showed no data because frontend data-fetches pointed at `http://localhost:8000` (the user's own
machine) instead of the relative `/api` that nginx proxies to the backend. Root cause: an env-var
**name mismatch** — code read `NEXT_PUBLIC_SPORTS_API_URL` but the build only set
`NEXT_PUBLIC_API_BASE`, so the `localhost:8000` fallback kicked in.

Already patched by Claude (do NOT undo): `services/sports.ts` fallback → `/api`; build args + Dockerfile
now set `NEXT_PUBLIC_SPORTS_API_URL=/api`; a broken-JSX build (escaped quotes `desc=\"...\"`) fixed.

But it is NOT comprehensive. `localhost:8000` still remains in at least `pages/api/nba/games.ts`
(used by `services/nbaGames.ts` / the unused `GameBrowser`), `.next/server/chunks`, etc.

## Do this — comprehensively
1. **Sweep the entire frontend** for every data-fetch base/host, not just the known spots:
   ```
   grep -rnE "localhost:8000|127.0.0.1:8000|http://|axios.create|baseURL|NEXT_PUBLIC_(API_BASE|SPORTS_API_URL)" pages/ components/ services/ lib/ utils/
   ```
2. **Standardize ONE convention** everywhere:
   - **Client-side** fetches (browser): relative **`/api/...`** (same-origin → nginx → backend). No hosts.
   - **Next.js API routes** (`pages/api/*`, server-side in the frontend container): use the compose
     service **`http://backend:8000`** via env (`API_PROXY_TARGET`), never `localhost:8000`.
   - If a path is dead (the NBA `GameBrowser`/`nbaGames.ts`/`pages/api/nba/games.ts` look unused), DELETE
     it rather than leave a wrong-host landmine.
3. **One source of truth** for the API base — don't have two env var names. Pick one, set it in the
   Dockerfile ARG/ENV + docker-compose build args, and make every caller use it (or relative `/api`).

## Discipline (you violated these — fix the habit)
- **BUILD before you commit.** You committed JSX that doesn't compile (escaped quotes). Run the build
  (`docker compose build frontend` → must say "Compiled successfully") BEFORE every commit. A commit
  that doesn't build is worse than no commit.
- **Verify against ground truth, not a 200.** After deploying, confirm each page actually RENDERS DATA
  (scores shows games, props shows lines, performance shows stats) — not just that the route returns 200.
- Don't touch Claude's committed fixes (sports.ts /api, props.tsx escaped-quote fix, the deploy config).

## Deliverable
The grep above returns ZERO wrong-host hits in source; build compiles; every data page renders real
data. Write before/after grep results + which files changed to
`docs/HANDOFF-deepseek-to-claude-other-leagues-2026-06-15.md` and ping.
