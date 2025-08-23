### [Decision 1]: Default NBA data provider to `nba_api` via FastAPI proxy
**Timestamp (UTC):** 2025-08-23T00:00:00Z
**Scope:** `pages/api/nba/games.ts`, `pages/scores.tsx`, `CONTEXT-2025-08-23.md`
**Change Summary:** Defaulted the NBA provider to `nba_api` (proxied through FastAPI) when no
explicit provider is supplied. The provider switch remains available to flip between `sportsdata`
and `nba_api` at runtime. The UI initializes to `nba_api` by default.
**Rationale:** Minimizes cost and avoids paid API dependencies for the MVP while preserving the
ability to switch to SportsData.io when a key is available. Keeps schemas normalized through the
Next API so UI does not need to react to upstream differences.
**Alternatives Considered:**
  - Default to `sportsdata` — rejected due to cost and key management for early MVP.
  - Client-only switching — rejected; would expose keys and increase UI complexity.
**Trade-offs / Risks:**
  - nba_api rate limits or instability; mitigated by retaining provider switch to SportsData.
  - Upstream schema drift; mitigated by centralized normalization in the API route.
**Follow-ups / TODOs:**
  - Add simple circuit breaker/health check for provider selection.
  - Document `NBA_PROVIDER` and `NEXT_PUBLIC_NBA_API_URL` in README.
  - Telemetry for provider errors to inform auto-fallback.
**Source Prompt(s):**
  - "1 yes. 2. on chain ownership verification at lock time. 3. nba_api 4. leaderboard only for now."


