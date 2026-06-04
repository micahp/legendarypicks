#!/usr/bin/env python3
"""nba_service.py — DEPRECATED.

This NBA-only FastAPI app (built on nba_api) was merged into the unified, multi-league
`sports_service.py`, which is ESPN-backed and covers NBA/WNBA/NHL/MLB/NFL with one service,
real data, and persisted predictions. It also bound the same port (8000) as sports_service,
so the two could never run together.

Run instead:
    uvicorn sports_service:app --host 0.0.0.0 --port 8000
    # NBA games today:        GET /api/nba/games
    # team quality ranking:   GET /api/nba/strength

NBA-specific advanced stats (nba_api) can be reintroduced as a router on the unified app if a
feature actually needs them; until then there's no reason to keep a second competing service.
The original implementation remains in git history.
"""
import sys

if __name__ == "__main__":
    sys.exit("nba_service is deprecated — use: uvicorn sports_service:app --port 8000  (see module docstring)")
