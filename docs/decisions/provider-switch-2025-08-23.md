### [Decision 1]: Centralize NBA provider switching via API route
**Timestamp (UTC):** 2025-08-23T00:00:00Z
**Scope:** `pages/api/nba/games.ts`, `services/nbaGames.ts`, `backend/nba_service.py`
**Change Summary:** Added provider switch in Next.js API to toggle between SportsData.io and a free FastAPI backend using `nba_api`, with retry and 60s cache for SportsData. Frontend calls the centralized route with `provider` param.
**Rationale:** Avoid vendor lock-in and rate-limit issues; simplify UI by centralizing selection and normalization.
**Alternatives Considered:**
  - Client-side switching — rejected to avoid exposing keys and duplicating logic.
  - SportsData-only — rejected due to rate limits/cost.
**Trade-offs / Risks:**
  - Slight added latency when proxying; need to maintain two mappers.
**Follow-ups / TODOs:**
  - Add more free providers behind the same interface.
**Source Prompt(s):** provider switching and free option request.
