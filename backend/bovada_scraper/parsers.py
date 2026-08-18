"""parsers — Bovada scraper parsers layer."""
import re
import json
import os
import sys
import collections
import datetime as dt
import unicodedata
import urllib.request

import collections
import re
from .config import (MARKET_MAP, _MLS_CLUB_CODES, _MLS_NON_PLAYER_OUTCOMES, _MLS_PLAYER_GROUPS, _MLS_PLAYER_MARKETS, _SOCCER_MARKET_RULES, _STALE_TEAM_TAGS, _UFC_METHOD, _UNMAPPED_PLAYER_MARKETS, _WC_SKIP_KW)  # noqa: E402

def _parse_ufc_props(event: dict) -> list:
    comps = [c.get("name") for c in event.get("competitors", []) if c.get("name")]
    if len(comps) < 2:
        return []
    fa, fb = comps[0], comps[1]
    desc = event.get("description") or f"{fa} vs {fb}"
    start_time = event.get("startTime")
    props = []
    for dg in event.get("displayGroups", []):
        for m in dg.get("markets", []):
            if m.get("description") != "Method of Victory":
                continue
            for o in m.get("outcomes", []):
                od = o.get("description") or ""
                if " Wins by " not in od:
                    continue
                fighter, method = od.split(" Wins by ", 1)
                market = _UFC_METHOD.get(method.strip().lower())
                if not market:
                    continue
                fighter = fighter.strip()
                opp = fb if fighter == fa else fa
                props.append({
                    "player_name": fighter,
                    "team": opp,
                    "market": market,
                    "line": 0.5,
                    "side": "over",
                    "odds": (o.get("price") or {}).get("american"),
                    "start_time": start_time,
                    "game_desc": desc,
                    "home_team": fa,
                    "away_team": fb,
                    "league": "ufc",
                })
    return props

# Tennis (atp/wta) — player-attributed markets on Bovada's tennis feed (verified live 2026-08-06:
# ATP Montreal + WTA Toronto). Four match-level markets carry player attribution:
#   Moneyline                             -> match_winner  (each outcome = a player; yes/no "wins the match")
#   Total Games O/U - <Player>            -> total_games   (player's games won over/under; handicap = line)
#   Set Betting                           -> set_betting   (exact-set-score ladder: "<Player> 2 - 0")
#   Will <Player> Win At Least One Set?   -> win_a_set     (yes/no; "Yes" outcome carries the player)
# Match-level only: markets are filtered to period.abbreviation == "MT" (pre-match "Match" and live
# "Live Match"); per-set variants (" - S1" / " - LS2" outcome suffixes) are out of scope for the
# props schema. Match-level markets with NO player attribution (Total Sets O/U 2.5, match Total
# games, Game/Set spreads, tie-break, odd/even, tournament Outrights) are deferred — the same
# deferral as UFC fight-level markets (see _UFC_METHOD). Set-betting scores ride in the market key
# ("set_betting___2_0") so the per-player ladders don't collide on the ingest dedup key
# (game_id, player_id, market, line, side, source); _base_market() still groups them under
# "set_betting" for boards/charting.
def _parse_tennis_props(event: dict, league: str) -> list:
    """Extract player-attributed tennis props from a single Bovada tennis event."""
    import re
    comps = [c.get("name") for c in event.get("competitors", []) if c.get("name")]
    if len(comps) < 2:
        return []
    fa, fb = comps[0], comps[1]
    comp_by_id = {c.get("id"): c.get("name") for c in event.get("competitors", []) if c.get("id")}
    desc = event.get("description") or f"{fa} vs {fb}"
    start_time = event.get("startTime")
    results = []
    for dg in event.get("displayGroups", []):
        for m in dg.get("markets", []):
            period_abbr = (m.get("period") or {}).get("abbreviation") or ""
            if period_abbr != "MT":
                continue  # match-level only; skip per-set / live-set periods (S1/S2/S3/LS*)
            mdesc = (m.get("description") or "").strip()
            mdesc_lower = mdesc.lower()
            if mdesc_lower == "moneyline":
                canonical, kind = "match_winner", "win"
            elif mdesc_lower.startswith("total games o/u - "):
                canonical, kind = "total_games", "ou"
            elif mdesc_lower == "set betting":
                canonical, kind = "set_betting", "setscore"
            elif mdesc_lower.startswith("will ") and mdesc_lower.endswith(" win at least one set?"):
                canonical, kind = "win_a_set", "winset"
            else:
                continue
            for o in m.get("outcomes", []):
                od = (o.get("description") or "").strip()
                price = o.get("price") or {}
                odds = price.get("american")
                cid = o.get("competitorId")
                player = comp_by_id.get(cid) if cid else None
                if kind == "win":
                    if not player:
                        player = od
                    if not player:
                        continue
                    market = canonical
                    line, side = 0.5, "over"
                elif kind == "ou":
                    if not player:
                        # fallback: player rides in the market desc ("Total Games O/U - <Player>")
                        player = mdesc.split(" - ", 1)[1].strip() if " - " in mdesc else ""
                    if not player:
                        continue
                    handicap = price.get("handicap")
                    market = canonical
                    line = float(handicap) if handicap is not None else None
                    side = "over" if od.lower() == "over" else "under"
                elif kind == "setscore":
                    sm = re.search(r"(\d+)\s*-\s*(\d+)\s*$", od)
                    if not sm or not player:
                        continue
                    market = "set_betting___{}_{}".format(sm.group(1), sm.group(2))
                    line, side = 0.5, "over"
                else:  # winset — the "No" outcome is the complement; keep the "Yes" price only
                    if od.lower() != "yes":
                        continue
                    if not player:
                        pm = re.match(r"Will (.+?) Win At Least One Set\?", mdesc)
                        player = pm.group(1).strip() if pm else ""
                    if not player:
                        continue
                    market = canonical
                    line, side = 0.5, "over"
                opp = fb if player == fa else (fa if player == fb else "")
                results.append({
                    "player_name": player,
                    "team": opp,
                    "market": market,
                    "line": line,
                    "side": side,
                    "odds": odds,
                    "league": league,
                    "game_desc": desc,
                    "home_team": fa,
                    "away_team": fb,
                    "start_time": start_time,
                    "source": "bovada",
                    "market_raw": mdesc,
                })
    return results

def _report_unmapped_market(league: str, group: str, market_desc: str, n_outcomes: int):
    """Record a player-attributed market we have no mapping for.

    Silently skipping it is the exact shape fail-loudly §2a describes: the run still
    prints a plausible prop count, and the missing market is invisible until somebody
    counts Bovada's board by hand. main() exits non-zero when this dict is non-empty.
    """
    key = (league, group, market_desc)
    entry = _UNMAPPED_PLAYER_MARKETS.setdefault(key, {"events": 0, "outcomes": 0})
    entry["events"] += 1
    entry["outcomes"] += n_outcomes

def _looks_player_attributed(outcomes) -> bool:
    """True when the outcomes are players ("Name (TEAM)") rather than Over/Under/Yes/No."""
    named = 0
    for o in outcomes or []:
        desc = (o.get("description") or "").strip()
        if re.match(r".+\(([^)]+)\)\s*$", desc):
            named += 1
    return bool(outcomes) and named >= max(2, len(outcomes) // 2)

def _parse_mls_props(event: dict) -> list:
    """Extract player props from a single Bovada MLS event.

    The team parenthetical is NOT trusted as identity. Bovada tags three players on this
    board with a club they no longer play for -- Alexis Sanchez (SEV), Josef Martinez (TIJ),
    Igor Jesus (NFO) -- all three appearing in MLS fixtures between two other clubs. Passing
    a foreign team code to the resolver turns a resolvable player into an unresolved one, so
    a code that is not one of the event's two clubs is dropped and the resolver is left to
    disambiguate on game_id, which it already does (_resolve_player_for_ingest / game_teams).
    """
    results = []
    game_desc = event.get("description", "")
    start_time = event.get("startTime")

    home_team = ""
    away_team = ""
    for c in event.get("competitors", []):
        if c.get("home", False):
            home_team = c.get("name", "")
        else:
            away_team = c.get("name", "")

    # Bovada names the competitors in full ("Austin FC") and codes the players in the
    # outcome parenthetical ("(ATX)"), with no published mapping between the two. The
    # event's own board supplies it: across its player markets the two squads account for
    # every outcome but a handful, so the two most frequent codes ARE the two clubs.
    # Measured 2026-08-16: real codes ran 18-53 outcomes each, the three stale tags ran 1.
    code_counts = collections.Counter()
    for dg in event.get("displayGroups", []):
        if (dg.get("description") or "").strip().lower() not in _MLS_PLAYER_GROUPS:
            continue
        for market in dg.get("markets", []):
            if (market.get("description") or "").strip().lower() not in _MLS_PLAYER_MARKETS:
                continue
            for outcome in market.get("outcomes", []):
                m = re.match(r".+?\s*\(([^)]+)\)\s*$", (outcome.get("description") or "").strip())
                if m:
                    code_counts[m.group(1).strip().upper()] += 1
    event_codes = {code for code, _ in code_counts.most_common(2)}

    # TOURNAMENT vs LEAGUE (decided 2026-08-17). A league has a fixed membership;
    # a tournament draws entrants FROM leagues. When one of the event's two
    # dominant clubs is not an MLS club (Chivas, América, Puebla, Toluca in a
    # Leagues Cup fixture; Nottingham Forest in a friendly), the fixture is not
    # MLS and must file under the tournament's own competition key (`lcup`) so
    # its players stay resolvable against whichever league actually rosters them.
    league = "lcup" if (event_codes - _MLS_CLUB_CODES) else "mls"

    for dg in event.get("displayGroups", []):
        group = (dg.get("description") or "").strip().lower()
        if group not in _MLS_PLAYER_GROUPS:
            continue

        for market in dg.get("markets", []):
            market_desc = (market.get("description") or "").strip()
            outcomes = market.get("outcomes", [])
            rule = _MLS_PLAYER_MARKETS.get(market_desc.lower())
            if rule is None:
                # Team-level markets share these groups ("First Card" is a team ladder,
                # "Total Cards O/U - Seattle Sounders" a team total). Only report the ones
                # that actually carry players.
                if _looks_player_attributed(outcomes):
                    _report_unmapped_market("mls", group, market_desc, len(outcomes))
                continue

            canonical_market, line = rule
            for outcome in outcomes:
                odesc = (outcome.get("description") or "").strip()
                # The "nobody" outcome on a goalscorer ladder is the market's complement,
                # not a player. Checked before the name parse so it can never be minted.
                if odesc.lower() in _MLS_NON_PLAYER_OUTCOMES:
                    continue
                # The club parenthetical is OPTIONAL. Requiring it dropped 31 of 1,464
                # outcomes on 2026-08-16 -- Sergi Roberto, Youssef Maziz, Célio Pompeu and
                # 28 others -- silently, because Bovada writes a bare name whenever it has
                # no club tag. `_split_market_and_player` learned this for MLB already: the
                # team is optional, the NAME is what the prop is about.
                m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", odesc)
                if m:
                    player_name = m.group(1).strip()
                    team_code = m.group(2).strip().upper()
                else:
                    player_name = odesc
                    team_code = ""
                if not player_name:
                    continue
                # Combination outcomes ("Saka or Messi") are not a player.
                if " or " in player_name.lower():
                    continue
                if team_code and team_code not in event_codes:
                    _STALE_TEAM_TAGS[(player_name, team_code)] = game_desc
                    team_code = ""
                results.append({
                    "player_name": player_name,
                    "team": team_code,
                    "market": canonical_market,
                    "line": line,
                    "side": "over",
                    "odds": (outcome.get("price") or {}).get("american"),
                    "league": league,
                    "game_desc": game_desc,
                    "home_team": home_team,
                    "away_team": away_team,
                    "start_time": start_time,
                    "source": "bovada",
                    "market_raw": market_desc,
                })

    return results

def _parse_wc_props(event: dict) -> list:
    """Parse World Cup soccer player props from a Bovada event.

    Two patterns:
      1. Yes/no (goalscorer/assists): player = outcome desc (e.g. "Lionel Messi (ARG)"),
         market = market desc.  Line = 0.5, side = "over".
      2. Threshold ladder (shots): player = extracted from market desc
         (e.g. "Shots On Target - Lionel Messi (ARG)"), outcome = "2+ Shots on Target"
         → line = 2, side = "over".
    """
    import re
    results = []
    game_desc = event.get("description", "")
    start_time = event.get("startTime")

    competitors = event.get("competitors", [])
    home_team = ""
    away_team = ""
    for c in competitors:
        if c.get("home", False):
            home_team = c.get("name", "")
        else:
            away_team = c.get("name", "")

    for dg in event.get("displayGroups", []):
        dg_desc = (dg.get("description") or "").lower()

        # Skip noise groups
        if any(kw in dg_desc for kw in ["player specials", "specials", "alternate",
                                          "game lines", "game props"]):
            continue

        for market in dg.get("markets", []):
            market_desc = (market.get("description") or "").strip()
            mdesc_lower = market_desc.lower()

            # Filter noise markets
            if any(kw in mdesc_lower for kw in _WC_SKIP_KW):
                continue

            # Match against soccer rules
            rule = None
            for (match_kw, canonical, is_yesno) in _SOCCER_MARKET_RULES:
                if match_kw in mdesc_lower:
                    rule = (canonical, is_yesno)
                    break
            if rule is None:
                continue  # not a market we care about

            canonical_market, is_yesno = rule

            for outcome in market.get("outcomes", []):
                odesc = (outcome.get("description") or "").strip()
                price = outcome.get("price", {})
                odds = price.get("american")

                if is_yesno:
                    # Player = outcome description, e.g. "Lionel Messi (ARG)"
                    pm = re.match(r"(.+?)\s*\(([A-Za-z]+)\)", odesc)
                    if not pm:
                        continue
                    player_name = pm.group(1).strip()
                    team_abbrev = pm.group(2).strip().upper()
                    # Skip combos: "Bukayo Saka or Lionel Messi"
                    if " or " in player_name.lower():
                        continue
                    results.append({
                        "player_name": player_name,
                        "team": team_abbrev,
                        "market": canonical_market,
                        "line": 0.5,
                        "side": "over",
                        "odds": odds,
                        "league": "wc",
                        "game_desc": game_desc,
                        "home_team": home_team,
                        "away_team": away_team,
                        "start_time": start_time,
                        "source": "bovada",
                        "market_raw": market_desc,
                    })
                else:
                    # Threshold ladder: player in market desc, e.g.
                    # "Shots On Target - Lionel Messi (ARG)"
                    # outcome: "2+ Shots on Target"
                    player_name = ""
                    team_abbrev = ""
                    if " - " in market_desc:
                        player_part = market_desc.split(" - ", 1)[1].strip()
                        pm = re.match(r"(.+?)\s*\(([A-Za-z]+)\)", player_part)
                        if pm:
                            player_name = pm.group(1).strip()
                            team_abbrev = pm.group(2).strip().upper()
                    if not player_name:
                        continue

                    # Extract threshold number from outcome: "2+ Shots on Target" → 2
                    line_match = re.match(r"(\d+)\s*\+", odesc)
                    if not line_match:
                        continue
                    line_val = float(line_match.group(1))

                    results.append({
                        "player_name": player_name,
                        "team": team_abbrev,
                        "market": canonical_market,
                        "line": line_val,
                        "side": "over",
                        "odds": odds,
                        "league": "wc",
                        "game_desc": game_desc,
                        "home_team": home_team,
                        "away_team": away_team,
                        "start_time": start_time,
                        "source": "bovada",
                        "market_raw": market_desc,
                    })

    return results

def _split_market_and_player(market_desc: str):
    """"Total Strikeouts - Ryan Gusto (MIA)" -> ("Total Strikeouts", "Ryan Gusto", "MIA").

    Bovada is not consistent about the team parenthetical. It writes "Total Strikeouts -
    Ryan Gusto (MIA)" and it also writes "Total Hits, Runs and RBIs - Cooper Pratt" with no
    team at all, and team codes are not reliably all-caps ("D-Backs"). The old regex
    required `\\([A-Z]+\\)` and returned nothing for every other shape, so the name was
    dropped and left welded into the market key instead.

    The team is optional. The NAME is the part that matters, because it is what the prop is
    about. Returns ("", "") for the player when the description carries no " - " separator
    at all — that is a game-level market, not a parse failure.
    """
    desc = (market_desc or "").strip()
    if " - " not in desc:
        return desc, "", ""
    head, player_part = desc.split(" - ", 1)
    player_part = player_part.strip()
    m = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", player_part)
    if m:
        return head.strip(), m.group(1).strip(), m.group(2).strip().upper()
    return head.strip(), player_part, ""

def _parse_standard_props(event: dict, league: str) -> list:
    """Extract all player props from a single Bovada event (non-WC leagues)."""
    results = []
    game_desc = event.get("description", "")
    start_time = event.get("startTime")

    # Parse home/away from competitors
    competitors = event.get("competitors", [])
    home_team = ""
    away_team = ""
    for c in competitors:
        if c.get("home", False):
            home_team = c.get("name", "")
        else:
            away_team = c.get("name", "")

    for dg in event.get("displayGroups", []):
        group_desc = (dg.get("description") or "").lower()

        # Only process player/pitcher props
        if "prop" not in group_desc:
            continue

        for market in dg.get("markets", []):
            market_desc = (market.get("description") or "").strip()

            # Split the player off BEFORE canonicalising. An unmapped market slugs its whole
            # description, so leaving the name attached minted market keys like
            # "total_hits,_runs_and_rbis___cooper_pratt" — one key per player, and a market
            # nothing could group by.
            market_head, desc_player, desc_team = _split_market_and_player(market_desc)

            # Find canonical market name
            canonical = None
            for pattern, name in MARKET_MAP.items():
                if pattern in market_head.lower():
                    canonical = name
                    break
            if not canonical:
                canonical = market_head.lower().replace(" ", "_").replace("-", "_")

            for outcome in market.get("outcomes", []):
                desc = (outcome.get("description") or "").strip()
                price = outcome.get("price", {})
                handicap = price.get("handicap")  # the line number (e.g., 4.5)
                odds = price.get("american")       # American odds (e.g., -110)

                # Determine over/under from description
                desc_lower = desc.lower()
                if desc_lower == "over":
                    side = "over"
                elif desc_lower == "under":
                    side = "under"
                else:
                    # Not an over/under outcome — it's a player name for yes/no props
                    # e.g., "Kyle Schwarber (PHI)"
                    # For yes/no props, the player IS the outcome, side varies by market
                    continue  # skip player-name outcomes for now; we'd need to restructure

                # The player was already parsed off the market description above.
                player_name, team_abbrev = desc_player, desc_team

                # A player-prop row with no player is not a player prop. Emitting one anyway
                # is how 3,729 props from Cooper Pratt, Raynel Delgado, Kahlil Watson and
                # others ended up on ONE nameless players row: the old regex demanded an
                # uppercase team parenthetical, and every market written without one fell
                # through to an empty name that nothing downstream rejected. The World Cup
                # path has always skipped these; this one silently kept them.
                #
                # Two shapes land here and both should be dropped rather than bucketed:
                # genuinely game-level markets in a props group ("Total Hits, Runs and
                # Errors"), and anything whose description we cannot parse. A prop we cannot
                # attribute is not a prop we can serve.
                if not player_name:
                    continue

                results.append({
                    "player_name": player_name,
                    "team": team_abbrev,
                    "market": canonical,
                    "line": float(handicap) if handicap is not None else None,
                    "side": side,
                    "odds": odds,
                    "league": league,
                    "game_desc": game_desc,
                    "home_team": home_team,
                    "away_team": away_team,
                    "start_time": start_time,
                    "source": "bovada",
                    "market_raw": market_desc,
                })

    return results
