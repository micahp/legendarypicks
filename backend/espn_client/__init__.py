"""espn_client — dependency-free ESPN data client for all major leagues.

Was a single 1549-line module; is now a package of focused modules. The whole
public surface is re-exported here so `import espn_client as espn;
espn.games(...)` and `from espn_client import LEAGUES, _get` keep working
unchanged, and so monkeypatching `espn_client._get` / `espn_client.summary`
/ ... (as the test suite does) still intercepts every internal call — the
submodules resolve shared names through this package object at call time.

Internal modules:
  config      hosts, LEAGUES, the shared Fetcher, setters, _get/_check
  scoreboard  games, scoreboard_raw, date/num helpers
  nfl         NFL schedule weeks / week games / event starts
  ufc         fighter resolution + fight history
  standings   team_strength & published group standings
  soccer      summary-based reads, WC knockout, MLS/NCAAF standings
"""
from .config import (
    LEAGUES, _SITE, _CORE, _COMMON, _SPORTS_CORE, _HDRS, _FETCHER, _CACHE,
    set_min_interval, set_disk_cache, set_retry_waits, set_on_exhausted,
    set_host_budget, batch_pacing, _get, _check,
)
from .scoreboard import (
    _ATP_MAJORS, _WTA_MAJORS, _is_major, _num, _int, _iso,
    neighbor_dates, _normalize_team_events, scoreboard_raw, games,
    tennis_draws_from_payload, tennis_rankings_from_payload, tennis_rankings,
    tennis_ranking_identities_from_payload, tennis_ranking_identities,
    _ny_date, _slate_day, scoreboard_raw_range, games_by_day,
)
from .nfl import (
    football_schedule_weeks, football_schedule_week_games,
    nfl_schedule_weeks, nfl_schedule_week_games, schedule_event_starts,
)
from .ufc import (
    _athlete_name_key, _athlete_name_parts, ufc_athlete, _ufc_method,
    ufc_fight_history,
)
from .standings import (
    team_strength, _team_strength_rows, team_strength_standings,
    team_strength_map, _standing_int, _standing_rows, group_standings,
)
from .soccer import (
    summary, game_result_soccer, lineups, _WC_ROUND_MAP, _WC_ROUND_ORDER,
    _wc_round_from_event, _wc_competitor, wc_knockout_standings,
    wc_is_knockout, match_events, boxscore, roster, game_result,
    _parse_record, _season_phase, mls_conference_standings,
    ncaaf_conference_standings, lcup_competition_snapshot_from_payload,
    lcup_competition_snapshot,
    soccer_athlete_form,
)

if __name__ == "__main__":
    import sys
    lg = sys.argv[1] if len(sys.argv) > 1 else "mlb"
    print(f"== {lg} top-5 by quality ==")
    for r in team_strength(lg)[:5]:
        print(f"  {r['abbrev']:4} {str(r['wins'])+'-'+str(r['losses']):8} "
              f"win%={r['win_pct']} diff={r['differential']} {r['streak']} L10={r['last10']}")
    print(f"== {lg} games today ==")
    for g in games(lg):
        h, a = g["home"], g["away"]
        print(f"  {a['abbrev']}@{h['abbrev']} {g['state']:4} {a['score']}-{h['score']} ({g['status']})")
