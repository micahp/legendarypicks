### [Decision 1]: NBA fantasy scoring weights for MVP
**Timestamp (UTC):** 2025-08-23T00:00:00Z
**Scope:** `backend/nba_service.py`, `CONTEXT-2025-08-23.md`
**Change Summary:** Set fantasy scoring weights to Points=1.0, Rebounds=1.2, Assists=1.5,
Steals=3.0, Blocks=3.0, Turnovers=−1.0 in the FastAPI service. This provides a clear baseline for
leaderboard calculations in the MVP.
**Rationale:** Aligns with the confirmed simple scoring choice to accelerate delivery. The weights
are easy to reason about, cheap to compute, and can be parameterized later without changing the UI.
**Alternatives Considered:**
  - Richer scoring (double-double/triple-double bonuses) — deferred to avoid scope creep now.
  - Provider-specific fantasy outputs — rejected to keep control and consistency.
**Trade-offs / Risks:**
  - Mapping indices from nba_api responses may change; add tests to lock correctness.
  - Community preference for different weights; expose via config in the future.
**Follow-ups / TODOs:**
  - Unit tests to validate stat index mapping and totals.
  - Extract weights to config/env for quick iteration.
  - Mirror or translate weights if scoring is moved on-chain later.
**Source Prompt(s):**
  - "1 yes. 2. on chain ownership verification at lock time. 3. nba_api 4. leaderboard only for now."


