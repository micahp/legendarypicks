# Project Context Summary (updated 2025-02-14)

## Purpose
Legendary Picks – Flow-based fantasy platform.  Core goals:
• Show users their NBA Top Shot moments (via account-linking/HybridCustody).
• Display today’s (and past) sports games and allow line-up/contest creation.
• Contests backed by `LegendaryPicksContest` Cadence contract.

## Current stack
| Layer | What is used |
|-------|--------------|
| Flow  | FCL (config/fcl.ts), `LegendaryPicksContest.cdc`, Top Shot scripts, HybridCustody for account linking |
| Frontend | Next.js 13, Tailwind, React Query-style fetch helpers (services/**) |
| Backend sports data | ① FastAPI `nba_service.py` using `nba_api` **OR** ② Next.js proxy in `/api/nba/games` (SportsData.io) |

## Key Components
- `pages/index.tsx`   – landing, sticky header, wallet connect.
- `components/GameBrowser.tsx` – single-day NBA games card grid.
- `pages/scores.tsx`  – new Scores page with date-picker (NBA only for now).
- `services/nbaGames.ts` – helpers: `getTodaysGames`, `getGamesByDate`.
- `backend/nba_service.py` – FastAPI routes `/api/games/today` etc.
- `pages/api/nba/games` *(proxy alternative)* – server proxy to SportsData.io.
- Contest scaffolding (`ContestCreator`, `ContestBrowser`, contract).

## Environment vars
```
NEXT_PUBLIC_FLOW_NETWORK=mainnet | local
NEXT_PUBLIC_ACCESS_NODE_API=...rest-mainnet...
NEXT_PUBLIC_NBA_API_URL=/api       # or http://localhost:8000/api when using FastAPI backend
NEXT_PUBLIC_WALLETCONNECT_ID=<id>
SPORTSDATA_KEY=<sportsdata.io key> # only for Next.js proxy
```

## Dev scripts (package.json)
- `yarn dev:mainnet` – start Next on mainnet.
- `yarn dev:sports-backend` – start FastAPI backend (requires venv).
- `yarn dev` – local network (needs Flow emulator running).

## Outstanding work
1. Decide single sports-data source (FastAPI vs proxy) and clean scripts.
2. Build roster/player stats endpoints & UI.
3. Finish account-linking Moments gallery (`DisplayLinkedNFTs`).
4. Wire contest creation & entry to on-chain contract.
5. Optional DB caching layer for sports data.

---
