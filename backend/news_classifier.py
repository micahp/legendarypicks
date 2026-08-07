#!/usr/bin/env python3
"""news_classifier.py — two-layer league news classification for the news engine.

Layer 1 (narrative): the league's dominant story right now — what people are
actually talking about. Raw headlines for the POC; the target (Micah,
2026-08-06) is LinkedIn-trending-style AI-generated narrative summaries built
from the chatter signal.

Layer 2 (granular): trades, staff decisions, injuries to key/notable players.
TRADE SPECULATION IS NOT NEWS (Micah, 2026-08-06): "realistic packages for
Jonathan Taylor", "top 10 trades that should happen", trade-value and
projection pieces are classified `speculation` and never served. Only
confirmed transactions (acquired/signed/released/extension) or definitive
statements ("no plans to trade X", "ruled out") stay `trade`. Staff means a
decision happened (fired/hired/resigned/stepping down) — commentary that merely
mentions coaches/managers ("Preseason coaches poll…") is not staff.

Keyword-rule based for the POC. Player lookups are O(1) by design — the
notable-name list here is a POC placeholder; the real feature does an indexed
by-name lookup against `players` only when a news item makes a name relevant
(Micah, 2026-08-06). Never a full-table scan.
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

# Non-trade layers first (most specific). Staff = decision verbs only; "fired up"
# is stripped before matching so Gruden-style clickbait never reads as a firing.
INJURY_RULES = ["injury", "injured", "out for", "out 4-5", "surgery", "torn", "sprain",
                "strain", "doubtful", "questionable", "day-to-day", "injured reserve",
                "hamstring", "ankle", "knee", "shoulder", "fracture", "concussion",
                "placed on ir"]
STAFF_RULES = ["fired", "fire", "fires", "firing", "hired", "hire", "hiring",
               "named", "appointed", "resigns", "resigned", "stepping down",
               "departs", "departure", "dismissed", "let go", "parting ways",
               "promoted to", "takes over as"]
NARRATIVE_RULES = ["salary cap", "salary floor", "relegation", "promotion",
                   "super conference", "superleague", "realignment", "expansion",
                   "cba", "lockout", "media rights", "broadcast", "tv deal",
                   "negotiations", "lawsuit", "settlement", "playoff format",
                   "rule change", "cap and floor", "cap debate", "conference"]

# A transaction actually happened (or was announced): the verb asserts it.
TRADE_ACTUAL = ["traded", "acquire", "acquired", "acquires", "sign", "signed", "signing",
                "extension", "re-sign", "free agent", "contract", "deal", "swap",
                "released", "release", "waive", "waived", "loan", "loaned", "inks",
                "agree to", "agreed to"]
# Definitive roster-status statements — "no plans to trade X" is real signal.
TRADE_DEFINITIVE = ["no plans to trade", "refuses to trade", "not trading",
                    "won't trade", "will not trade", "ruled out", "no intention",
                    "unwilling to trade", "not for sale"]
# Strong speculation markers — listicle/projection phrases. Checked FIRST:
# an article that is a projection or a "10 best" list is not news even when its
# body mentions a real transaction or a fired coach.
STRONG_SPEC = ["projecting", "projection", "predict", "prediction", "ranked",
               "ranking", "the 10 best", "10 best", "top 10", "realistic",
               "packages", "should happen", "under-the-radar", "landing spots",
               "destinations", "trade value", "way too early", "mock trade",
               "fantasy trade", "biggest impact", "next in line", "that'll make",
               "would be the best", "who should", "watch list", "winners and losers",
               "could actually", "steals"]
# Weak speculation markers — only meaningful with a bare trade mention.
WEAK_SPEC = ["rumor", "rumours", "speculation", "speculate", "could land",
             "could be", "might be", "would be", "potential", "buzz", "mulling",
             "exploring", "reportedly considering", "open to trading",
             "asking price", "trades that", "dream trade", "could actually"]

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

    Layers: narrative | trade | staff | injury | speculation | other.
    `speculation` is never served by the API — it exists so the board stays
    clean (trade rumors/packages/projections are not news).
    """
    t = (text or "").lower()
    t_no_fired_up = t.replace("fired up", " ")

    league: Optional[str] = None
    for lg, terms in LEAGUE_TERMS.items():
        if any(term in t for term in terms):
            league = lg
            break
    if league is None and source_hint in LEAGUE_TERMS:
        league = source_hint
    if league is None:
        league = "unclassified"
    # "Giants" is ambiguous (NYG = nfl, SF = mlb). A Giants *broadcaster*
    # retiring/stepping away is the MLB San Francisco Giants.
    if league == "nfl" and "giants" in t and any(
            w in t for w in ("broadcast", "broadcasts", "broadcaster", "retiring",
                             "retirement", "step away")):
        league = "mlb"

    layer = "other"
    if any(w in t for w in STRONG_SPEC):
        layer = "speculation"
    elif any(w in t for w in INJURY_RULES):
        layer = "injury"
    elif any(w in t_no_fired_up for w in STAFF_RULES):
        layer = "staff"
    elif any(w in t for w in NARRATIVE_RULES):
        layer = "narrative"
    else:
        if any(w in t for w in TRADE_ACTUAL):
            layer = "trade"
        elif "trade" in t or "trades" in t:
            if any(w in t for w in TRADE_DEFINITIVE):
                layer = "trade"
            elif any(w in t for w in WEAK_SPEC):
                layer = "speculation"
            else:
                # bare trade mention with no transaction verb and no definitive
                # stance — a rumor or a generic mention; do not serve it
                layer = "speculation"
        elif any(w in t for w in WEAK_SPEC):
            # rumor-flavored piece without the word trade
            layer = "speculation"

    key_player: Optional[str] = None
    for lg, names in NOTABLE.items():
        for n in names:
            if n in t:
                key_player = n.title()
                break
        if key_player:
            break

    return {"league": league, "layer": layer, "key_player": key_player}
