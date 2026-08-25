"""Bovada market names -> the stat key a game log actually stores.

Lifted out of `_core.py` unchanged. Pure data plus one string normaliser: no
database, no network, nothing imported from `_core`, which is why it comes out
first and cleanly.

A market that maps to None is charted as "not available" rather than guessed —
a fabricated stat key does not raise, it draws the wrong line.
"""

_MARKET_STAT_KEY = {
    "mlb": {"total_bases": "TB", "hits": "H", "home_runs": "HR", "walks": "BB",
            "doubles": "2B", "total_doubles": "2B", "triples": "3B", "total_triples": "3B",
            "total_home_runs": "HR", "total_hits": "H", "total_walks": "BB",
            "total_bases_allowed": None,
            # compound: sum across 3 stat keys. Real Bovada market string is
            # "total_hits,_runs_and_rbis" (comma + "total_" prefix + spelled-out "and") —
            # mapping under the clean "hits_runs_rbis" name alone never matches what
            # _base_market() actually produces from real prop rows, so the chart silently
            # never fires from the real UI. Keep both keys: the real one so it actually
            # works, the clean one in case a future source names it plainly.
            "total_hits,_runs_and_rbis": ["H", "R", "RBI"],
            "hits_runs_rbis": ["H", "R", "RBI"],
            # Pitcher markets (ingest_mlb_pitcher_logs.py)
            "strikeouts": "K", "outs": "outs", "hits_allowed": "hits_allowed",
            "pitcher_walks": "BB", "total_pitcher_walks": "BB",
            "earned_runs": "earned_runs"},
    "nba": {"points": "PTS", "rebounds": "REB", "assists": "AST", "threes": "3PM",
            "steals": "STL", "blocks": "BLK", "turnovers": "TO",
            "points_rebounds_assists": "PRA", "pra": "PRA"},
    "nhl": {"goals": "goals", "assists": "assists", "points": "points",
            "shots": "shots", "shots_on_goal": "shots"},
    "nfl": {"passing_yards": "passing_yards", "rushing_yards": "rushing_yards",
            "receiving_yards": "receiving_yards", "receptions": "receptions",
            "passing_tds": "passing_tds", "rushing_tds": "rushing_tds",
            "receiving_tds": "receiving_tds", "interceptions": "interceptions"},
    "wc": {"goals": "goals", "assists": "assists", "shots": "shots",
           "shots_on_target": "sot", "shots_on_goal": "sot"},
    # MLS game logs store the same soccer stat shape as WC (goals/assists/shots/sot)
    "mls": {"goals": "goals", "assists": "assists", "shots": "shots",
            "shots_on_target": "sot", "shots_on_goal": "sot"},
    # Leagues Cup. The stat keys are the ones ingest_soccer_logs actually writes
    # (see _STAT_ORDER), verified against real lcup rows rather than assumed.
    # `goal_or_assist` is a COMPOUND market: the chart sums the listed fields, so
    # it charts as goals+assists per game rather than needing a stored column.
    #
    # CORRECTED 2026-08-25: tackles, clearances, crosses, passes attempted and
    # shot assists were mapped to None here on the measurement "ESPN publishes
    # none of them, 0 of 1,640 log rows". That measured the SUMMARY endpoint,
    # which carries 14 per-player fields. The CORE api carries 108 for the same
    # fixture and publishes all five. The gap was the endpoint we asked, not the
    # publisher -- the exact rule stated at the top of ingest_soccer_logs.
    # `ingest_soccer_logs --deep` writes them; a row from a shallow run simply
    # lacks the key and charts as "no data" rather than as a zero.
    #
    # dribbles stays None because it is genuinely absent: the core api publishes
    # groundDuels and duelWinPct, which are NOT take-ons and must not stand in
    # for them. first_goal_scorer stays None because it is an ORDER market and
    # no per-game stat answers it.
    "lcup": {"goals": "goals", "assists": "assists", "shots": "shots",
             "shots_on_target": "sot", "shots_on_goal": "sot",
             "goal_or_assist": ["goals", "assists"],
             "fouls_committed": "fouls_committed",
             "saves": "saves", "goals_allowed": "goals_conceded",
             "card_shown": ["yellow_cards", "red_cards"],
             "tackles": "tackles", "clearances": "clearances",
             "crosses": "crosses", "passes_attempted": "passes_attempted",
             "passes": "passes", "shots_assisted": "shots_assisted",
             "dribbles": None, "first_goal_scorer": None},
    # fight_time (minutes, from round+clock at the ESPN status endpoint -- see
    # ingest_ufc_fight_stats.py) now backfillable same as significant_strikes.
    # finishes/win_by_ko/win_by_submission are win-by-method yes/no props, same
    # category as MLB's home_run_any/hit_any etc — none of those are chartable either,
    # this isn't a new gap. All fall back to "chart not available" via lookup returning None.
    "ufc": {"significant_strikes": "sigStrikesLanded", "fight_time": "fight_time"},
    # Tennis has no game-log ingest — docs/LEAGUE-SOURCES-FIELDS.md "Tennis — Bovada prop markets":
    # charting requires tennis game logs that don't exist, so every market maps to None (the chart
    # lookup returns "market not chartable") until that lands. Never fabricate a stat key.
    # total_sets is a match-level Bovada market (O/U 2.5, no player attribution) deferred from
    # _parse_tennis_props; listed here so the intent is explicit.
    "atp": {"match_winner": None, "total_games": None, "set_betting": None,
            "win_a_set": None, "total_sets": None},
    "wta": {"match_winner": None, "total_games": None, "set_betting": None,
            "win_a_set": None, "total_sets": None},
}


def _base_market(m: str) -> str:
    return (m or "").split("___")[0].strip().lower()


# Sources that are ANONYMOUS chatter, not publishers: they feed the signal but
# are never served on the board and never become a card's receipt.
#
# X is NOT in this list (2026-08-10). Lumping it in with Bluesky meant 401
# collected posts — 126 of them real trades, injuries and staff moves from
# Schefter, Shams, Rapoport and Passan — were displayed nowhere at all. A vetted
# beat reporter is a publisher with a byline and a permalink; a random Bluesky
# account arguing about the cap is signal. Micah, 2026-08-10: "these posts we're
# getting might make more sense for the more news section."


# Export the underscore-prefixed helpers: `from _core import *` has to keep
# reaching them, and the default `import *` rule hides a leading underscore.
# _core.py does exactly this for the same reason.
__all__ = [n for n in dir() if not n.startswith("__")]
