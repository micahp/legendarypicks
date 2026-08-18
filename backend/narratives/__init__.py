#!/usr/bin/env python3
"""narratives — AI-generated league conversations package.

This package splits the narrative generation pipeline from the original
ingest_league_narratives.py into modules by concern.

Public API matches the original module: callers can `import narratives`
and find every name they used to rely on.
"""
from .constants import (
    _MAX_SOURCES,
    _MIN_ITEMS,
    _BATCH_MAX_TOKENS,
    _SINGLE_MAX_TOKENS,
    _BATCH_CHUNK,
    _ANCHORS,
    _TIE_ALARM,
    _MIN_TOPIC_LEN,
    _GENERIC_WORDS,
    _STOPWORDS,
)
from .topic_words import _norm_url, _norm_words, _significant, _topic_words, _topic_hits
from .anchor_routing import _better_home

__all__ = [
    "_MAX_SOURCES",
    "_MIN_ITEMS",
    "_BATCH_MAX_TOKENS",
    "_SINGLE_MAX_TOKENS",
    "_BATCH_CHUNK",
    "_ANCHORS",
    "_TIE_ALARM",
    "_MIN_TOPIC_LEN",
    "_GENERIC_WORDS",
    "_STOPWORDS",
    "_norm_url",
    "_norm_words",
    "_significant",
    "_topic_words",
    "_topic_hits",
    "_better_home",
]
