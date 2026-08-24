"""config — Bovada scraper config layer."""
import re
import json
import os
import sys
import collections
import datetime as dt
import unicodedata
import urllib.request


API_BASE = os.environ.get("LP_API_BASE", "http://localhost:8000")

BOVADA = "https://www.bovada.lv/services/sports/event/coupon/events/A/description"

LEAGUES = {
    "mlb":  ("baseball", "mlb"),
    "nba":  ("basketball", "nba"),
    "nfl":  ("football", "nfl"),
    "nhl":  ("hockey", "nhl"),
    "wnba": ("basketball", "wnba"),
    "wc":   ("soccer", "fifa-world-cup/fifa-world-cup-matches"),
    # MLS was here from 2026-08-16 until later the same day, on the continent path
    # `soccer/north-america/united-states/mls` (`soccer/usa/mls` 404s). It scraped fine —
    # 1,461 of 1,464 published player outcomes, 8 markets.
    #
    # It is REMOVED because Bovada cannot price the markets this league is being built for.
    # Of the eleven that matter — shots, shots on target, passes attempted, goals, goalie
    # saves, clearances, assists, attempted dribbles, tackles, crosses, fouls — Bovada
    # publishes two. MLS props now come from the RotoWire/PrizePicks relay, which prices
    # seven (see docs/ROTOWIRE-PICKS-RELAY.md and ingest_rotowire_mls_props.py). Keeping a
    # second book writing goals and assists into the same board would mean two sources
    # disagreeing on a league where one of them answers almost none of the question.
    #
    # Historical Bovada MLS rows are kept, not deleted; the reader's source policy selects
    # the relay. `_parse_mls_props` stays in this file — it is measured, tested, and the
    # league is one line away if the relay does not work out.
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

# Per-league backoff state: {league: {"last_empty_at": iso, "empty_runs": n}}.
# Kept beside the DB rather than in it — it is operational scheduling, not app data.
# One dirname per directory this file sits below `backend/`. The split moved
# it into a package, so this needs TWO -- with one it resolved to
# `backend/<package>/data/`, which does not exist, and sqlite3.connect
# CREATES the file rather than failing. The job would run against an empty
# database and report success.
_BACKOFF_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "bovada-league-backoff.json")

# An out-of-season league is asked for again after this long. UFC sits at zero players
# between cards, tennis between tournaments, WNBA/NBA out of season — and this scraper ran
# `all` every 30 minutes regardless, so each of those cost 48 requests a day to be told
# "no board" 48 times. Bovada gives this API away with no auth and no key; asking it 48
# times for an answer that changed once is a cost we push onto them for nothing.
_EMPTY_RUNS_BEFORE_BACKOFF = 3

_BACKOFF_HOURS = 6

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

# Clubs that belong to MLS. A Bovada soccer event whose two dominant player codes
# are BOTH in this set is an MLS regular-season fixture. If either is a foreign
# club (AME/GDL/PUE/TOL... Liga MX in a Leagues Cup fixture, NFO in a friendly),
# the fixture is a TOURNAMENT and must file under `lcup` -- its own competition
# key -- so the players stay resolvable against whichever league actually rosters
# them. Filing Leagues Cup under `mls` is the shadow-player defect: it creates
# players nobody's MLS spine can ever resolve (see _MINTED_PLAYERS note below).
_MLS_CLUB_CODES = frozenset({
    "ATL", "ATX", "MTL", "CLT", "CHI", "COL", "CLB", "DC", "CIN", "DAL",
    "HOU", "MIA", "LA", "LAFC", "MIN", "NSH", "NE", "NYC", "RBNY", "ORL",
    "PHI", "POR", "RSL", "SD", "SJ", "SEA", "SKC", "STL", "TOR", "VAN",
})

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

# [(league, name)] for every `players` row this run created from a sportsbook display name
# with no publisher id behind it. Only the wc and ufc direct-DB paths can do this; every
# other league goes through the resolver, which never creates. Printed by main() at zero
# too -- a mint that reads the same as a match in the log is how 531 shadow MLS players
# reached prod without anyone noticing.
_MINTED_PLAYERS = []

# Leagues skipped this run by the backoff, named in the report so a rest is never
# mistaken for a league that produced nothing.
_RESTED_LEAGUES = []

# {(league, market_head, team_name): n} for outcomes whose "player" is one of the fixture's
# own competitors. Bovada files team totals inside groups named "Game Props" and "Score
# Props" -- "Highest Scoring Quarter Total Points O/U - Boston Celtics" splits exactly like
# a player market does, so the club lands in player_name and the resolver rejects it. On
# 2026-08-24 that was all 120 NBA outcomes, and the resulting "resolved 0 of 120" exit 3
# took the whole unit down while Bovada was publishing no NBA player props at all.
# Counted, not silenced: a league whose only offering is team markets must read differently
# from a league that scraped nothing.
_TEAM_LEVEL_OUTCOMES = {}

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
