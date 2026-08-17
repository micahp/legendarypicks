#!/usr/bin/env python3
"""
bovada_scraper.py — scrape player props from Bovada's open API.

Usage:
  python3 bovada_scraper.py mlb     # scrape MLB player props
  python3 bovada_scraper.py nba     # NBA (when in season)
  python3 bovada_scraper.py nfl     # NFL
  python3 bovada_scraper.py nhl     # NHL
  python3 bovada_scraper.py atp     # ATP tennis props
  python3 bovada_scraper.py wta     # WTA tennis props
  python3 bovada_scraper.py all     # all available
  python3 bovada_scraper.py mlb --ingest   # scrape + POST to ingest API

Source: Bovada's internal API — no auth, no Cloudflare, live odds.
"""
import sys, json, os, re, collections, unicodedata, urllib.request, datetime as dt

from link_prop_games import link_prop_game
import espn_client as espn

API_BASE = os.environ.get("LP_API_BASE", "http://localhost:8000")
BOVADA = "https://www.bovada.lv/services/sports/event/coupon/events/A/description"

LEAGUES = {
    "mlb":  ("baseball", "mlb"),
    "nba":  ("basketball", "nba"),
    "nfl":  ("football", "nfl"),
    "nhl":  ("hockey", "nhl"),
    "wnba": ("basketball", "wnba"),
    "wc":   ("soccer", "fifa-world-cup/fifa-world-cup-matches"),
    # Bovada files MLS by continent, not by country code. `soccer/usa/mls` and
    # `soccer/united-states/mls` both 404, which is how a probe on 2026-08-16 first
    # concluded "Bovada has no MLS" -- it has 14 fixtures and 1,464 player outcomes.
    "mls":  ("soccer", "north-america/united-states/mls"),
    "ufc":  ("ufc-mma", "ufc"),
    "atp":  ("tennis", "atp"),
    "wta":  ("tennis", "wta"),
}

HDR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}

# Soccer (WC) market recognition rules — (match_substring, canonical_market, is_yesno)
# yes/no: player = outcome description, line set to 0.5 ("over 0.5 goals/assists")
# over/under: player in market name, line extracted from outcome threshold
_SOCCER_MARKET_RULES = [
    ("anytime goal scorer",  "goals",           True),
    ("to assist a goal",     "assists",          True),
    # over/under with thresholds: player in market name, line from outcome
    ("shots on target",      "shots_on_target",  False),
    ("shots",                "shots",            False),
]

# WC noise filters — market/outcome keywords we skip entirely
_WC_SKIP_KW = [
    "corner", "card", "total match", "1h ", "first half",
    "goalkeeper", "either player", "return the favor",
    "score direct from a free kick", "score and assist",
    "to score 2 or more", "to assist 2 or more",
    "first goal scorer", "last goal scorer",
    "3+ goals", "8+ corners", "offsides",
    "throw-in", "goal kick", "scoring quarter",
    "player to be carded", "sending off", "red card",
    "both teams to score", "draw no bet", "method of victory",
    "spread", "moneyline", "total goals", "to qualify",
    "goal spread", "3-way", "player specials",
]

# Map Bovada market descriptions → our canonical market names
MARKET_MAP = {
    # Pitcher props (with lines)
    "total strikeouts": "strikeouts",
    "total hits allowed": "hits_allowed",
    "total pitcher outs": "outs",
    "total earned runs": "earned_runs",
    "total walks": "walks",
    # Player props with lines (points/rebounds etc for NBA/NFL)
    "total points": "points",
    "total rebounds": "rebounds",
    "total assists": "assists",
    "total threes": "threes",
    "total blocks": "blocks",
    "total steals": "steals",
    "total turnovers": "turnovers",
    "passing yards": "passing_yards",
    "passing tds": "passing_tds",
    "rushing yards": "rushing_yards",
    "receiving yards": "receiving_yards",
    "receptions": "receptions",
    "total tackles": "tackles",
    "total sacks": "sacks",
    "total shots": "shots",
    "total saves": "saves",
    "total goals": "goals",
    # Yes/no props (no line, just odds)
    "player to hit a home run": "home_run_any",
    "player to hit 2+ home runs": "home_runs_2plus",
    "player to record a hit": "hit_any",
    "player to record 2+ hits": "hits_2plus",
    "player to record a run": "run_any",
    "player to record 2+ runs": "runs_2plus",
    "player to record a rbi": "rbi_any",
    "player to record 2+ rbis": "rbis_2plus",
    "player to record a stolen base": "stolen_base_any",
    "player to record a double": "double_any",
    "player to record a triple": "triple_any",
}


def fetch_events(sport: str, league: str) -> list:
    url = f"{BOVADA}/{sport}/{league}"
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    events = []
    for group in data:
        for ev in group.get("events", []):
            events.append(ev)
    return events


def parse_player_props(event: dict, league: str) -> list:
    """Extract all player props from a single Bovada event."""
    if league == "mls":
        return _parse_mls_props(event)
    if league == "wc":
        return _parse_wc_props(event)
    if league == "ufc":
        return _parse_ufc_props(event)
    if league in ("atp", "wta"):
        return _parse_tennis_props(event, league)
    return _parse_standard_props(event, league)


# UFC has no per-fighter STAT props on Bovada; the fighter-attributed market is Method of Victory. Map
# each outcome to a yes/no prop on the fighter (o0.5), mirroring the WC anytime-goal shape. Fight-level
# markets (total rounds, go-the-distance) are game-level and not represented in the player-prop schema
# yet — deferred. This is the template for other individual sports (tennis majors) too.
# win_by_ko / win_by_submission are deliberately NOT mapped here — Underdog Fantasy prices
# the same markets (its "Knockouts"/"Submissions" O/U 0.5 lines) and is now the sole source
# for both (see ingest_underdog_props.py). win_by_decision has no Underdog equivalent, still
# sourced from Bovada.
_UFC_METHOD = {
    "decision or technical decision": "win_by_decision",
}


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


# MLS player-attributed markets, enumerated live 2026-08-16 across all 14 fixtures on
# soccer/north-america/united-states/mls. Every one is a yes/no market whose OUTCOMES are
# the players ("Christian Ramirez (ATX)"); none of them carry a threshold ladder, and MLS
# publishes no shots or shots-on-target market at all (the WC feed does -- do not assume
# one soccer coupon implies another).
#
# Keyed on the EXACT market description rather than a substring. The WC rules below match
# on substrings, which is why "to score 2 or more goals" had to be listed in _WC_SKIP_KW to
# stop "anytime goal scorer" from swallowing it. An exact table cannot have that collision,
# and it makes an unrecognised market visible instead of silently absorbed (see
# _report_unmapped_market).
#
# The goal ladder is deliberately ONE market at three lines rather than three market names.
# `goals` over 0.5 / 1.5 / 2.5 all settle from the same published stat, so the board, the
# hit-rate chart and settlement.py need no new market vocabulary. Splitting them into
# "hat_trick" and "two_plus_goals" would have created two markets nothing could grade.
#
#   market description            -> (canonical market, line)   outcomes seen 2026-08-16
_MLS_PLAYER_MARKETS = {
    "to assist a goal":          ("assists", 0.5),             # 639
    "anytime goal scorer":       ("goals", 0.5),               # 357
    "first goal scorer":         ("first_goal_scorer", 0.5),   # 332
    "to score a hat trick":      ("goals", 2.5),               # 56
    "to be shown a card":        ("card_shown", 0.5),          # 22
    "to score or assist a goal": ("goal_or_assist", 0.5),      # 20
    "to score 2 or more goals":  ("goals", 1.5),               # 20
    # Bovada writes the first-goal market under two names. No event carries both (checked
    # across all 14), and if one ever does the ingest dedup key
    # (game_id, player_id, market, line, side, source) collapses them.
    "player to score 1st goal":  ("first_goal_scorer", 0.5),   # 18
}

# Display groups whose markets are player-attributed. A market that appears here and is NOT
# in _MLS_PLAYER_MARKETS is a market Bovada added since this table was measured -- it gets
# reported, never silently dropped. Game-level groups (Game Lines, Corners, Combo Props ...)
# are out of scope for the player-prop schema, the same deferral as UFC fight-level markets.
_MLS_PLAYER_GROUPS = {"goalscorer", "assists", "cards"}

# Outcomes inside a player market that are the market's complement rather than a person.
# "No Goalscorer" is a real, priced outcome on every goalscorer ladder; minting it as a
# player is how a sportsbook string becomes a row in `players`.
_MLS_NON_PLAYER_OUTCOMES = {"no goalscorer", "no 1st goal", "no goal scorer",
                            "no first goal scorer", "no card", "none", "no assist"}

# Populated by _parse_mls_props, printed by main(). A module-level accumulator because the
# parser runs per event and the finding is per RUN -- one unmapped market on 14 events is
# one finding, not fourteen.
_UNMAPPED_PLAYER_MARKETS = {}

# {(player_name, bovada_code): game_desc} for outcomes whose club tag is not one of the
# event's two teams. Printed by main() -- a silent drop here is a player the resolver was
# never given a fair chance at.
_STALE_TEAM_TAGS = {}


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
                    "league": "mls",
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


def _wc_event_date(prop: dict, fallback: str) -> str:
    """UTC event date from Bovada startTime (milliseconds or seconds)."""
    try:
        stamp = float(prop.get("start_time"))
        if stamp > 10_000_000_000:
            stamp /= 1000
        return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return fallback


def _event_start_iso(prop: dict):
    """Full UTC kickoff datetime (ISO) from Bovada startTime, so the slate can show a game time and
    not just a date. None when the stamp is missing/unparseable."""
    try:
        stamp = float(prop.get("start_time"))
        if stamp > 10_000_000_000:
            stamp /= 1000
        return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _wc_direct_ingest(all_props: list, today: str):
    """Direct DB insert for WC props — bypasses ingest API since WC players
    don't exist in the players table yet (Phase 1: name-match only).
    Creates player rows as needed."""
    import sqlite3, os as _os
    DB = _os.environ.get("LP_DB_PATH") or _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ingested = 0
    espn_by_date = {}

    try:
        by_game = {}
        for p in all_props:
            game_date = _wc_event_date(p, today)
            gkey = (game_date, p["game_desc"])
            if gkey not in by_game:
                by_game[gkey] = {
                    "date": game_date,
                    "home": p["home_team"],
                    "away": p["away_team"],
                    "props": []
                }
            by_game[gkey]["props"].append(p)

        for gkey, batch in by_game.items():
            print(f"  {batch['away']} @ {batch['home']}: {len(batch['props'])} props")
            game_start = _event_start_iso(batch["props"][0]) if batch["props"] else None
            cur = con.execute(
                "SELECT id,league,date,home,away,espn_event_id,start_time FROM prop_games "
                "WHERE league=? AND date=? AND home=? AND away=?",
                ("wc", batch["date"], batch["home"], batch["away"]))
            game_row = cur.fetchone()
            if game_row:
                game_id = game_row["id"]
                if game_start and not game_row["start_time"]:   # backfill a known kickoff time
                    con.execute("UPDATE prop_games SET start_time=? WHERE id=?", (game_start, game_id))
            else:
                cur = con.execute(
                    "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) VALUES(?,?,?,?,?,?)",
                    ("wc", batch["date"], batch["home"], batch["away"], "", game_start))
                game_id = cur.lastrowid
                game_row = con.execute(
                    "SELECT id,league,date,home,away,espn_event_id,start_time FROM prop_games WHERE id=?",
                    (game_id,)).fetchone()

            if not game_row["espn_event_id"]:
                if batch["date"] not in espn_by_date:
                    try:
                        espn_by_date[batch["date"]] = espn.games("wc", batch["date"])
                    except Exception as exc:
                        print(f"    ESPN schedule unavailable for {batch['date']}: {exc}")
                        espn_by_date[batch["date"]] = []
                espn_id = link_prop_game(con, game_row, espn_by_date[batch["date"]])
                if espn_id:
                    con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?", (espn_id, game_id))
                    print(f"    linked ESPN event {espn_id}")
                else:
                    print("    WARNING: unresolved ESPN event; props retained for next retry")

            for p in batch["props"]:
                pname = p["player_name"]
                pteam = p.get("team", "")
                pl = con.execute(
                    "SELECT id FROM players WHERE name=? AND league=?",
                    (pname, "wc")).fetchone()
                if pl:
                    player_id = pl["id"]
                else:
                    cur = con.execute(
                        "INSERT INTO players(name, team, league) VALUES(?,?,?)",
                        (pname, pteam if pteam else None, "wc"))
                    player_id = cur.lastrowid

                odds_val = p.get("odds")
                line_val = p.get("line") or 0
                side = p.get("side", "over")
                market = p.get("market", "")

                odds_int = None
                if odds_val is not None:
                    try:
                        odds_int = int(odds_val)
                    except (ValueError, TypeError):
                        if str(odds_val).upper() == "EVEN":
                            odds_int = 100
                existing = con.execute(
                    "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? "
                    "AND line=? AND side=? AND source='bovada'",
                    (game_id, player_id, market, line_val, side)).fetchone()
                if existing:
                    if odds_int is None:
                        con.execute("UPDATE props SET captured_at=? WHERE id=?", (now, existing["id"]))
                    else:
                        con.execute(
                            "UPDATE props SET captured_at=?,odds=?,odds_captured_at=? WHERE id=?",
                            (now, odds_int, now, existing["id"]))
                elif odds_int is not None:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (game_id, player_id, market, line_val, side, "bovada", now, odds_int, now))
                else:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) VALUES(?,?,?,?,?,?,?)",
                        (game_id, player_id, market, line_val, side, "bovada", now))
                ingested += 1

        con.commit()
    finally:
        con.close()
    return ingested


def _normalize_identity_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", value.lower())).strip()


def _resolve_ufc_player_for_bovada(con, player_name: str) -> int:
    """Use a reviewed alias before creating a Bovada-only UFC player row."""
    exact = con.execute(
        "SELECT id FROM players WHERE name=? AND league='ufc' ORDER BY id", (player_name,)
    ).fetchall()
    if len(exact) == 1:
        return exact[0]["id"]
    if len(exact) > 1:
        raise RuntimeError("ambiguous UFC canonical name from Bovada: {}".format(player_name))
    aliases = con.execute(
        "SELECT DISTINCT p.id FROM name_alias na JOIN players p ON p.id=na.player_id "
        "WHERE p.league='ufc' AND na.alias_norm=? ORDER BY p.id",
        (_normalize_identity_name(player_name),),
    ).fetchall()
    if len(aliases) == 1:
        return aliases[0]["id"]
    if len(aliases) > 1:
        raise RuntimeError("ambiguous UFC reviewed alias from Bovada: {}".format(player_name))
    return con.execute(
        "INSERT INTO players(name, team, league) VALUES(?,?,?)",
        (player_name, None, "ufc"),
    ).lastrowid


def _find_existing_ufc_game_for_players(con, game_date: str, player_ids: set):
    """Find one canonical fight by its resolved fighters when display names changed."""
    if len(player_ids) != 2:
        return None
    candidates = con.execute(
        "SELECT pg.id,pg.start_time FROM prop_games pg JOIN props pr ON pr.game_id=pg.id "
        "WHERE pg.league='ufc' AND pg.date=? AND pr.player_id IN (?,?) "
        "GROUP BY pg.id HAVING COUNT(DISTINCT pr.player_id)=2",
        (game_date, *sorted(player_ids)),
    ).fetchall()
    if len(candidates) > 1:
        raise RuntimeError("ambiguous UFC canonical game for Bovada fighter ids")
    return candidates[0] if candidates else None


def _ufc_direct_ingest(all_props: list, today: str) -> int:
    """Direct DB insert for UFC method-of-victory props — fighters are created as players (league
    'ufc') as needed, like WC. Game home/away = the two fighters; start_time stored. No ESPN linking."""
    import sqlite3, os as _os
    DB = _os.environ.get("LP_DB_PATH") or _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    ingested = 0
    try:
        by_game = {}
        for p in all_props:
            gdate = _wc_event_date(p, today)
            gkey = (gdate, p["game_desc"])
            if gkey not in by_game:
                by_game[gkey] = {"date": gdate, "home": p["home_team"], "away": p["away_team"], "props": []}
            by_game[gkey]["props"].append(p)

        for batch in by_game.values():
            game_start = _event_start_iso(batch["props"][0]) if batch["props"] else None
            resolved_props = [
                (p, _resolve_ufc_player_for_bovada(con, p["player_name"]))
                for p in batch["props"]
            ]
            row = con.execute(
                "SELECT id,start_time FROM prop_games WHERE league=? AND date=? AND home=? AND away=?",
                ("ufc", batch["date"], batch["home"], batch["away"])).fetchone()
            if not row:
                row = _find_existing_ufc_game_for_players(
                    con, batch["date"], {player_id for _, player_id in resolved_props}
                )
            if row:
                game_id = row["id"]
                if game_start and not row["start_time"]:
                    con.execute("UPDATE prop_games SET start_time=? WHERE id=?", (game_start, game_id))
            else:
                game_id = con.execute(
                    "INSERT INTO prop_games(league,date,home,away,espn_event_id,start_time) VALUES(?,?,?,?,?,?)",
                    ("ufc", batch["date"], batch["home"], batch["away"], "", game_start)).lastrowid
            print(f"  {batch['away']} vs {batch['home']}: {len(batch['props'])} props")
            for p, player_id in resolved_props:
                line_val = p.get("line") or 0
                side = p.get("side", "over")
                market = p.get("market", "")
                odds_int = None
                if p.get("odds") is not None:
                    try:
                        odds_int = int(p["odds"])
                    except (ValueError, TypeError):
                        odds_int = 100 if str(p["odds"]).upper() == "EVEN" else None
                existing = con.execute(
                    "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? AND line=? AND side=? AND source='bovada'",
                    (game_id, player_id, market, line_val, side)).fetchone()
                if existing:
                    if odds_int is None:
                        con.execute("UPDATE props SET captured_at=? WHERE id=?", (now, existing["id"]))
                    else:
                        con.execute("UPDATE props SET captured_at=?,odds=?,odds_captured_at=? WHERE id=?",
                                    (now, odds_int, now, existing["id"]))
                elif odds_int is not None:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,odds,odds_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (game_id, player_id, market, line_val, side, "bovada", now, odds_int, now))
                else:
                    con.execute(
                        "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) VALUES(?,?,?,?,?,?,?)",
                        (game_id, player_id, market, line_val, side, "bovada", now))
                ingested += 1
        con.commit()
    finally:
        con.close()
    return ingested


def ingest_batch(batch: dict):
    """POST to the ingest API."""
    url = f"{API_BASE}/api/props/ingest"
    data = json.dumps(batch).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())




def capture_snapshots(all_props: list, league: str):
    """Write prop_odds_snapshots for existing props. Does NOT create new props."""
    import urllib.request as _ur, json as _json
    url = f"{API_BASE}/api/capture-odds"
    data = _json.dumps({"league": league, "props": all_props}).encode()
    req = _ur.Request(url, data=data, headers={"Content-Type": "application/json"})
    with _ur.urlopen(req, timeout=30) as r:
        return _json.loads(r.read().decode())

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    league = sys.argv[1]
    do_ingest = "--ingest" in sys.argv
    do_capture = "--capture" in sys.argv

    if league == "all":
        targets = list(LEAGUES.items())
    elif league in LEAGUES:
        targets = [(league, LEAGUES[league])]
    else:
        print(f"Unknown league: {league}")
        sys.exit(1)

    all_props = []
    resolve_counts = {}
    today = dt.date.today().isoformat()

    for key, (sport, lg) in targets:
        print(f"Fetching {key.upper()} from Bovada...")
        try:
            events = fetch_events(sport, lg)
        except Exception as e:
            print(f"  FAIL: {e}")
            continue

        print(f"  {len(events)} events")

        for ev in events:
            props = parse_player_props(ev, key)
            if props:
                game_desc = ev.get("description", "?")
                print(f"  {game_desc}: {len(props)} props")
                all_props.extend(props)

    print(f"\nTotal props scraped: {len(all_props)}")

    if all_props:
        # Show sample
        for p in all_props[:10]:
            line_str = f" {p['line']}" if p['line'] else ""
            print(f"  {p['player_name']} {p['side'].upper()}{line_str} {p['market']} ({p['odds']})")

        # Optionally ingest
        if do_ingest:
            # Route ingest PER PROP-LEAGUE (not the CLI arg) so `all --ingest` sends each league to the
            # right path: WC + UFC create their own players (direct DB), everything else goes through the
            # resolver API. The game date is derived from the Bovada startTime, not "today".
            by_league = {}
            for p in all_props:
                by_league.setdefault(p["league"], []).append(p)
            for lg, lprops in by_league.items():
                if lg == "wc":
                    print(f"\nDirect-ingesting WC props into DB...")
                    try:
                        print(f"  {_wc_direct_ingest(lprops, today)} props ingested")
                    except Exception as e:
                        print(f"  FAIL ingest (wc): {e}")
                elif lg == "ufc":
                    print(f"\nDirect-ingesting UFC props into DB...")
                    try:
                        print(f"  {_ufc_direct_ingest(lprops, today)} props ingested")
                    except Exception as e:
                        print(f"  FAIL ingest (ufc): {e}")
                else:
                    print(f"\nIngesting {lg.upper()} into {API_BASE}...")
                    by_game = {}
                    for p in lprops:
                        gkey = f"{p['league']}|{p['game_desc']}"
                        if gkey not in by_game:
                            by_game[gkey] = {
                                "league": p["league"],
                                "date": _wc_event_date(p, today),
                                "home": p["home_team"],
                                "away": p["away_team"],
                                "espn_event_id": "",
                                "start_time": _event_start_iso(p),
                                "props": []
                            }
                        by_game[gkey]["props"].append({
                            "player_name": p["player_name"],
                            "team": p["team"],
                            "market": p["market"],
                            "line": p["line"] or 0,
                            "side": p["side"],
                            "source": "bovada",
                            "odds": p.get("odds"),
                        })
                    lg_ingested = 0
                    lg_refreshed = 0
                    lg_unresolved = 0
                    lg_failed = 0
                    for batch in by_game.values():
                        try:
                            result = ingest_batch(batch)
                            lg_ingested += result.get("ingested") or 0
                            lg_refreshed += result.get("refreshed") or 0
                            lg_unresolved += result.get("unresolved") or 0
                            print(f"  {batch['away']} @ {batch['home']}: "
                                  f"{result['ingested']} new, {result.get('refreshed', 0)} refreshed")
                        except Exception as e:
                            lg_failed += 1
                            print(f"  FAIL ingest: {e}")
                    resolve_counts[lg] = {
                        "scraped": len(lprops),
                        "ingested": lg_ingested,
                        "refreshed": lg_refreshed,
                        "unresolved": lg_unresolved,
                        "games_failed": lg_failed,
                        "games": len(by_game),
                    }
        # Optionally capture snapshots
        if do_capture:
            print(f"\nCapturing odds snapshots...")
            try:
                result = capture_snapshots(all_props, league)
                print(f"  Snapshots: {result.get('snapshots',0)} written ({result.get('paired',0)} paired, {result.get('single',0)} single)")
            except Exception as e:
                print(f"  FAIL capture: {e}")
    else:
        print("  (no props found — games may not have started yet, or sport is out of season)")

    sys.exit(_run_report(resolve_counts, do_ingest))


def _run_report(resolve_counts: dict, did_ingest: bool) -> int:
    """Print what this run could NOT do, and return the process exit code.

    Every line here prints even when the count is zero (fail-loudly §3.7): a log that only
    speaks up on failure cannot tell "clean" from "never ran", which is the state the tennis
    ingest sat in for its whole existence -- 169 players rejected every 30 minutes behind a
    status line reading `0 ingested`.

    Exit 3 means the run wrote data AND found something a human needs to look at. It is
    deliberately not 0: a scrape that resolves none of what it scraped is a broken feed, and
    a systemd unit is the only thing that will ever notice.
    """
    problems = []

    print("\n--- run report ---")
    print(f"  unmapped player markets: {len(_UNMAPPED_PLAYER_MARKETS)}")
    for (lg, group, desc), n in sorted(_UNMAPPED_PLAYER_MARKETS.items()):
        print(f"      UNMAPPED {lg} [{group}] {desc!r}"
              f" — {n['outcomes']} outcomes across {n['events']} events, NOT ingested")
        problems.append(f"unmapped market {lg}:{desc}")

    print(f"  outcomes tagged with a club not in the fixture: {len(_STALE_TEAM_TAGS)}")
    for (name, code), game in sorted(_STALE_TEAM_TAGS.items()):
        print(f"      STALE TAG {name} ({code}) in {game} — team dropped, resolved on game_id")

    if did_ingest:
        for lg, c in sorted(resolve_counts.items()):
            resolved = c["ingested"] + c["refreshed"]
            print(f"  {lg}: resolved {resolved} of {c['scraped']} scraped"
                  f" ({c['ingested']} new, {c['refreshed']} refreshed,"
                  f" {c['unresolved']} unresolved) across {c['games']} games")
            if c["scraped"] and not resolved:
                print(f"      REJECTED all {c['scraped']} {lg} props —"
                      f" nothing in `players` matched. A count of zero is a finding.")
                problems.append(f"{lg} resolved 0 of {c['scraped']}")
            if c["games_failed"]:
                print(f"      {c['games_failed']} of {c['games']} {lg} games failed to POST")
                problems.append(f"{lg} {c['games_failed']} games failed to POST")

    if problems:
        print("\nEXIT 3 — " + "; ".join(problems))
        return 3
    print("  no problems found")
    return 0


if __name__ == "__main__":
    main()
