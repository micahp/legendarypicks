#!/usr/bin/env python3
"""sports_service.py — unified multi-league sports API (ESPN-backed) + prediction store.

ONE service. Replaces the old sportsipy-based `sports_service` and the NBA-only `nba_service`
(now a deprecation stub). All data flows through espn_client (free, reliable, every league).

This file is the thin app shell. As of the 2026-06-27 refactor the routes live in
routers/ (games, players, props, analytics, game_extras) and the shared DB/helpers/models
live in _core.py. See docs/RETRO-2026-06-27.md for why the 2125-line god-file was split.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import espn_client as espn
from _core import ALLOWED_ORIGINS
from routers import games, players, props, analytics, game_extras, esports

app = FastAPI(title="Legendary Picks Sports API", description="Multi-league sports data (ESPN)", version="2.0.0")
print(f"DEBUG: espn_client leagues: {sorted(espn.LEAGUES)}")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(games.router)
app.include_router(players.router)
app.include_router(props.router)
app.include_router(analytics.router)
app.include_router(game_extras.router)
app.include_router(esports.router)
