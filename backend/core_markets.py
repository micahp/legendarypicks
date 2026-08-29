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
    # CORRECTED 2026-08-26: every key here named a field that does not exist.
    # The map said `receiving_yards -> receiving_yards`; NFL logs are written by
    # `nflverse_weekly` and store `rec_yds`. All eight markets resolved to 0 rows,
    # so the ENTIRE NFL board charted nothing -- 0 of 488 player/market combos --
    # while 24,996 log rows sat there and 192 of 213 players with props had them.
    # Same defect as the Liga MX one fixed today: a map naming a key the store
    # does not use. Measured before mapping, not assumed: pass_yds 1,396,
    # rush_yds 4,713, rec_yds 8,987, rec 8,987, pass_td 1,396, rush_td 4,713,
    # rec_td 8,987, intc 1,396 -- against 0 for every name replaced.
    "nfl": {"passing_yards": "pass_yds", "rushing_yards": "rush_yds",
            "receiving_yards": "rec_yds", "receptions": "rec",
            "passing_tds": "pass_td", "rushing_tds": "rush_td",
            "receiving_tds": "rec_td", "interceptions": "intc",
            # Compounds the board prices and the logs can already answer. The
            # chart sums the listed fields, so these need no stored column.
            "total_touchdowns": ["rush_td", "rec_td"],
            "passing_rushing_yards": ["pass_yds", "rush_yds"],
            "rushing_receiving_yards": ["rush_yds", "rec_yds"],
            # Deliberately NOT mapped: field_goals_made. nflverse_weekly holds no
            # kicking fields at all, so mapping it would draw an empty series as
            # though the market were answerable.
            "carries": "carries", "targets": "targets",
            # The market NAMES the RotoWire relay ships, mapped to the keys
            # nflverse_weekly stores. Added 2026-08-26 alongside the ingest that
            # started taking them; a prop that arrives with no map entry charts
            # "No history", which is how the eight keys above went unnoticed.
            # `rushing_touchdowns` is the relay's spelling of `rushing_tds`.
            "rushing_touchdowns": "rush_td",
            "rush_attempts": "carries",
            "pass_attempts": "att",
            "pass_completions": "cmp"},
    # NCAAF's durable ESPN logs use the same compact offensive vocabulary as
    # nflverse. Only map fields those rows actually store: completions, carries,
    # and kicking are intentionally absent until the history ingest publishes
    # them, while final-game settlement can still use ESPN's full boxscore.
    "ncaaf": {
            "passing_yards": "pass_yds",
            "passing_touchdowns": "pass_td",
            "interceptions_thrown": "intc",
            "pass_attempts": "att",
            "rushing_yards": "rush_yds",
            "rushing_touchdowns": "rush_td",
            "receiving_yards": "rec_yds",
            "receptions": "rec",
            "total_touchdowns": ["rush_td", "rec_td"],
            "passing_rushing_yards": ["pass_yds", "rush_yds"],
            "rushing_receiving_yards": ["rush_yds", "rec_yds"],
            "rushing_receiving_touchdowns": ["rush_td", "rec_td"],
            },
    "wc": {"goals": "goals", "assists": "assists", "shots": "shots",
           "shots_on_target": "sot", "shots_on_goal": "sot"},
    # MLS game logs store the same soccer stat shape as WC (goals/assists/shots/sot)
    "mls": {"goals": "goals", "assists": "assists", "shots": "shots",
            "shots_on_target": "sot", "shots_on_goal": "sot",
            # 1,169 MLS first-goal props sat on the board with no entry here at
            # all, which reads identically to "not chartable". `first_goal` is
            # written per appearance on 4,516 MLS rows.
            "first_goal_scorer": "first_goal",
            # Both already stored for MLS and both already mapped for lcup and
            # ligamx; this map had simply never been extended past the five
            # markets it launched with. goal_or_assist is COMPOUND -- the chart
            # sums the fields -- so it needs no stored column.
            "goal_or_assist": ["goals", "assists"],
            "fouls_committed": "fouls_committed",
            # Goalkeeper markets. `saves` is on 4,516 MLS rows and 86 board
            # rows were rendering "No history" against it; the market has been
            # mapped for ligamx and lcup all along.
            "saves": "saves",
            "goals_allowed": "goals_conceded",
            # Bovada's card market, compound the same way ligamx maps it.
            "card_shown": ["yellow_cards", "red_cards"],
            # Kambi sends the raw key as the market name. `shots_on_target`
            # below already resolves to the same field; without this entry the
            # 21 kambi rows answer "not chartable" while identical rows from
            # another book chart.
            "sot": "sot",
            # CLOSED 2026-08-26. These five were held out because MLS carried 0
            # rows for them: ESPN's shallow ingest does not publish them and
            # FotMob had only ever been run for ligamx and lcup. `mls` was
            # configured in ingest_fotmob_soccer_logs.LEAGUES the whole time --
            # it was a run that had never happened, not a capability we lacked.
            #
            # Run: 9,679 rows from 314 fixtures, 8,955 resolved to the spine.
            # In `player_game_logs_all` now: tackles 8,955, passes 8,955,
            # clearances 8,955, chances_created 8,409, crosses 3,589.
            #
            # This also closes the settlement residue: 186 of the 322 MLS props
            # on these markets now have their OWN appearance covered, matched on
            # player AND match date rather than on the player existing somewhere.
            "tackles": "tackles",
            "clearances": "clearances",
            "chances_created": "chances_created",
            # PrizePicks "Shots Assisted" and Opta "chances created" are the same
            # stat, as already mapped for ligamx and lcup.
            "shots_assisted": "chances_created",
            "crosses": "crosses",
            # This is exact attempted passes from the provider-separated
            # RotoWire rows. FotMob's accurate/completed `passes` field is never
            # substituted for it.
            "passes_attempted": "passes_attempted",
            },
            # An earlier note here called these "FotMob-only" fields, which is
            # false about PUBLISHERS: eight days of the RotoWire relay archive
            # price Tackles 18, Clearances 50, Chances Created 57, Crosses 17 and
            # Passes Attempted 283. The separate RotoWire stats source now
            # supplies the attempted-pass game logs without changing FotMob's
            # accurate-pass semantics.
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
    # for them.
    #
    # CORRECTED 2026-08-26: first_goal_scorer was None on the reasoning that it
    # is an ORDER market that no per-game stat answers. The ingest writes exactly
    # that stat -- `first_goal`, 1 when the player scored the opener and 0 when
    # he played and did not, derived from the published keyEvents -- so the
    # question was already answerable from the logs we hold. The claim described
    # the market rather than the stored row. It cost 1,249 board rows: 80 Liga MX
    # and 1,169 MLS first-goal props all rendered "No history", which is what a
    # market absent from this map looks like on the props tab.
    #
    # An absence still charts as no data rather than as a 0: a player who did not
    # appear has no row, and _PLAYED already drops the appearances=0 rows, so a
    # DNP never reads as "did not score first".
    # `/api/props` returns the PLAYER's league, so a Leagues Cup prop on a Liga
    # MX athlete asks the chart for `ligamx`, not `lcup`. There was no ligamx
    # entry at all, so every one of those rows answered "market not chartable"
    # and rendered "No history" -- while the MLS players on the same card
    # charted fine, because `mls` is in this map. Same markets, same stat keys:
    # one competition's props, two league labels reaching this table.
    "ligamx": {"goals": "goals", "assists": "assists", "shots": "shots",
               "shots_on_target": "sot", "shots_on_goal": "sot",
               "goal_or_assist": ["goals", "assists"],
               "fouls_committed": "fouls_committed",
               "saves": "saves", "goals_allowed": "goals_conceded",
               "card_shown": ["yellow_cards", "red_cards"],
               "tackles": "tackles", "clearances": "clearances",
               "crosses": "crosses", "passes_attempted": "passes_attempted",
               "passes": "passes", "shots_assisted": "shots_assisted",
               # dribbles is answerable after all: FotMob publishes
             # `dribbles_succeeded` per appearance and ingest_fotmob_soccer_logs
             # merges it in. ESPN has groundDuels and duelWinPct, which are not
             # take-ons -- so this waited for a provider that measures the thing
             # rather than a near-miss field.
             "dribbles": "dribbles",
             # PrizePicks "Shots Assisted" and Opta "chances created" are the
             # same stat: a pass that leads to a shot. ESPN's shotAssists is
             # populated on 0 rows; FotMob's chances_created on 1,352.
             "shots_assisted": "chances_created",
             "chances_created": "chances_created",
             "interceptions": "interceptions",
             "first_goal_scorer": "first_goal"},
    "lcup": {"goals": "goals", "assists": "assists", "shots": "shots",
             "shots_on_target": "sot", "shots_on_goal": "sot",
             "goal_or_assist": ["goals", "assists"],
             "fouls_committed": "fouls_committed",
             "saves": "saves", "goals_allowed": "goals_conceded",
             "card_shown": ["yellow_cards", "red_cards"],
             "tackles": "tackles", "clearances": "clearances",
             "crosses": "crosses", "passes_attempted": "passes_attempted",
             "passes": "passes", "shots_assisted": "shots_assisted",
             # dribbles is answerable after all: FotMob publishes
             # `dribbles_succeeded` per appearance and ingest_fotmob_soccer_logs
             # merges it in. ESPN has groundDuels and duelWinPct, which are not
             # take-ons -- so this waited for a provider that measures the thing
             # rather than a near-miss field.
             "dribbles": "dribbles",
             # PrizePicks "Shots Assisted" and Opta "chances created" are the
             # same stat: a pass that leads to a shot. ESPN's shotAssists is
             # populated on 0 rows; FotMob's chances_created on 1,352.
             "shots_assisted": "chances_created",
             "chances_created": "chances_created",
             "interceptions": "interceptions",
             "first_goal_scorer": "first_goal"},
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
