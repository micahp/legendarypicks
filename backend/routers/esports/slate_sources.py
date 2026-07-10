"""External source adapters used by the esports slate rebuild pipeline."""

import importlib.util
import json
import os
import re
import urllib.request as _u

from .common import _amer_to_p, _ESPORTS_TITLES, _slug_to_name
from .frag import _fetch_frag_live
from .kalshi import _kalshi_results
from .match_identity import _normalize_match_metadata, _same_pair, _same_team


try:
    from .streams import _candidate
except ImportError:
    _spec = importlib.util.spec_from_file_location(
        "routers.esports._streams_reviewed",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "streams.reviewed.py"))
    _streams_reviewed = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_streams_reviewed)
    _candidate = _streams_reviewed._candidate


_BOV_ESPORTS = ("https://www.bovada.lv/services/sports/event/coupon/events/A/description/"
                "esports?marketFilterId=def&liveOnly=false&lang=en")


def _grid_lookup(team_a, team_b, grid_index):
    """Return a GRID entry and its side labels for a cross-source team pairing."""
    for entry in grid_index:
        names = entry.get("names") or []
        full_names = entry.get("fullNames") or []
        grid_a = grid_b = None
        for index, grid_name in enumerate(names):
            variants = [grid_name]
            if index < len(full_names) and full_names[index]:
                variants.append(full_names[index])
            if any(_same_team(team_a, variant) for variant in variants):
                grid_a = grid_name
            if any(_same_team(team_b, variant) for variant in variants):
                grid_b = grid_name
        if grid_a and grid_b and grid_a != grid_b:
            return entry, grid_a, grid_b
    return None, None, None


def _kalshi_winner_fuzzy(title, team_a, team_b, near_ms=None,
                         tol_ms=12 * 3600 * 1000):
    """Return a settled Kalshi winner aligned to side ``a`` or ``b``, with ambiguity guards."""
    best = None
    seen_winners = set()
    for (market_title, pair), settlements in (_kalshi_results() or {}).items():
        if market_title != title or len(pair) != 2:
            continue
        first, second = sorted(pair)
        if not _same_pair(team_a, team_b, first, second):
            continue
        for winner, close_ms in settlements:
            if near_ms and close_ms and abs(close_ms - near_ms) > tol_ms:
                continue
            seen_winners.add(winner)
            delta = abs((close_ms or near_ms or 0) - (near_ms or 0))
            if best is None or delta < best[0]:
                best = (delta, winner)
    if best is None or len(seen_winners) > 1:
        return None
    winner = best[1]
    return ("a" if _same_team(winner, team_a) else
            "b" if _same_team(winner, team_b) else None)


def _frag_lookup(team_a, team_b):
    """Return a matching frag.se live record and whether its sides are reversed."""
    for match in _fetch_frag_live() or []:
        opponents = match.get("opponents") or []
        if len(opponents) < 2:
            continue

        def variants(opponent):
            team = opponent.get("opponent") or {}
            return [value for value in (team.get("name"), team.get("acronym"), team.get("slug"))
                    if value]

        first, second = variants(opponents[0]), variants(opponents[1])
        direct = (any(_same_team(team_a, value) for value in first)
                  and any(_same_team(team_b, value) for value in second))
        reversed_sides = (any(_same_team(team_a, value) for value in second)
                          and any(_same_team(team_b, value) for value in first))
        if direct or reversed_sides:
            return match, (reversed_sides and not direct)
    return None, None


def _frag_candidates(frag_match):
    """Return all attested stream candidates from a frag.se live record."""
    candidates = []
    for stream in frag_match.get("streams") or []:
        candidates.append(_candidate(
            url=stream.get("raw_url"), embed=stream.get("embed_url"),
            main=stream.get("main"), official=stream.get("official"),
            language=stream.get("language"), attested=True, source="frag"))
    if not candidates:
        official = (frag_match.get("official_stream_url") or "").strip()
        if official:
            candidates.append(_candidate(embed=official, official=True,
                                         attested=True, source="frag"))
    return [candidate for candidate in candidates if candidate]


def _ps_candidates(ps_id, streams_by_id, running):
    """Return PandaScore stream candidates for one matched fixture."""
    candidates = []
    for stream in streams_by_id.get(ps_id) or []:
        candidates.append(_candidate(
            url=stream.get("raw_url"), embed=stream.get("embed_url"),
            main=stream.get("main"), official=stream.get("official"),
            language=stream.get("language"), attested=bool(running), source="pandascore"))
    return [candidate for candidate in candidates if candidate]


def _fetch_bovada_rows(stale_cutoff_ms):
    """Fetch and normalize Bovada series rows, or return ``None`` when the source is unavailable."""
    try:
        request = _u.Request(
            _BOV_ESPORTS,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with _u.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode())
    except Exception:
        return None

    rows = []
    for group in data:
        for event in group.get("events", []):
            path_parts = [part for part in (event.get("link") or "").split("/") if part]
            if len(path_parts) < 3:
                continue
            title_slug, league_slug = path_parts[1], path_parts[2]
            if title_slug not in _ESPORTS_TITLES:
                continue
            start_time = event.get("startTime")
            if not event.get("live") and start_time and start_time < stale_cutoff_ms:
                continue
            if re.search(r"\bl?map\s*\d", (event.get("description") or "").lower()):
                continue

            moneyline = None
            for display_group in event.get("displayGroups", []):
                for market in display_group.get("markets", []):
                    if (market.get("description") or "").lower() == "moneyline":
                        moneyline = market
                        break
                if moneyline:
                    break

            prices = []
            if moneyline:
                for outcome in moneyline.get("outcomes", []):
                    american = (outcome.get("price") or {}).get("american")
                    probability = None
                    if american not in (None, "EVEN", "", "-"):
                        try:
                            probability = _amer_to_p(american)
                        except Exception:
                            pass
                    prices.append((outcome.get("description"), probability))
            if len(prices) != 2:
                description = event.get("description") or ""
                names = ([part.strip() for part in description.split(" vs ")]
                         if " vs " in description else [])
                if len(names) != 2:
                    continue
                prices = [(names[0], None), (names[1], None)]

            favorite = None
            if prices[0][1] is not None and prices[1][1] is not None:
                total = prices[0][1] + prices[1][1]
                if total > 0:
                    first_pct = round(prices[0][1] / total * 100)
                    favorite = {
                        "name": prices[0][0] if first_pct >= 50 else prices[1][0],
                        "pct": max(first_pct, 100 - first_pct),
                    }
            rows.append(_normalize_match_metadata({
                "startTime": start_time,
                "title": _ESPORTS_TITLES[title_slug],
                "league": _slug_to_name(league_slug),
                "teamA": prices[0][0],
                "teamB": prices[1][0],
                "favorite": favorite,
                "watch": None,
                "_origin": "bovada",
                "_bov_live": bool(event.get("live")),
            }))
    return rows
