#!/usr/bin/env python3
"""extract_status.py -- rule-based pregame designation extractor for one (player, article) pair.

No language model is used. Rules are fixed by hand and tuned only on the dev split of gold/sample.csv. The result for a
pair is one of:
  OUT, DOUBTFUL, QUESTIONABLE   a designation for this game
  NONE                          the article states no game designation (a practice-only, cleared, roster or
                                season-level line, or an on-topic article that never mentions a designation)
  OTHER                         an official table reports a non-game status (placed on injured reserve)
  UNKNOWN                       abstain: no body, off-topic page, conflicting statements, or an ambiguous line

Route order: an official status table row on an on-topic page is read first; otherwise the article body (JSON-LD
articleBody, never the page chrome, teasers or related-story links) is read sentence by sentence.

Every result carries the exact span it came from and the rule that produced it, so each status can be audited.
"""
import html
import json
import re

from build_pool import key, name_key
import status_text as st

TEAM_TOKENS = {
    "ARI": ["arizona", "cardinals"], "ATL": ["atlanta", "falcons"], "BAL": ["baltimore", "ravens"],
    "BUF": ["buffalo", "bills"], "CAR": ["carolina", "panthers"], "CHI": ["chicago", "bears"],
    "CIN": ["cincinnati", "bengals"], "CLE": ["cleveland", "browns"], "DAL": ["dallas", "cowboys"],
    "DEN": ["denver", "broncos"], "DET": ["detroit", "lions"], "GB": ["green bay", "packers"],
    "HOU": ["houston", "texans"], "IND": ["indianapolis", "colts"], "JAX": ["jacksonville", "jaguars"],
    "KC": ["kansas city", "chiefs"], "LV": ["las vegas", "raiders"], "LAC": ["la chargers", "los angeles chargers", "chargers"],
    "LA": ["la rams", "los angeles rams", "rams"], "MIA": ["miami", "dolphins"], "MIN": ["minnesota", "vikings"],
    "NE": ["new england", "patriots"], "NO": ["new orleans", "saints"], "NYG": ["new york giants", "giants"],
    "NYJ": ["new york jets", "jets"], "PHI": ["philadelphia", "eagles"], "PIT": ["pittsburgh", "steelers"],
    "SF": ["san francisco", "49ers", "niners"], "SEA": ["seattle", "seahawks"], "TB": ["tampa bay", "buccaneers"],
    "TEN": ["tennessee", "titans"], "WAS": ["washington", "commanders"],
}
WEEK = re.compile(r"\bweek[\s-]*(\d{1,2})\b", re.I)
ARTICLE_BODY = re.compile(r'"articleBody"\s*:\s*"((?:[^"\\]|\\.)*)"')
HEADLINE = re.compile(r'"headline"\s*:\s*"((?:[^"\\]|\\.)*)"')
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s*(?=[A-Z0-9\"(])|;\s+")

OUT_PATTERNS = [
    re.compile(r"\b(?:officially |was |were |been |are |is )?ruled out\b", re.I),
    re.compile(r"\b(?:downgraded|listed|ruled)\b[^.;]*?\b(?:to|as) out\b", re.I),
    re.compile(r"\b(?:is|are) out\b(?! (?:of|there|for the season|with))", re.I),
    re.compile(r"\bOUT\b"),
]
DOUBTFUL = re.compile(r"\bdoubtful\b", re.I)
QUESTIONABLE = re.compile(r"\bquestionable\b", re.I)
CLEARED = re.compile(r"\b(lifted|cleared|no longer|upgraded|activated|removed from|"
                     r"ready to go|good to go|off the injury report|taken off)\b", re.I)
NEGATED_CLEAR = re.compile(r"\bnot (?:been |officially |yet |fully )*(?:cleared|lifted|upgraded)\b", re.I)
ROSTER = re.compile(r"\b(waived|waiver|signed|released|practice squad|elevated|promoted|claimed|traded)\b", re.I)
SEASON = re.compile(r"\b(season-ending|season ending|for the season|rest of the season|injured reserve|placed on ir|"
                    r"reserve/injured|reserve/ir)\b", re.I)
PRACTICE_ONLY = re.compile(r"\b(limited participant|did not practice|did not participate|full practice)\b|\bDNP\b|\bLP\b|\bFP\b", re.I)
HISTORY = re.compile(r"\b(last week|previous week|prior week|recap|teaser|preview)\b", re.I)
TABLE_OTHER = re.compile(r"\b(placed on ir|injured reserve|reserve)\b", re.I)


def json_string(raw):
    try:
        return html.unescape(json.loads('"' + raw + '"')).replace("\xa0", " ").replace("’", "'")
    except ValueError:
        return None


def article(page):
    """Return (body, topic). body is None when the page has no JSON-LD articleBody."""
    m = ARTICLE_BODY.search(page)
    body = json_string(m.group(1)) if m else None
    heads = [json_string(h.group(1)) or "" for h in HEADLINE.finditer(page)]
    title = html.unescape(TITLE.search(page).group(1)) if TITLE.search(page) else ""
    return body, " | ".join([title] + heads)


def body_sentences(body):
    out = []
    for line in body.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            out.extend(part.strip() for part in SENT_SPLIT.split(line) if part and part.strip())
    return out


def opponent(game_id, team):
    _, _, away, home = game_id.split("_")
    return home if team == away else away


def on_topic(game_id, team, week, topic, url):
    """True only when the page names this week or this game's opponent, and names no other week."""
    text = (topic + " " + url.replace("-", " ")).lower()
    weeks = {int(w) for w in WEEK.findall(text)}
    if weeks - {week} and week not in weeks:
        return False, "topic_other_week"
    opp_tokens = TEAM_TOKENS.get(opponent(game_id, team), [])
    if week in weeks or any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", text) for t in opp_tokens):
        return True, "topic_match"
    return False, "topic_no_match"


def name_in(sentence, player):
    return re.search(r"(?<![a-z])" + re.escape(name_key(player)) + r"(?![a-z])", key(sentence)) is not None


def table_route(page, player, week, game_id, team, topic, url):
    rows, _ = st.status_tables(page)
    row = next((r for r in rows if key(st.table_player(r.get("Player", ""))) == name_key(player)), None)
    if row is None:
        return None
    ok, why = on_topic(game_id, team, week, topic, url)
    if not ok:
        return ("UNKNOWN", why, "", "table")
    raw = st.status_column(row).strip()
    token = raw.lower().strip("()- ").strip()
    if raw in {"", "-", "--", "(-)", "----"} or token == "":
        return ("NONE", "table_blank_or_dash", raw, "table")
    if token in ("out", "doubtful", "questionable"):
        return (token.upper(), "table_game_status", raw, "table")
    if TABLE_OTHER.search(raw):
        return ("OTHER", "table_injured_reserve", raw, "table")
    return ("UNKNOWN", "table_unrecognised_status", raw, "table")


def classify_sentence(sentence):
    """Return the set of designation classes a sentence states, and the rule that matched."""
    found = set()
    if any(p.search(sentence) for p in OUT_PATTERNS):
        found.add("OUT")
    if DOUBTFUL.search(sentence):
        found.add("DOUBTFUL")
    if QUESTIONABLE.search(sentence):
        found.add("QUESTIONABLE")
    return found


def narrative_route(body, player, week, game_id, team):
    decisions = []
    for s in body_sentences(body):
        if not name_in(s, player):
            continue
        weeks = {int(w) for w in WEEK.findall(s)}
        if weeks - {week}:
            continue  # a sentence about another week or game is not evidence for this one
        if HISTORY.search(s):
            continue
        classes = classify_sentence(s)
        if CLEARED.search(NEGATED_CLEAR.sub("", s)):
            decisions.append(("NONE", "cleared", s))
        elif SEASON.search(s):
            decisions.append(("NONE", "season_or_reserve", s))
        elif ROSTER.search(s) and not classes:
            decisions.append(("NONE", "roster_move", s))
        elif PRACTICE_ONLY.search(s) and not classes:
            decisions.append(("NONE", "practice_only", s))
        elif len(classes) == 1:
            decisions.append((classes.pop(), "explicit_designation", s))
        elif len(classes) > 1:
            decisions.append(("UNKNOWN", "conflicting_designations", s))
        else:
            decisions.append(("NONE", "mention_no_designation", s))
    return decisions


EXPLICIT_NONE = {"cleared", "season_or_reserve"}


def combine(decisions):
    """Collapse per-sentence decisions into one status. Any disagreement among designation lines abstains."""
    designations = [d for d in decisions if d[0] in ("OUT", "DOUBTFUL", "QUESTIONABLE", "UNKNOWN")]
    if designations:
        labels = {d[0] for d in designations}
        clears = [d for d in decisions if d[1] in EXPLICIT_NONE]
        if clears:
            return "UNKNOWN", "designation_vs_clearance_conflict", " || ".join(d[2] for d in designations + clears)[:600]
        if len(labels) == 1 and "UNKNOWN" not in labels:
            status, rule, span = designations[0]
            return status, rule, span
        return "UNKNOWN", "designation_conflict", " || ".join(d[2] for d in designations)[:600]
    if decisions:
        status, rule, span = decisions[0]
        return status, rule, span
    return "UNKNOWN", "no_player_mention", ""


def extract(page, player, game_id, team, week, url):
    """Return a dict with predicted status, the rule that produced it, the exact span and the route."""
    body, topic = article(page)
    if body is None:
        return dict(status="UNKNOWN", rule="no_article_body", span="", route="none")
    tab = table_route(page, player, week, game_id, team, topic, url)
    if tab is not None:
        status, rule, span, route = tab
        return dict(status=status, rule=rule, span=span, route=route)
    ok, why = on_topic(game_id, team, week, topic, url)
    if not ok:
        return dict(status="UNKNOWN", rule=why, span="", route="narrative")
    status, rule, span = combine(narrative_route(body, player, week, game_id, team))
    return dict(status=status, rule=rule, span=span[:600], route="narrative")
