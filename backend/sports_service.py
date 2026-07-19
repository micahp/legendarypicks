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
import os


# --- esports API keys: self-hydrate BEFORE importing routers ------------------------------------
# Esports data (PandaScore/GRID/YouTube) silently degrades if this process is launched without its
# API keys — e.g. `npm run dev:backend`, which does NOT source them. On 2026-07-13 a keyless dev
# relaunch dropped every scheduled-match logo (PandaScore enrichment carries them) with no error.
# Make the app self-sufficient: fill any MISSING key from the dev secrets file if it exists (a no-op
# in the prod container, where that file is absent and keys arrive via compose env), then log
# presence loudly so a degraded launch is never silent again. Must run before `from routers ...`
# because routers/esports/grid.py reads GRID_API_KEY at IMPORT time.
def _hydrate_esports_keys():
    keys = ("PANDASCORE_API_KEY", "GRID_API_KEY", "YOUTUBE_API_KEY", "DEEPSEEK_API_KEY")
    envfile = "/root/.hermes/.env"
    if any(not os.environ.get(k) for k in keys) and os.path.exists(envfile):
        try:
            with open(envfile) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    if k.strip() in keys and not os.environ.get(k.strip()):
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass
    missing = [k for k in keys if not os.environ.get(k)]
    print(f"ESPORTS KEYS: present={[k for k in keys if os.environ.get(k)]} missing={missing}")
    if missing:
        print("=" * 72)
        print(f"WARNING  ESPORTS DEGRADED — missing {missing}. Scheduled-match logos and live "
              f"PandaScore/GRID surfacing will be ABSENT. Source keys before launch.")
        print("=" * 72)


_hydrate_esports_keys()

import espn_client as espn  # noqa: E402  (must import after key hydration; grid.py reads its key at import)
from _core import ALLOWED_ORIGINS, _normalize_name  # noqa: E402  (_normalize_name re-exported for ingest scripts)
from routers import (  # noqa: E402
    games,
    players,
    props,
    analytics,
    game_extras,
    esports,
    live_discounts,
    momentum,
    plays,
    ufc_picks,
)

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
app.include_router(live_discounts.router)
app.include_router(momentum.router)
app.include_router(plays.router)
app.include_router(ufc_picks.router)


@app.on_event("startup")
def _start_background_warmers():
    # Keep the lazily-cached esports board fresh without depending on organic traffic (prod has ~0).
    # No-op unless enabled — see routers/esports/slate.ESPORTS_WARMER_INTERVAL_S.
    esports.slate.start_esports_warmer()
