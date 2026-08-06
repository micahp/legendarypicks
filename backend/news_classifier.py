#!/usr/bin/env python3
"""news_classifier.py — two-layer league news classification for the news engine.

Layer 1 (narrative): the league's dominant story right now.
Layer 2 (granular): trades, staff decisions, injuries to key/notable players.

Keyword-rule based for the POC (2026-08-06). The real feature may move the
narrative layer to an LLM pass; granular detection stays rule-based (fast,
deterministic). Player lookups are O(1) by design — the notable-name list here
is a POC placeholder; the real feature does an indexed by-name lookup against
`players` only when a news item makes a name relevant (Micah, 2026-08-06).
"""
from typing import Dict, List, Optional

LEAGUE_TERMS: Dict[str, List[str]] = {
    "nfl": ["nfl", "chiefs", "eagles", "49ers", "cowboys", "ravens", "bills", "lions",
            "vikings", "packers", "bengals", "dolphins", "jets", "giants", "steelers",
            "broncos", "seahawks", "buccaneers", "saints", "colts", "texans", "jaguars",
            "titans", "panthers", "falcons", "commanders", "patriots", "bears", "browns",
            "cardinals", "chargers", "rams", "raiders"],
    "mlb": ["mlb", "dodgers", "yankees", "mets", "red sox", "cubs", "phillies", "braves",
            "astros", "padres", "orioles", "brewers", "guardians", "twins", "mariners",
            "rangers", "giants", "cardinals", "white sox", "rays", "blue jays", "tigers",
            "royals", "athletics", "pirates", "reds", "rockies", "diamondbacks", "marlins",
            "nationals", "angels", "world series"],
    "mls": ["mls", "inter miami", "lafc", "galaxy", "sounders", "timbers", "atlanta united",
            "toronto", "austin fc", "charlotte", "cincinnati", "colorado", "columbus",
            "dallas", "dc united", "dynamo", "kansas city", "minnesota", "montreal",
            "nashville", "new england", "new york", "orlando", "philadelphia",
            "real salt lake", "san jose", "st. louis", "vancouver", "relegation"],
    "ncaaf": ["sec", "big ten", "big 12", "acc", "pac-12", "college football", "cfp",
              "playoff", "bowl game", "alabama", "georgia", "ohio state", "michigan",
              "texas", "notre dame", "lsu", "clemson", "oklahoma", "oregon", "usc",
              "saban", "super conference", "superleague"],
    "nba": ["nba", "lakers", "celtics", "warriors", "nuggets", "bucks", "heat", "knicks",
            "76ers", "suns", "mavericks", "thunder", "cavaliers", "timberwolves"],
    "nhl": ["nhl", "bruins", "rangers", "maple leafs", "oilers", "avalanche", "golden knights",
            "panthers", "hurricanes", "stars", "penguins"],
}

# Granular checked first (most specific), then narrative, then transactions.
# Media-rights / CBA / realignment words are narrative even when they co-occur
# with "deal" or "agreement" (e.g. Fox backing out of NFL negotiations).
LAYER_RULES: List[tuple] = [
    ("injury", ["injury", "injured", "out for", "out 4-5", "surgery", "torn", "sprain",
                "strain", "doubtful", "questionable", "day-to-day", "injured reserve",
                "hamstring", "ankle", "knee", "shoulder", "fracture", "concussion",
                "placed on ir"]),
    ("staff", ["fired", "firing", "fire", "fires", "hire", "hired", "hiring", "coach",
               "coaching", "manager", "coordinator", "general manager", "front office",
               "stepping down", "resigns", "interim", "departs", "departure"]),
    ("narrative", ["salary cap", "salary floor", "relegation", "promotion",
                   "super conference", "superleague", "realignment", "expansion",
                   "cba", "lockout", "media rights", "broadcast", "tv deal",
                   "negotiations", "lawsuit", "settlement", "playoff format",
                   "rule change", "cap and floor", "cap debate", "conference"]),
    ("trade", ["trade", "traded", "acquire", "acquired", "acquires", "sign", "signed",
               "extension", "re-sign", "free agent", "contract", "deal for",
               "swap", "agreement"]),
]

# POC placeholder — real feature: O(1) by-name lookup against `players` per
# candidate mention. Never a full-table scan.
NOTABLE: Dict[str, List[str]] = {
    "nfl": ["mahomes", "josh allen", "jalen hurts", "burrow", "lamar", "herbert", "stroud",
            "purdy", "saquon", "mccaffrey", "tyreek", "kelce", "jefferson", "jamarr",
            "aja brown", "jettas"],
    "mlb": ["ohtani", "shohei", "mookie", "betts", "freeman", "judge", "soto", "harper",
            "acuna", "trout", "wheeler", "burnes"],
    "mls": ["messi", "suarez", "busquets", "alba", "reus", "pulisic", "lodeiro"],
    "ncaaf": ["saban", "kirby smart", "ryan day", "james franklin", "lane kiffin", "dabo"],
    "nba": ["lebron", "luka", "giannis", "jokic", "tatum", "curry", "shai", "ant man"],
    "nhl": ["mcdavid", "draisaitl", "mackinnon", "pastrnak", "panarin"],
}


def classify(text: str, source_hint: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Return {league, layer, key_player} for a headline+body blob.

    `source_hint` is the league from the source itself (e.g. "espn-mlb" → "mlb"),
    used only when keyword rules find no league signal.
    """
    t = (text or "").lower()

    league: Optional[str] = None
    for lg, terms in LEAGUE_TERMS.items():
        if any(term in t for term in terms):
            league = lg
            break
    if league is None and source_hint in LEAGUE_TERMS:
        league = source_hint
    if league is None:
        league = "unclassified"

    layer = "other"
    for name, words in LAYER_RULES:
        if any(w in t for w in words):
            layer = name
            break

    key_player: Optional[str] = None
    for lg, names in NOTABLE.items():
        for n in names:
            if n in t:
                key_player = n.title()
                break
        if key_player:
            break

    return {"league": league, "layer": layer, "key_player": key_player}
