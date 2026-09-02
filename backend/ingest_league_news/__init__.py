"""ingest_league_news — collect + classify league news into `news_items`.

Out-of-band collection path (never per-pageview). Sources (all verified
2026-08-06, see docs/PLAN-league-news-engine.md):

  - ESPN news API      1 req per league (nfl, baseball/mlb, soccer/usa.1, football/college-football)
  - Deadspin RSS       https://deadspin.com/rss/
  - Awful Announcing   https://www.awfulannouncing.com/feed
  - FanSided           https://fansided.com/feed/
  - SB Nation          https://www.sbnation.com/rss/index.xml
  - Bluesky search     https://api.bsky.app/xrpc/app.bsky.feed.searchPosts
  - X timelines        https://nitter.net/{handle}/rss — 17 accounts, see
                       X_ACCOUNTS below and PLAN §2.1 for why each one is on
                       the list and what it scored. Timelines only; Nitter's
                       search returns an empty document.

Two cadences. The full run (this file, no flags) is nightly. `--x-only` is the
fast lane every 2 hours: the X feeds hold ~6 hours at current post rates, so a
daily run would miss most of them.

ESPN requests go through the shared paced_http Fetcher (espn-request-budget
doctrine §4: one home for pacing, per-host budget and disk cache; re-runs
inside the cache TTL cost zero requests). host_budget=20: refuse early, never
discover the wall.

Usage:
  LP_DB_PATH=/path/to/db python3 ingest_league_news.py            # all leagues
  python3 ingest_league_news.py --leagues nfl,mlb --no-espn        # subset
  python3 ingest_league_news.py --dry-run                          # collect+classify, no write
  python3 ingest_league_news.py --x-only                           # X timelines only (2-hourly)
  python3 ingest_league_news.py --reclassify                       # re-run the classifier, no network
  python3 ingest_league_news.py --repair-text                      # re-clean stored text + dates
  python3 ingest_league_news.py --sync-conversations               # code defaults -> DB
  python3 ingest_league_news.py --ingest-story <espn-url|id>       # one article, full body

Split from the former single-file ingest_league_news.py (2026-08-18) into
modules by concern: conversations, creds, fetch, trending, collect, store,
cli. The package re-exports the full external surface the module did — callers
that did `from ingest_league_news import CONVERSATIONS` (or anything else)
keep working unchanged. `python3 -m ingest_league_news` runs the same CLI, and
backend/ingest_league_news.py remains as a shim for the existing entry point.
"""
import argparse
import datetime
import email.utils
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# Same role the single-file module's preamble served: make backend/ importable
# so paced_http, news_classifier and _core resolve regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paced_http import Fetcher  # noqa: E402
from news_classifier import classify, entities  # noqa: E402

from .cli import main  # noqa: E402
from .collect import (  # noqa: E402
    ALL_BLUESKY_QUERIES,
    BLUESKY_SEARCH,
    GOOGLE_NEWS_RSS,
    NITTER_INSTANCES,
    OPEN_QUERIES,
    X_ACCOUNTS,
    X_SEARCH,
    _BLUE_FETCHER,
    _GNEWS_FETCHER,
    _OPEN_LEAGUES,
    _X_FETCHER,
    collect_bluesky,
    collect_news_search,
    collect_x,
    collect_x_search,
    tag_conversations,
)
from .conversations import (  # noqa: E402
    CONVERSATION_QUERIES,
    CONVERSATIONS,
    _DEFAULT_CONVERSATIONS,
    _TEXTURE_DIMENSIONS,
    _conversation_queries,
    load_conversations,
    sync_conversations,
)
from .creds import (  # noqa: E402
    BLUESKY_PDS,
    _BSKY_GIVE_UP,
    _BSKY_HANDLE_KEYS,
    _BSKY_PASS_KEYS,
    _BSKY_TOKEN,
    _bsky_credential,
    _bsky_token,
    _env_or_hermes,
    _x_key,
)
from .fetch import (  # noqa: E402
    CACHE_DIR,
    ESPN_NEWS,
    RSS_FEEDS,
    UA,
    _ESPN_FETCHER,
    _ESPN_LEAGUE_HINT,
    _STORY_API,
    _STORY_ID_RE,
    _TAG_RE,
    _clean,
    _http_text,
    _iso,
    collect_espn,
    collect_rss,
    fetch_espn_story,
)
from .store import reclassify_existing, repair_stored_text, upsert  # noqa: E402
from .trending import trending_queries  # noqa: E402
