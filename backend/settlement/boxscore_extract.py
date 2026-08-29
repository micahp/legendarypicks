#!/usr/bin/env python3
"""boxscore_extract.py — read a single stat for a player from an ESPN boxscore."""
from typing import Optional, List


def _norm_name(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — so "Michael Porter Jr."
    and "michael porter jr" are the same name and nothing else is."""
    return " ".join("".join(c for c in (text or "").lower() if c.isalnum() or c.isspace()).split())


def _find_player_stat(boxscore: dict, player_name: str, team: str,
                       category: str, stat_key: str,
                       espn_id: Optional[str] = None) -> Optional[float]:
    """Extract a single stat for a player from ESPN's boxscore JSON.

    Identity, exact key first — ESPN publishes `athlete.id` on the same object as
    the stats, so there is no name to match:

      1. `espn_id` against `athlete.id`. Absent from the box score means the player
         did not appear: a void, not a licence to guess.
      2. No espn_id on our row: exact name match after normalising case,
         punctuation and whitespace.
      3. Two athletes answering to the same name: void.

    The ESPN boxscore structure:
      boxscore.players[team_abbrev] = {
        "team": {...},
        "statistics": [{"name": "batting", "athletes": [
          {"athlete": {"displayName": ...}, "stats": ["AB", "R", "H", ...]},
          ...
        ]}]
      }
    Returns the stat value as float, or None if player not found / DNP.
    """
    if not boxscore:
        return None
    players = boxscore.get("players", [])
    if not players:
        return None

    # Team abbreviation aliases (ESPN sometimes uses different abbrevs than our data)
    _TEAM_ALIASES = {
        "WAS": "WSH", "WSH": "WAS",  # Washington
        "ATH": "OAK", "OAK": "ATH",  # Athletics
        "LAL": "LAL", "LAC": "LAC",  # LA teams
        "TB": "TB", "TBL": "TB",     # Tampa Bay
        "ARI": "ARI", "AZ": "ARI",   # Arizona
    }

    # ESPN MLB boxscore label sets (used to identify stat group when name is None)
    _BATTING_ONLY = {'AB', 'R', 'H', 'RBI', 'HR', 'BB', 'K', 'AVG', 'OBP', 'SLG', 'H-AB', '#P', 'TB', '2B', '3B', 'SB', 'CS'} - {'IP', 'H', 'R', 'ER', 'BB', 'K', 'HR', 'ERA', 'PC-ST', 'PC', 'SO', 'outs', 'BF'}
    _PITCHING_ONLY = {'IP', 'H', 'R', 'ER', 'BB', 'K', 'HR', 'ERA', 'PC-ST', 'PC', 'SO', 'outs', 'BF'} - {'AB', 'R', 'H', 'RBI', 'HR', 'BB', 'K', 'AVG', 'OBP', 'SLG', 'H-AB', '#P', 'TB', '2B', '3B', 'SB', 'CS'}

    for team_group in players:
        tg_team = (team_group.get("team") or {}).get("abbreviation", "")
        tg_upper = tg_team.upper()
        team_upper = team.upper()
        if tg_upper != team_upper and _TEAM_ALIASES.get(tg_upper) != team_upper:
            tg_name = (team_group.get("team") or {}).get("displayName", "")
            tg_short = (team_group.get("team") or {}).get("shortDisplayName", "")
            # A durable ESPN athlete id is globally scoped and stronger than a
            # team abbreviation. This matters in college football, where our
            # canonical school code and the boxscore abbreviation can differ.
            if (not espn_id
                    and team.upper() not in (
                        tg_upper, tg_name.upper(), tg_short.upper())):
                continue

        for stats_group in team_group.get("statistics", []):
            stats_name = (stats_group.get("name") or "")
            labels = stats_group.get("labels") or []
            label_set = set(labels)
            category_norm = (category or "").lower().replace(" ", "_")

            if category is not None:
                if stats_name:
                    if stats_name.lower().replace(" ", "_") != category_norm:
                        continue
                else:
                    if category_norm in ("batting", "offensive"):
                        if not (label_set & _BATTING_ONLY) or (label_set & _PITCHING_ONLY):
                            continue
                    elif category_norm == "pitching":
                        if not (label_set & _PITCHING_ONLY) or (label_set & _BATTING_ONLY):
                            continue

            entries = stats_group.get("athletes", []) or []
            matched = None
            if espn_id:
                wanted = str(espn_id)
                matched = next(
                    (e for e in entries
                     if str((e.get("athlete") or {}).get("id") or "") == wanted), None)
            else:
                want = _norm_name(player_name)
                by_name = [e for e in entries
                           if _norm_name((e.get("athlete") or {}).get("displayName")) == want]
                matched = by_name[0] if len(by_name) == 1 else None

            for athlete_entry in ([matched] if matched else []):
                stats_list = athlete_entry.get("stats", [])
                labels = stats_group.get("labels") or []
                if isinstance(stats_list, list) and len(stats_list) > 0:
                    # ESPN's label casing varies by sport and feed: NFL
                    # publishes YDS while the established maps use Yds.
                    label_keys = [str(label).casefold() for label in labels]
                    wanted_key, _, pair_selector = str(stat_key).casefold().partition(":")
                    if labels and wanted_key in label_keys:
                        idx = label_keys.index(wanted_key)
                        if idx < len(stats_list):
                            val = stats_list[idx]
                            if val in (None, ""):
                                return None
                            try:
                                return float(val)
                            except (ValueError, TypeError):
                                # Kicking FG/XP and passing C/ATT are published
                                # as made/attempted. A mapped made-stat uses the
                                # numerator; malformed pairs still fail closed.
                                if isinstance(val, str) and "/" in val:
                                    made, _attempted = val.split("/", 1)
                                    selected = _attempted if pair_selector == "attempted" else made
                                    try:
                                        return float(selected)
                                    except (ValueError, TypeError):
                                        pass
                                return None
                return None
    return None


def _find_player_compound_stat(boxscore: dict, player_name: str, team: str,
                                categories: List[str], stat_keys: List[str],
                                espn_id: Optional[str] = None,
                                missing_as_zero: bool = False) -> Optional[float]:
    """Sum multiple stats across categories (e.g. hits_runs_rbis = H + R + RBI)."""
    total = 0.0
    found = False
    for cat, key in zip(categories, stat_keys):
        val = _find_player_stat(boxscore, player_name, team, cat, key, espn_id=espn_id)
        if val is None:
            if missing_as_zero:
                continue
            return None
        found = True
        total += val
    return total if found else None
