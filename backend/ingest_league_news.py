#!/usr/bin/env python3
"""Shim for the league-news collector.

The collector now lives in the `ingest_league_news/` package (split 2026-08-18,
same refactor as ingest_league_narratives). This file exists so the existing
entry point — `python3 ingest_league_news.py`, used by scripts/news-collect.sh
and scripts/news-x-collect.sh — keeps working unchanged. `python3 -m
ingest_league_news` is the equivalent package invocation.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_league_news.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
