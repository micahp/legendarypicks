# PRD: Multi-League Scoreboard Transformation

## 1. Overview
The current Scoreboard page (`/scores`) is hardcoded to only display NBA games. To align with our unified backend and trading goals, we need to transform this into a multi-league dashboard. This page will serve as the "Command Center" for both manual observation and tracking our automated paper trading collectors.

## 2. Objective
Update the `/scores` page to aggregate and display live/scheduled games for:
- **Major Leagues**: NBA, NFL, NHL, MLB (replacing old 'MOB' typo).
- **Tennis**: ATP, WTA.
- **Esports**: Call of Duty (COD).

## 3. Functional Requirements

### 3.1 Aggregate Game List
- The main view should display **all** active games for the selected date across all supported leagues.
- **Section Headers**: Games must be grouped by league. Each league section should have a clear, styled header (e.g., "NBA", "Call of Duty").
- **Ordering**: 
    1. Status (LIVE first, then SCHEDULED, then FINAL).
    2. League priority (NBA > MLB > NHL > NFL > COD > ATP > WTA).

### 3.2 League Filtering
- **Dropdown Filter**: A new dropdown menu in the header to filter the list by a specific league (Default: "All Leagues").
- **Supported Filter Options**: All, NBA, MLB, NHL, NFL, ATP, WTA, Call of Duty.

### 3.3 Data Integration
- **Unified Backend**: Fetch data from `sports_service:8000`.
- **New Service Methods**: Update `NBAGameService` (or create a new `UnifiedGameService`) to handle multi-league requests.
- **Tennis/Esports Support**: Integrate the same logic used in the `prediction-market-trading` repo for tracking ATP/WTA and COD markets, potentially through a specialized endpoint if ESPN doesn't cover them.

### 3.4 UI/UX Enhancements
- **Game Cards**: Maintain the existing `GameCard` style but add a league-specific icon or tag if the view is "All Leagues".
- **Empty States**: If a specific league has no games for the selected date, hide that section (or show a "No games" message only if that specific league is filtered).

## 4. Technical Specifications
- **Frontend**: Next.js (TypeScript), Tailwind CSS.
- **State Management**: React `useState` for the `filter` and `games` array.
- **Backend**: FastAPI (Python) - Ensure `sports_service.py` supports the new categories or proxies them correctly.

## 5. Success Metrics
- 100% parity between backend API results and UI display.
- Seamless league switching with zero page reloads (client-side filtering).
- Accurate rendering of "Call of Duty" match states (which lack ESPN PBP).
