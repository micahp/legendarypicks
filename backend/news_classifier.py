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
import re


def _term_present(t: str, term: str) -> bool:
    """Word-boundary substring match for league/notable terms.

    Plain `term in t` collides with common substrings: "acc" matched
    "accepting" (stealing an NHL story into NCAAF), "nba" matched "wnba",
    "stars" matched "superstar", "alba" matched "Albarado" (2026-08-08).
    """
    return re.search(r"\b" + re.escape(term) + r"\b", t) is not None


_HANDLE_RE = re.compile(r"^\[@[^\]]+\]\s*")
_ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z'\u2019.-]{2,})(?:\s+([A-Z][a-zA-Z'\u2019.-]{2,}))?")


def entities(headline: str) -> set:
    """Capitalized TWO-word sequences from a headline — a proper-noun proxy.

    Two words, not one: single capitalized tokens are first names and sentence
    openers ("larry", "mike", "red", "after") and they swamp any ranking built
    on them. Lives here because both the discovery pass and the collector's
    article-derived social queries need the same extraction (2026-08-10).
    """
    h = _HANDLE_RE.sub("", headline or "")
    out = set()
    for m in _ENTITY_RE.finditer(h):
        one, two = m.group(1), m.group(2)
        if not two:
            continue
        if one.lower() in _ENTITY_STOPWORDS or two.lower() in _ENTITY_STOPWORDS:
            continue
        out.add(("%s %s" % (one, two)).lower())
    return out


def _norm(s: str) -> str:
    """Lowercase, hyphens to spaces, whitespace collapsed.

    Hyphens are a publisher's style choice, not a meaning: "way-too-early"
    and "way too early" are the same phrase, and only one of them was ever in
    a rule list. Normalizing both the text and the terms means a rule is
    written once (2026-08-09).
    """
    return " ".join(re.sub(r"[-‐-―]", " ", (s or "").lower()).split())


def _any_term(t_norm: str, terms: List[str]) -> bool:
    """True if any term appears as a WHOLE WORD (or whole phrase) in t_norm.

    The layer rules used bare `term in t`, so "sign" matched *assignment*,
    "deal" matched *dealing*, "broadcast" matched *broadcaster*, and "out for"
    matched *standout forward* — 44 of the served rows rested on a match like
    that (measured 2026-08-09, the "multiple tags having a false positive"
    Micah reported). Inflections are listed explicitly in the rules instead.
    """
    return any(_term_present(t_norm, _norm(term)) for term in terms)

# Words that look like entities but never name a story.
_ENTITY_STOPWORDS = {
    "the", "this", "that", "what", "why", "how", "when", "who", "his", "her",
    "new", "top", "best", "first", "last", "next", "one", "two", "three",
    "game", "games", "highlights", "week", "season", "day", "night", "report",
    "reports", "sources", "source", "news", "update", "updates", "live",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "espn", "vs",
}

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
            "austin fc", "dc united", "dynamo", "real salt lake", "relegation",
            "pro/rel", "usl", "usl championship", "lower division soccer", "mls next pro",
            "leagues cup"],
    "ncaaf": ["sec", "big ten", "big 12", "acc", "pac-12", "college football", "cfp",
              "playoff", "bowl game", "alabama", "georgia", "ohio state", "michigan",
              "notre dame", "lsu", "clemson", "oklahoma", "oregon", "usc",
              "longhorns", "texas a&m", "texas tech", "aggies", "red raiders",
              "baylor", "tcu", "smu", "purdue", "saban", "super conference", "superleague"],
    "nba": ["nba", "lakers", "celtics", "warriors", "nuggets", "bucks", "heat", "knicks",
            "76ers", "suns", "mavericks", "thunder", "cavaliers", "timberwolves",
            "clippers", "kawhi", "lebron"],
    "nhl": ["nhl", "bruins", "rangers", "maple leafs", "oilers", "avalanche", "golden knights",
            "panthers", "hurricanes", "stars", "penguins", "blues", "red wings"],
    "ufc": ["ufc", "mma", "octagon", "paddy pimblett", "islam makhachev", "jon jones",
            "alex pereira", "conor mcgregor", "dana white"],
    "esports": ["esports", "league of legends", "lol esports", "lcs", "lec", "worlds",
                "valorant", "vct", "champions tour", "counter-strike", "cs2", "csgo",
                "dota 2", "the international", "rainbow six", "overwatch league", "owl",
                "call of duty league", "cdl", "giantx", "fnatic", "g2 esports", "t1 esports",
                "faker", "sentinels", "navi", "vitality", "team liquid", "cloud9"],
}

# Non-trade layers first (most specific). Staff = decision verbs only; "fired up"
# is stripped before matching so Gruden-style clickbait never reads as a firing.
INJURY_RULES = ["injury", "injuries", "injured", "out for", "out 4 5", "surgery",
                "torn", "sprain", "sprains", "strain", "strains", "doubtful",
                "questionable", "day to day", "injured reserve",
                "hamstring", "ankle", "knee", "shoulder", "fracture", "fractured",
                "concussion", "placed on ir", "15 day injured list",
                "10 day injured list"]
STAFF_RULES = ["fired", "fire", "fires", "firing", "hired", "hires", "hire", "hiring",
               "named", "names", "appointed", "appoints", "resigns", "resigned",
               "stepping down", "steps down", "dismissed", "let go", "parting ways",
               "promoted to", "takes over as"]
# A league-level storyline, not a transaction and not a media-business item.
# Bare "conference"/"major"/"offseason"/"broadcast" were removed 2026-08-09:
# "press conference", "major league", "offseason" and "broadcaster" appear in
# ordinary wire copy and dragged unrelated items onto the board.
NARRATIVE_RULES = ["salary cap", "salary floor", "relegation", "promotion",
                   "super conference", "superleague", "realignment", "expansion",
                   "cba", "lockout", "media rights", "broadcast rights", "tv deal",
                   "negotiations", "lawsuit", "settlement", "playoff format",
                   "rule change", "cap and floor", "cap debate",
                   "conference realignment", "worlds", "champions tour",
                   "grand final"]

# A transaction actually happened (or was announced): the verb asserts it.
# Whole-word matching is what makes "sign" safe here: as a substring it matched
# *assignment*, *design* and *signal*; as a word it only matches the verb.
TRADE_ACTUAL = ["traded", "acquire", "acquired", "acquires", "sign", "signed",
                "signing", "signs", "extension", "re-sign", "re-signs", "free agent",
                "contract", "deal", "deals", "swap", "released", "release",
                "waive", "waived", "waives", "loan", "loaned", "inks",
                "agree to", "agreed to", "for assignment", "claimed off waivers"]
# Definitive roster-status statements — "no plans to trade X" is real signal.
TRADE_DEFINITIVE = ["no plans to trade", "refuses to trade", "not trading",
                    "won't trade", "will not trade", "ruled out", "no intention",
                    "unwilling to trade", "not for sale"]
# Strong speculation markers — listicle/projection phrases. Checked FIRST:
# an article that is a projection or a "10 best" list is not news even when its
# body mentions a real transaction or a fired coach.
STRONG_SPEC = ["projecting", "projection", "predict", "prediction", "ranked",
               "ranking", "the 10 best", "10 best", "top 10", "realistic",
               "package", "packages", "should happen", "under-the-radar",
               "landing spots", "destinations", "trade value", "way too early",
               "mock trade", "fantasy trade", "biggest impact", "next in line",
               "that'll make", "would be the best", "who should", "watch list",
               "winners and losers", "could actually", "steals",
               # 2026-08-09: the pieces that still reached the board because a
               # later rule (injury/narrative) matched first.
               "trade candidates", "trade deadline plans", "is needed",
               "should target", "wish list", "best remaining", "grades",
               # inflections — whole-word matching means each form is its own
               # rule ("predict" no longer covers "predicting").
               "predicting", "predictions", "projections", "ranks", "rankings",
               "realistically", "candidates"]
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
    "mlb": ["ohtani", "shohei", "mookie", "betts", "freeman", "aaron judge", "soto", "harper",
            "acuna", "trout", "wheeler", "burnes"],
    "mls": ["messi", "suarez", "busquets", "alba", "reus", "pulisic", "lodeiro"],
    "ncaaf": ["saban", "kirby smart", "ryan day", "james franklin", "lane kiffin", "dabo"],
    "nba": ["lebron", "luka", "giannis", "jokic", "tatum", "curry", "shai", "ant man"],
    "nhl": ["mcdavid", "draisaitl", "mackinnon", "pastrnak", "panarin"],
    "esports": ["faker", "caps", "chovy", "s1mple", "zywoo", "demon1", "tenz", "aspas"],
}


def classify(text: str, source_hint: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Return {league, layer, key_player} for a headline+body blob.

    Layers: narrative | trade | staff | injury | speculation | other.
    `speculation` is never served by the API — it exists so the board stays
    clean (trade rumors/packages/projections are not news).
    """
    t = _norm(text)
    t_no_fired_up = t.replace("fired up", " ")

    league: Optional[str] = None
    for lg, terms in LEAGUE_TERMS.items():
        if any(_term_present(t, term) for term in terms):
            league = lg
            break
    if league is None and source_hint in LEAGUE_TERMS:
        league = source_hint
    if league is None:
        league = "unclassified"
    # "Giants" is ambiguous (NYG = nfl, SF = mlb). A Giants *broadcaster*
    # retiring/stepping away is the MLB San Francisco Giants.
    if league == "nfl" and _term_present(t, "giants") and any(
            w in t for w in ("broadcast", "broadcasts", "broadcaster", "retiring",
                             "retirement", "step away")):
        league = "mlb"

    layer = "other"
    if _any_term(t, STRONG_SPEC):
        layer = "speculation"
    elif _any_term(t, INJURY_RULES):
        layer = "injury"
    elif _any_term(t_no_fired_up, STAFF_RULES):
        layer = "staff"
    elif _any_term(t, NARRATIVE_RULES):
        layer = "narrative"
    else:
        if _any_term(t, TRADE_ACTUAL):
            layer = "trade"
        elif _term_present(t, "trade") or _term_present(t, "trades"):
            if _any_term(t, TRADE_DEFINITIVE):
                layer = "trade"
            elif _any_term(t, WEAK_SPEC):
                layer = "speculation"
            else:
                # bare trade mention with no transaction verb and no definitive
                # stance — a rumor or a generic mention; do not serve it
                layer = "speculation"
        elif _any_term(t, WEAK_SPEC):
            # rumor-flavored piece without the word trade
            layer = "speculation"

    key_player: Optional[str] = None
    for lg, names in NOTABLE.items():
        for n in names:
            if _term_present(t, n):
                key_player = n.title()
                break
        if key_player:
            break

    return {"league": league, "layer": layer, "key_player": key_player}
