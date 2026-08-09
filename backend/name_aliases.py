#!/usr/bin/env python3
"""Name aliases for the published-identity gate, plus the consolidation log.

Two concerns, one module:

1. ``name-aliases.json`` — per publisher-id accepted alternate spellings.
   G/published-identity compares our stored row name to the name the id's own
   issuer publishes, folding only decoration (diacritics, case, suffixes,
   middle initials). That is strict on purpose: it exists to catch the wrong
   person, never a spelling. But publishers disagree on which name form is
   canonical — ESPN fantasy and Yahoo both publish 'Kenny Gainwell' while the
   legal form is Kenneth; hoopR publishes 'Jeenathan Williams' where ESPN
   publishes the nickname 'Nate'. The market-facing name is the nickname, so
   our rows keep it; the gate learns the accepted alternates from this file.

   The file is checked in, reviewed in diff, one entry per id, human-decided.

2. ``identity-consolidations.jsonl`` — append-only artifact recording every
   dedupe/merge/rename event. A consolidation without a log line is a defect.
"""

from __future__ import annotations

import json
import os
import unicodedata
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALIASES_PATH = HERE / "data" / "name-aliases.json"
CONSOLIDATIONS_PATH = HERE / "data" / "identity-consolidations.jsonl"

_ALIASES_CACHE: dict | None = None


def _identity_name_key(name):
    """Mirror audit_league_stats._identity_name_key so alias matching compares
    the same way the gate does (decoration folded, people not folded)."""
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^a-z ]", "", folded.lower())
    folded = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", folded)
    folded = re.sub(r"\b[a-z]\b", "", folded)
    return " ".join(folded.split())


def load_aliases() -> dict:
    """Read the alias map once. Shape: {league: {id: [normalized aliases]}}."""
    global _ALIASES_CACHE
    if _ALIASES_CACHE is not None:
        return _ALIASES_CACHE
    if not ALIASES_PATH.exists():
        _ALIASES_CACHE = {}
        return _ALIASES_CACHE
    with open(ALIASES_PATH) as f:
        data = json.load(f)
    # Normalize aliases to gate-comparison form at load so callers can compare
    # with a plain == against _identity_name_key(row_name).
    out = {}
    for league, ids in data.items():
        out[league] = {
            str(eid): {_identity_name_key(a) for a in names}
            for eid, names in ids.items()
        }
    _ALIASES_CACHE = out
    return out


def aliases_for(league: str, ext_id) -> set[str]:
    """Normalized accepted alternate spellings for one publisher id."""
    return load_aliases().get(league, {}).get(str(ext_id), set())


def matches_published(league: str, ext_id, row_name: str, published_name: str) -> bool:
    """True when row_name is the publisher's name or a recorded alias for the id.

    The gate calls this only after the strict comparison already failed — the
    point is to admit a known same-person spelling without ever admitting a
    different person (which the file's absence of an entry prevents). The
    alias file lists BOTH accepted forms of the name (market-facing and
    publisher-legal), so whichever side a row holds, it passes.
    """
    if _identity_name_key(published_name) == _identity_name_key(row_name):
        return True
    return _identity_name_key(row_name) in aliases_for(league, ext_id)


def record_consolidation(entry: dict) -> Path:
    """Append one JSONL line to the consolidation artifact. Never truncates."""
    CONSOLIDATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONSOLIDATIONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return CONSOLIDATIONS_PATH
