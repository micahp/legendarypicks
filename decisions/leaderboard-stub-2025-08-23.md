### [Decision 1]: Add contest leaderboard UI stub (no payouts yet)
**Timestamp (UTC):** 2025-08-23T00:00:00Z
**Scope:** `components/ContestLeaderboard.tsx`, `components/ContestEntry.tsx`,
`CONTEXT-2025-08-23.md`
**Change Summary:** Implemented a basic leaderboard component and mounted it on the Contest Entry
screen. It displays placeholder rows and is intended to be backed by live scoring hooks later.
**Rationale:** Gives users immediate visibility into standings and creates a clear integration
point for wiring score updates without blocking on payout mechanics.
**Alternatives Considered:**
  - Wait for backend scoring to be complete — rejected; reduces feedback and UI progress.
  - On-chain-only leaderboard — deferred; higher complexity before data ingestion is wired.
**Trade-offs / Risks:**
  - Placeholder data may confuse users; label clearly and keep visual distinction.
  - Risk of UI churn as scoring events are integrated; keep component small and focused.
**Follow-ups / TODOs:**
  - Wire to score updates from API/contract events and show timestamps.
  - Add pagination if entries exceed viewport.
  - Integrate basic participant address shortener and avatar later.
**Source Prompt(s):**
  - "1 yes. 2. on chain ownership verification at lock time. 3. nba_api 4. leaderboard only for now."


