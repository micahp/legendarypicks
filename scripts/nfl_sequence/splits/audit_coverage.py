"""Coverage and join audit for the NFL historical splits layer (read-only).

Reports, per season, what the stored tables actually hold, and whether their keys join. It never infers coverage from
table presence: every number here is a count taken from the database at run time.

Usage: python3 audit_coverage.py [--db PATH]
"""
import argparse
import sqlite3

DEFAULT_DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'


def rows(con, sql, params=()):
    return con.execute(sql, params).fetchall()


def show(title, con, sql, params=(), headers=None):
    print(f'\n## {title}')
    if headers:
        print(' | '.join(headers))
    for row in rows(con, sql, params):
        print(' | '.join('' if v is None else str(v) for v in row))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    args = ap.parse_args()
    con = sqlite3.connect(args.db, uri=True)

    show('nfl_schedule by season and game type (observed weather, referee, venue fields)', con, """
        select season, game_type, count(*), min(week), max(week),
               sum(home_score is not null), sum(roof is not null), sum(surface is not null),
               sum(temp is not null), sum(wind is not null), sum(referee is not null and referee <> ''),
               sum(gametime is not null), sum(stadium is not null), sum(weekday is not null)
        from nfl_schedule group by season, game_type order by season, game_type""",
         headers=['season', 'type', 'games', 'min_wk', 'max_wk', 'scored', 'roof', 'surface', 'temp', 'wind',
                  'referee', 'gametime', 'stadium', 'weekday'])

    show('nfl_schedule weekday distribution (regular season)', con, """
        select season, weekday, count(*) from nfl_schedule where game_type = 'REG'
        group by season, weekday order by season, weekday""", headers=['season', 'weekday', 'games'])

    show('nfl_pbp: distinct games and plays by season, and schedule games with play-by-play', con, """
        select p.season, p.games, p.plays, s.reg_games, s.reg_with_pbp
        from (select season, count(distinct game_id) games, count(*) plays from nfl_pbp group by season) p
        left join (select season, count(*) reg_games,
                          sum(n.game_id in (select game_id from nfl_pbp)) reg_with_pbp
                   from nfl_schedule n where game_type = 'REG' group by season) s on s.season = p.season
        order by p.season""", headers=['season', 'pbp_games', 'plays', 'reg_sched', 'reg_with_pbp'])

    show('nfl_game_officials: schedule games with a Referee row, by season', con, """
        select n.season, count(distinct n.game_id) games,
               sum(n.game_id in (select game_id from nfl_game_officials where position = 'Referee'))
        from nfl_schedule n where n.game_type = 'REG' and n.season >= 2015 group by n.season order by n.season""",
         headers=['season', 'reg_games', 'with_referee'])

    show('nfl_game_officials: positions per game (distinct) by season', con, """
        select n.season, count(*) games,
               sum(c.k = 7), sum(c.k < 7), sum(c.k is null)
        from nfl_schedule n left join
             (select game_id, count(distinct position) k from nfl_game_officials group by game_id) c
             on c.game_id = n.game_id
        where n.game_type = 'REG' and n.season >= 2015 group by n.season order by n.season""",
         headers=['season', 'reg_games', 'seven_positions', 'fewer', 'none'])

    show('nfl_schedule weather nulls by roof, regular season scored games', con, """
        select season, roof, count(*), sum(temp is null), sum(wind is null)
        from nfl_schedule where game_type = 'REG' and home_score is not null and season >= 2015
        group by season, roof order by season, roof""",
         headers=['season', 'roof', 'scored', 'temp_null', 'wind_null'])

    show('player_game_availability per team-game (nfl, 2024+): rows and played flags', con, """
        select season, count(*) team_games, avg(n), min(n), max(n), sum(n_played = 0) with_zero_played
        from (select season, game_id, team, count(*) n, sum(played = 0) n_played
              from player_game_availability where league = 'nfl' and season >= 2024
              group by season, game_id, team) group by season order by season""",
         headers=['season', 'team_games', 'avg_rows', 'min_rows', 'max_rows', 'team_games_with_zero_played'])

    show('nfl_hist_depth_charts depth_team values', con, """
        select depth_team, count(*) from nfl_hist_depth_charts group by depth_team order by count(*) desc limit 8""",
         headers=['depth_team', 'rows'])

    show('nfl_hist_depth_charts position values (top)', con, """
        select position, count(*) from nfl_hist_depth_charts group by position order by count(*) desc limit 14""",
         headers=['position', 'rows'])

    show('nfl_hist_depth_charts club codes not used by nfl_schedule', con, """
        select club_code, count(*) from nfl_hist_depth_charts
        where club_code not in (select home_team from nfl_schedule union select away_team from nfl_schedule)
        group by club_code""", headers=['club_code', 'rows'])

    show('nfl_snap_counts vs nfl_hist_snap_counts overlap (2024-2025 games)', con, """
        select 'nfl_snap_counts' src, count(*) from nfl_snap_counts where season in (2024, 2025)
        union all select 'nfl_hist_snap_counts', count(*) from nfl_hist_snap_counts where season in (2024, 2025)""",
         headers=['table', 'rows_2024_2025'])

    show('nfl_game_officials positions present', con, """
        select position, position_published, count(*) from nfl_game_officials group by position, position_published
        order by count(*) desc""", headers=['position', 'published_label', 'rows'])

    show('nfl_pbp_penalty by season', con, """
        select season, count(distinct game_id), sum(penalty = 1), count(*) from nfl_pbp_penalty
        group by season order by season""", headers=['season', 'games', 'flagged_penalties', 'rows'])

    show('nfl_game_context by season (attendance, broadcast)', con, """
        select season, count(*), sum(attendance is not null), sum(broadcast_networks is not null),
               sum(attendance_suspect = 1)
        from nfl_game_context group by season order by season""",
         headers=['season', 'games', 'attendance', 'broadcast', 'attendance_suspect'])

    show('player_game_logs (nfl) by season', con, """
        select season, count(*), count(distinct player_id), count(distinct game_id), min(game_date), max(game_date)
        from player_game_logs where league = 'nfl' group by season order by season""",
         headers=['season', 'rows', 'players', 'games', 'first_date', 'last_date'])

    show('player_game_logs (nfl) game_type and source', con, """
        select game_type, source, count(*), count(distinct season) from player_game_logs where league = 'nfl'
        group by game_type, source""", headers=['game_type', 'source', 'rows', 'seasons'])

    show('player_game_availability (nfl) by season', con, """
        select season, count(*), count(distinct game_id), sum(played = 1), sum(played = 0), sum(played is null),
               count(distinct report_status)
        from player_game_availability where league = 'nfl' group by season order by season""",
         headers=['season', 'rows', 'games', 'played', 'not_played', 'played_null', 'status_kinds'])

    show('player_game_availability (nfl) reason values', con, """
        select reason, count(*) from player_game_availability where league = 'nfl' group by reason
        order by count(*) desc limit 12""", headers=['reason', 'rows'])

    show('nfl_hist_depth_charts by season', con, """
        select season, count(*), count(distinct week), count(distinct club_code), count(distinct gsis_id)
        from nfl_hist_depth_charts group by season order by season""",
         headers=['season', 'rows', 'weeks', 'clubs', 'players'])

    show('nfl_depth_chart (current-era snapshots) by season', con, """
        select season, count(*), count(distinct team), count(distinct snapshot_at), count(distinct gsis_id)
        from nfl_depth_chart group by season order by season""",
         headers=['season', 'rows', 'teams', 'snapshots', 'players'])

    show('nfl_hist_snap_counts by season', con, """
        select season, count(*), count(distinct game_id), count(distinct pfr_player_id)
        from nfl_hist_snap_counts group by season order by season""",
         headers=['season', 'rows', 'games', 'players'])

    show('nfl_snap_counts by season', con, """
        select season, count(*), count(distinct week), count(distinct player_id)
        from nfl_snap_counts group by season order by season""", headers=['season', 'rows', 'weeks', 'players'])

    show('injury_reports (nfl) by season', con, """
        select season, count(*), count(distinct week), count(distinct team), count(distinct gsis_id),
               sum(report_status is not null), min(date_modified), max(date_modified)
        from injury_reports where league = 'nfl' group by season order by season""",
         headers=['season', 'rows', 'weeks', 'teams', 'players', 'with_status', 'first_mod', 'last_mod'])

    show('nfl_hist_injuries by season and game type', con, """
        select season, game_type, count(*), count(distinct week), count(distinct team), count(distinct gsis_id)
        from nfl_hist_injuries group by season, game_type order by season, game_type""",
         headers=['season', 'type', 'rows', 'weeks', 'teams', 'players'])

    show('nfl_hist_participation by season', con, """
        select season, count(*), count(distinct nflverse_game_id) from nfl_hist_participation
        group by season order by season""", headers=['season', 'plays', 'games'])

    show('nfl_team_game_totals by season', con, """
        select season, count(*), count(distinct game_id), sum(carries is not null), sum(targets is not null)
        from nfl_team_game_totals group by season order by season""",
         headers=['season', 'rows', 'games', 'carries', 'targets'])

    print('\n## Join keys')
    show('sample game_id formats', con, """
        select * from (select 'schedule' t, game_id from nfl_schedule where game_type = 'REG' limit 1)
        union all select * from (select 'pbp', game_id from nfl_pbp limit 1)
        union all select * from (select 'officials', game_id from nfl_game_officials limit 1)
        union all select * from (select 'pgl', game_id from player_game_logs where league = 'nfl' limit 1)
        union all select * from (select 'pga', game_id from player_game_availability where league = 'nfl' limit 1)
        union all select * from (select 'hist_snap', game_id from nfl_hist_snap_counts limit 1)
        union all select * from (select 'participation', nflverse_game_id from nfl_hist_participation limit 1)
        union all select * from (select 'team_totals', game_id from nfl_team_game_totals limit 1)""",
         headers=['table', 'game_id'])

    show('player_game_logs (nfl) game_id matched to nfl_schedule, by season', con, """
        select season, count(*), sum(l.game_id in (select game_id from nfl_schedule))
        from player_game_logs l where league = 'nfl' group by season order by season""",
         headers=['season', 'rows', 'matched_to_schedule'])

    show('player_game_availability (nfl) game_id matched to nfl_schedule, by season', con, """
        select season, count(*), sum(a.game_id in (select game_id from nfl_schedule))
        from player_game_availability a where league = 'nfl' group by season order by season""",
         headers=['season', 'rows', 'matched_to_schedule'])

    show('nfl player id bridges: player_game_logs.player_id to players.nfl_gsis_id', con, """
        select count(*), sum(p.id is not null), sum(p.nfl_gsis_id is not null)
        from (select distinct player_id from player_game_logs where league = 'nfl') l
        left join players p on p.id = l.player_id""",
         headers=['distinct_nfl_players', 'in_players', 'with_gsis'])

    show('nfl_hist_depth_charts gsis_id matched to players.nfl_gsis_id', con, """
        select count(distinct gsis_id), sum(gsis_id in (select nfl_gsis_id from players where nfl_gsis_id is not null))
        from (select distinct gsis_id from nfl_hist_depth_charts) d""",
         headers=['distinct_gsis', 'in_players'])

    show('nfl_hist_snap_counts pfr_player_id matched to nfl_hist_player_ids.pfr_id', con, """
        select count(distinct pfr_player_id), sum(pfr_player_id in (select pfr_id from nfl_hist_player_ids))
        from (select distinct pfr_player_id from nfl_hist_snap_counts) s""",
         headers=['distinct_pfr', 'in_ids'])

    show('nfl_pbp passer/rusher/receiver ids: populated share by season', con, """
        select season, count(*), sum(passer_player_id is not null), sum(rusher_player_id is not null),
               sum(receiver_player_id is not null)
        from nfl_pbp group by season order by season""",
         headers=['season', 'plays', 'passer_id', 'rusher_id', 'receiver_id'])

    show('nfl_pbp id namespace sample (passer_player_id, gsis-style?)', con, """
        select passer_player_id, count(*) from nfl_pbp where passer_player_id is not null
        group by passer_player_id order by count(*) desc limit 3""", headers=['passer_player_id', 'plays'])


if __name__ == '__main__':
    main()
