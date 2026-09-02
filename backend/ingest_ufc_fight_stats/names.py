"""Name-normalization helpers for UFC fighter matching."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import List, Optional

def _name_key(value: Optional[str]) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())

def _name_parts(value: Optional[str]) -> List[str]:
    ascii_value = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.findall(r"[a-z0-9]+", ascii_value.lower())

def _parse_date(value: Optional[str]) -> Optional[dt.date]:
    try:
        return dt.datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

def _opponent_for(player_name: str, home: Optional[str], away: Optional[str]) -> Optional[str]:
    player_key = _name_key(player_name)
    if player_key and player_key == _name_key(home):
        return away
    if player_key and player_key == _name_key(away):
        return home
    return None
