"""Build the NFL historical splits layer from the stored dev database.

The input is read-only (picks.dev.db). The output is a new SQLite file, and the build refuses to overwrite an existing
one, so a built layer never changes under a query or a published result. Four tables:

  team_game      one row per team per completed game: calendar, kickoff windows, venue, weather, officials and
                 outcomes computed from nfl_pbp
  game_official  one row per game and official position (nfl_game_officials)
  player_game    one row per player per game from player_game_logs, with snaps and the counting stats
  team_role      one row per team-game and role (QB1, RB1, WR1): the expected starter, how the role was identified,
                 and whether that player played, with the source of any absence reason

Nothing is downloaded. The build only reads tables that already exist. Penalty tables use LA and WAS, which are mapped to
LAR and WSH, the codes every other table uses.

Usage: python3 layer.py [--source URI] [--out PATH]
"""
import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

import pytz

DEFAULT_SOURCE = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
DEFAULT_OUT = '/root/lp-snapshots/nfl-splits/layer-2026-10-27/splits_layer.sqlite'
SCHEMA_VERSION = 'lp-nfl-historical-splits-layer-1'
RULE_VERSION = 'splits-rules-v1'
PENALTY_TEAM = {'LA': 'LAR', 'WAS': 'WSH'}
ET = pytz.timezone('America/New_York')
PRIOR_GAMES = 3
ROLES = ('QB', 'RB', 'WR')
USAGE_METRIC = {'QB': 'dropbacks', 'RB': 'carries', 'WR': 'targets'}
# Venue state for every stadium state in nfl_game_context (2015 onward). A state missing here stops the build.
STATE_TZ = {
    'CA': 'America/Los_Angeles', 'WA': 'America/Los_Angeles', 'NV': 'America/Los_Angeles',
    'AZ': 'America/Phoenix', 'CO': 'America/Denver',
    'TX': 'America/Chicago', 'MO': 'America/Chicago', 'LA': 'America/Chicago', 'WI': 'America/Chicago',
    'MN': 'America/Chicago', 'IL': 'America/Chicago', 'TN': 'America/Chicago',
    'FL': 'America/New_York', 'PA': 'America/New_York', 'MD': 'America/New_York', 'OH': 'America/New_York',
    'NJ': 'America/New_York', 'MA': 'America/New_York', 'NY': 'America/New_York', 'MI': 'America/New_York',
    'NC': 'America/New_York', 'GA': 'America/New_York', 'IN': 'America/New_York',
}
# Stadium names outside the United States, for games before 2015 (no venue state there).
INTERNATIONAL_MARKERS = ('Wembley', 'Tottenham', 'Azteca', 'Banorte', 'Allianz', 'Deutsche Bank', 'Corinthians',
                         'Melbourne', 'Bayern', 'Frankfurt', 'Olympiastadion', 'Croke Park', 'Dublin', 'Mexico')

SCHEMA = """
create table meta (key text primary key, value text);
create table team_game (
    game_id text not null, season integer not null, week integer not null, game_type text not null,
    team text not null, opponent text not null, home_away text not null, division integer,
    gameday text not null, weekday text not null, gametime_et text not null, kickoff_utc text not null,
    window_et text not null, window_venue text, window_body text,
    venue_state text, venue_tz text, venue_source text, team_home_tz text, international integer,
    stadium text, roof text, surface text, temp real, wind real, referee text,
    attendance integer, broadcast text,
    points_for integer not null, points_against integer not null, result text not null,
    plays integer, yards integer, pass_att integer, completions integer, pass_yds integer,
    rush_att integer, rush_yds integer, epa_per_play real, success_rate real,
    sacks_taken integer, interceptions integer, fumbles_lost integer, turnovers integer,
    penalties integer, penalty_yards integer,
    primary key (game_id, team));
create index team_game_team_season on team_game (team, season);
create index team_game_weekday on team_game (weekday);
create table game_official (
    game_id text not null, position text not null, official_name text, position_published text,
    primary key (game_id, position));
create table player_game (
    game_id text not null, season integer not null, week integer not null, game_type text not null,
    team text not null, opponent text not null, home_away text not null,
    player_id integer, gsis_id text, player_name text,
    snaps integer, snap_source text,
    att integer, cmp integer, pass_yds integer, pass_td integer, intc integer, dropbacks integer,
    sacks_taken integer, carries integer, rush_yds integer, rush_td integer,
    targets integer, rec integer, rec_yds integer, rec_td integer, fum_lost integer, fpts_ppr real);
create index player_game_gsis on player_game (gsis_id, season, week);
create index player_game_team_game on player_game (game_id, team);
create table team_role (
    game_id text not null, season integer not null, week integer not null, team text not null,
    role text not null, gsis_id text, player_name text,
    identified_by text not null, tie integer not null, candidates integer not null,
    status text not null, status_reason text, snaps integer,
    primary key (game_id, team, role));
create index team_role_gsis on team_role (gsis_id, season, week);
"""


def window_of(minutes):
    """Kickoff window from minutes after local midnight: early, late_afternoon or primetime."""
    if minutes < 14 * 60 + 30:
        return 'early'
    if minutes < 20 * 60:
        return 'late_afternoon'
    return 'primetime'


def kickoff_utc(gameday, gametime):
    naive = datetime.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M')
    return ET.localize(naive).astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def local_clock(utc_text, tz):
    """(minutes after local midnight, HH:MM) for a UTC kickoff in zone tz."""
    local = datetime.strptime(utc_text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=pytz.utc).astimezone(tz)
    return local.hour * 60 + local.minute, local.strftime('%H:%M')


def minutes_of(hhmm):
    hours, minutes = hhmm.split(':')
    return int(hours) * 60 + int(minutes)


def pick_by_usage(candidates, usage):
    """The candidate with the most prior-game usage, or None when nobody has any or the top two tie."""
    ranked = sorted(((usage.get(gsis, 0), gsis) for gsis in candidates), reverse=True)
    if not ranked or ranked[0][0] <= 0:
        return None
    if len(ranked) > 1 and ranked[1][0] == ranked[0][0]:
        return None
    return ranked[0][1]


def load_games(src):
    keys = ('game_id', 'season', 'week', 'game_type', 'gameday', 'weekday', 'gametime', 'home', 'away', 'division',
            'roof', 'surface', 'temp', 'wind', 'referee', 'stadium', 'home_score', 'away_score')
    games = [dict(zip(keys, r)) for r in src.execute(
        "select game_id, season, week, game_type, gameday, weekday, gametime, home_team, away_team, div_game, "
        "roof, surface, temp, wind, referee, stadium, home_score, away_score from nfl_schedule "
        "where game_type != 'PRE' and home_score is not null and away_score is not null "
        "order by season, week, gameday, gametime, game_id")]
    for g in games:
        if g['gametime'] is None or g['weekday'] is None:
            raise ValueError(f"{g['game_id']}: completed game without kickoff or weekday")
    return games


def load_context(src):
    context = {}
    for gid, state, attendance, broadcast in src.execute(
            "select game_id, venue_state, attendance, broadcast_networks from nfl_game_context"):
        context[gid] = {'venue_state': state, 'attendance': attendance, 'broadcast': broadcast}
    return context


def load_play_aggregates(src):
    sql = ("select game_id, posteam, count(*), sum(yards_gained), sum(pass_attempt), sum(complete_pass), "
           "sum(passing_yards), sum(rush_attempt), sum(rushing_yards), avg(epa), avg(success), sum(sack), "
           "sum(interception), sum(fumble_lost) from nfl_pbp where play_type in ('pass', 'run') and posteam is not null "
           "group by game_id, posteam")
    out = {}
    for row in src.execute(sql):
        gid, team = row[0], row[1]
        out[(gid, team)] = dict(zip(('plays', 'yards', 'pass_att', 'completions', 'pass_yds', 'rush_att', 'rush_yds',
                                     'epa_per_play', 'success_rate', 'sacks_taken', 'interceptions', 'fumbles_lost'),
                                    row[2:]))
    return out


def load_penalties(src):
    """Flagged penalties by penalty team, with yards from nfl_pbp_penalty (2015 onward; None before)."""
    count = Counter()
    for gid, team, n in src.execute(
            "select game_id, penalty_team, count(*) from nfl_pbp where penalty = 1 and penalty_team is not null "
            "group by game_id, penalty_team"):
        count[(gid, PENALTY_TEAM.get(team, team))] += n
    yards = {}
    for gid, team, n_yards in src.execute(
            "select game_id, penalty_team, sum(penalty_yards) from nfl_pbp_penalty where penalty = 1 "
            "and penalty_team is not null group by game_id, penalty_team"):
        yards[(gid, PENALTY_TEAM.get(team, team))] = n_yards or 0
    return count, yards


def load_officials(src):
    out = defaultdict(dict)
    for gid, position, name, published in src.execute(
            "select game_id, position, official_name, position_published from nfl_game_officials"):
        out[gid][position] = (name, published)
    return out


def team_home_zones(games, context):
    """(season, team) -> tz name, from the venue state of the team's most frequent home venue that season.

    Built only from nfl_game_context rows (2015 onward). Later code carries a zone forward to a later season that has
    no row of its own, but never backward, because several franchises moved.
    """
    seen = defaultdict(Counter)
    for g in games:
        state = context.get(g['game_id'], {}).get('venue_state')
        if state:
            seen[(g['season'], g['home'])][state] += 1
    zones = {}
    for key, counts in seen.items():
        state = counts.most_common(1)[0][0]
        if state not in STATE_TZ:
            raise ValueError(f'venue state {state} has no time zone in STATE_TZ')
        zones[key] = STATE_TZ[state]
    return zones


def zone_for(zones, season, team):
    if (season, team) in zones:
        return zones[(season, team)]
    earlier = [s for (s, t) in zones if t == team and s < season]
    return zones[(max(earlier), team)] if earlier else None


def build_team_games(games, context, plays, penalty_count, penalty_yards, zones):
    rows, problems = [], Counter()
    for g in games:
        gid, season = g['game_id'], g['season']
        kick = kickoff_utc(g['gameday'], g['gametime'])
        window_et = window_of(minutes_of(g['gametime']))
        ctx_row = context.get(gid)
        ctx = ctx_row or {}
        if ctx_row is not None:
            # A game with a context row has a venue state; a row with no state was played outside the United States.
            state = ctx['venue_state']
            if state and state not in STATE_TZ:
                raise ValueError(f'{gid}: venue state {state} has no time zone in STATE_TZ')
            venue_tz = STATE_TZ.get(state) if state else None
            international = int(state is None)
            venue_source = 'nfl_game_context'
        else:
            # No context row (2026 so far, and 2010 to 2014): the stadium name is the only venue evidence.
            state = None
            marker = any(m in (g['stadium'] or '') for m in INTERNATIONAL_MARKERS)
            international = int(marker)
            venue_tz = None if marker else zone_for(zones, season, g['home'])
            venue_source = 'stadium_marker' if marker else ('home_team_zone' if venue_tz else 'unknown')
            problems[f'no_context_{venue_source}'] += 1
        window_venue = window_of(local_clock(kick, pytz.timezone(venue_tz))[0]) if venue_tz else None
        for side in ('home', 'away'):
            team = g[side]
            opp = g['away'] if side == 'home' else g['home']
            pf = g['home_score'] if side == 'home' else g['away_score']
            pa = g['away_score'] if side == 'home' else g['home_score']
            result = 'W' if pf > pa else ('L' if pf < pa else 'T')
            body_tz = zone_for(zones, season, team)
            body_window = window_of(local_clock(kick, pytz.timezone(body_tz))[0]) if body_tz else None
            agg = plays.get((gid, team))
            # nfl_pbp has no playoff games, so their play, turnover and penalty fields stay null rather than 0.
            has_pbp = agg is not None
            if not has_pbp:
                problems['no_play_aggregate'] += 1
                agg = {k: None for k in ('plays', 'yards', 'pass_att', 'completions', 'pass_yds', 'rush_att',
                                         'rush_yds', 'epa_per_play', 'success_rate', 'sacks_taken',
                                         'interceptions', 'fumbles_lost')}
            # 2026 pbp has interceptions but no fumble_lost values, so turnovers stay null for it.
            turnovers = None
            if has_pbp and agg['interceptions'] is not None and agg['fumbles_lost'] is not None:
                turnovers = agg['interceptions'] + agg['fumbles_lost']
            elif has_pbp:
                problems['turnovers_unknown'] += 1
            penalties = penalty_count.get((gid, team), 0) if has_pbp else None
            py = penalty_yards.get((gid, team), 0) if has_pbp and season >= 2015 else None
            rows.append((
                gid, season, g['week'], g['game_type'], team, opp, side, g['division'], g['gameday'], g['weekday'],
                g['gametime'], kick, window_et, window_venue, body_window, state, venue_tz, venue_source, body_tz,
                international, g['stadium'], g['roof'], g['surface'], g['temp'], g['wind'], g['referee'],
                ctx.get('attendance'), ctx.get('broadcast'),
                pf, pa, result,
                agg['plays'], agg['yards'], agg['pass_att'], agg['completions'], agg['pass_yds'],
                agg['rush_att'], agg['rush_yds'], agg['epa_per_play'], agg['success_rate'],
                agg['sacks_taken'], agg['interceptions'], agg['fumbles_lost'], turnovers, penalties, py))
    return rows, problems


def build_players(src, team_game_keys, games_by_id):
    """player_game rows for completed games, with snaps from the source that covers the season."""
    lp_to_gsis = {}
    gsis_by_lp = {}
    for lp_id, gsis, name in src.execute("select id, nfl_gsis_id, name from players"):
        lp_to_gsis[lp_id] = gsis
        gsis_by_lp[lp_id] = name
    pfr_by_gsis = {gsis: pfr for gsis, pfr in src.execute(
        "select gsis_id, pfr_id from nfl_hist_player_ids where gsis_id is not null and pfr_id is not null")}
    hist_snaps = {}
    for gid, pfr, snaps in src.execute(
            "select game_id, pfr_player_id, offense_snaps from nfl_hist_snap_counts"):
        hist_snaps[(gid, pfr)] = snaps
    new_snaps = {}
    for lp_id, season, week, team, snaps in src.execute(
            "select player_id, season, week, team, off_snaps from nfl_snap_counts"):
        new_snaps[(lp_id, season, week, team)] = snaps
    logs = src.execute(
        "select game_id, season, team, opponent, home_away, player_id, stats from player_game_logs "
        "where league = 'nfl' and source = 'nflverse_weekly' and game_type in ('REG', 'POST') and team is not null").fetchall()
    rows, problems = [], Counter()
    for gid, season, team, _logged_opp, _logged_side, lp_id, stats_text in logs:
        if (gid, team) not in team_game_keys:
            continue
        g = games_by_id[gid]
        # The schedule decides home/away and opponent; the logged values are empty for some rows.
        home_away = 'home' if team == g['home'] else 'away'
        opp = g['away'] if home_away == 'home' else g['home']
        s = json.loads(stats_text)
        gsis = lp_to_gsis.get(lp_id)
        if gsis is None:
            problems['player_without_gsis'] += 1
        snaps, source = None, None
        if season >= 2024:
            if (lp_id, season, g['week'], team) in new_snaps:
                snaps, source = new_snaps[(lp_id, season, g['week'], team)], 'nfl_snap_counts'
            elif 'off_snaps' in s:
                snaps, source = s['off_snaps'], 'player_game_logs'
        else:
            pfr = pfr_by_gsis.get(gsis) if gsis else None
            if pfr is not None and (gid, pfr) in hist_snaps:
                snaps, source = hist_snaps[(gid, pfr)], 'nfl_hist_snap_counts'
        if source is None:
            problems['no_snap_source'] += 1
        rows.append((
            gid, season, g['week'], g['game_type'], team, opp, home_away, lp_id, gsis, gsis_by_lp.get(lp_id),
            snaps, source,
            s.get('att'), s.get('cmp'), s.get('pass_yds'), s.get('pass_td'), s.get('intc'), s.get('dropbacks'),
            s.get('sacks_taken'), s.get('carries'), s.get('rush_yds'), s.get('rush_td'),
            s.get('targets'), s.get('rec'), s.get('rec_yds'), s.get('rec_td'), s.get('fum_lost'), s.get('fpts_ppr')))
    return rows, problems


def build_roles(src, player_rows, team_game_rows):
    """team_role rows for regular-season team games.

    Candidates come from the historical depth chart (2010 to 2024) at depth 1 in the offense. Two or more depth-1
    players are a tie, broken by prior usage. With no depth row (2025 and 2026), the role comes from prior usage alone.
    Prior usage is the team's last PRIOR_GAMES regular-season games before the game being classified, so no role
    reads the game it describes.
    """
    depth = defaultdict(lambda: defaultdict(list))
    for season, week, club, position, gsis, name in src.execute(
            "select season, week, club_code, position, gsis_id, full_name from nfl_hist_depth_charts "
            "where game_type = 'REG' and formation = 'Offense' and depth_team = '1' "
            "and position in ('QB', 'RB', 'WR') and gsis_id is not null"):
        depth[(season, week, club)][position].append((gsis, name))
    position_of = {}
    for gsis, pos in src.execute("select gsis_id, position from nfl_hist_player_ids where gsis_id is not null"):
        position_of[gsis] = pos
    for gsis, pos in src.execute("select nfl_gsis_id, position from players where nfl_gsis_id is not null"):
        position_of.setdefault(gsis, pos)
    reasons = {}
    for gid, team, gsis, reason, report in src.execute(
            "select a.game_id, a.team, pl.nfl_gsis_id, a.reason, a.report_status "
            "from player_game_availability a join players pl on pl.id = a.player_id "
            "where a.league = 'nfl' and pl.nfl_gsis_id is not null"):
        reasons[(gid, team, gsis)] = (reason, report)
    hist_reports = {}
    for season, week, team, gsis, report, practice in src.execute(
            "select season, week, team, gsis_id, report_status, practice_status from nfl_hist_injuries "
            "where game_type = 'REG' and gsis_id is not null"):
        hist_reports[(season, week, team, gsis)] = (report, practice)
    players = defaultdict(dict)
    for row in player_rows:
        if row[8] is not None:
            players[(row[0], row[4])][row[8]] = row
    by_team = defaultdict(list)
    for gid, season, week, team in team_game_rows:
        by_team[(season, team)].append((week, gid))
    for key in by_team:
        by_team[key].sort()

    def prior_usage(season, team, week, metric):
        usage = Counter()
        games = [gid for w, gid in by_team[(season, team)] if w < week][-PRIOR_GAMES:]
        for gid in games:
            for gsis, row in players.get((gid, team), {}).items():
                value = row_stat(row, metric)
                if gsis and value:
                    usage[gsis] += value
        return usage

    rows, problems = [], Counter()
    for gid, season, week, team in team_game_rows:
        for role in ROLES:
            cands = depth.get((season, week, team), {}).get(role, [])
            metric = USAGE_METRIC[role]
            if len(cands) == 1:
                gsis, name = cands[0]
                identified, tie, candidates = 'depth_chart_week', 0, 1
                if gsis is None:
                    problems['depth_without_gsis'] += 1
            elif len(cands) > 1:
                usage = prior_usage(season, team, week, metric)
                gsis = pick_by_usage([c[0] for c in cands], usage)
                name = dict(cands).get(gsis)
                identified, tie, candidates = 'depth_chart_week+prior_usage', 1, len(cands)
                if gsis is None:
                    identified = 'tie_unresolved'
            else:
                usage = prior_usage(season, team, week, metric)
                pool = [g for g in usage if position_of.get(g) == role]
                gsis = pick_by_usage(pool, {g: usage[g] for g in pool})
                name = None
                identified, tie, candidates = 'usage_prior_3g', 0, len(pool)
                if gsis is None:
                    identified = 'no_prior_usage'
                    problems[f'{role}_no_prior_usage'] += 1
            if gsis is None:
                rows.append((gid, season, week, team, role, None, None, identified, tie, candidates,
                             'unidentified', None, None))
                continue
            row = players.get((gid, team), {}).get(gsis)
            status, reason, snaps = classify(gid, team, season, week, gsis, row, reasons, hist_reports)
            if name is None:
                name = row[9] if row else None
            rows.append((gid, season, week, team, role, gsis, name, identified, tie, candidates,
                         status, reason, snaps))
            problems[status] += 1
    return rows, problems


def row_stat(row, metric):
    """A usage count from a player_game row. Columns follow player_game's insert order."""
    index = {'dropbacks': 17, 'carries': 19, 'targets': 22}[metric]
    value = row[index]
    return value or 0


def classify(gid, team, season, week, gsis, row, reasons, hist_reports):
    """(status, reason, snaps) for a role player in a game.

    played              logged, with snaps above zero, or with snaps unknown
    officially_inactive 2024 onward: the availability snapshot labels him inactive without an injury report
    injured             an injury report or the availability reason says he was out or questionable
    absent_no_reason    not logged, or logged with zero snaps, and no reason on record
    """
    if row is not None:
        snaps = row[10]
        if snaps is None or snaps > 0:
            return 'played', row[11] or 'player_game', snaps
        return 'absent_no_reason', 'logged_zero_snaps', snaps
    reason, report = reasons.get((gid, team, gsis), (None, None))
    if reason == 'played':
        return 'absent_no_reason', 'availability_says_played_but_no_log', None
    if reason == 'inactive_no_report':
        return 'officially_inactive', f'availability:{reason}', None
    if reason == 'injury_out' or (report in ('Out', 'Doubtful', 'Questionable')):
        return 'injured', f'availability:{reason}|report:{report}', None
    hist = hist_reports.get((season, week, team, gsis))
    if hist and hist[0] in ('Out', 'Doubtful', 'Questionable'):
        return 'injured', f'nfl_hist_injuries:{hist[0]}', None
    return 'absent_no_reason', 'no_reason_on_record', None


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(source, out, git_commit):
    if os.path.exists(out):
        raise SystemExit(f'refusing to overwrite {out}')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    src = sqlite3.connect(source, uri=True)
    games = load_games(src)
    games_by_id = {g['game_id']: g for g in games}
    context = load_context(src)
    plays = load_play_aggregates(src)
    penalty_count, penalty_yards = load_penalties(src)
    officials = load_officials(src)
    zones = team_home_zones(games, context)

    team_rows, team_problems = build_team_games(games, context, plays, penalty_count, penalty_yards, zones)
    team_keys = {(r[0], r[4]) for r in team_rows}
    player_rows, player_problems = build_players(src, team_keys, games_by_id)
    role_rows, role_problems = build_roles(
        src, player_rows, [(r[0], r[1], r[2], r[4]) for r in team_rows if r[3] == 'REG'])

    dst = sqlite3.connect(out)
    dst.executescript(SCHEMA)
    def insert(table, rows):
        marks = ','.join('?' * len(rows[0]))
        dst.executemany(f'insert into {table} values ({marks})', rows)

    insert('team_game', team_rows)
    official_rows = []
    for gid in games_by_id:
        for position, (name, published) in sorted(officials.get(gid, {}).items()):
            official_rows.append((gid, position, name, published))
    insert('game_official', official_rows)
    insert('player_game', player_rows)
    insert('team_role', role_rows)
    meta = {
        'schema': SCHEMA_VERSION, 'rule_version': RULE_VERSION, 'built_from': source,
        'source_sha256': sha256_file(source.replace('file:', '').split('?')[0]),
        'code_commit': git_commit, 'team_game_rows': len(team_rows), 'game_official_rows': len(official_rows),
        'player_game_rows': len(player_rows), 'team_role_rows': len(role_rows),
        'problems': {'team_game': dict(team_problems), 'player_game': dict(player_problems),
                     'team_role': dict(role_problems)},
    }
    for key, value in meta.items():
        dst.execute('insert into meta values (?, ?)', (key, json.dumps(value, sort_keys=True)))
    dst.commit()
    dst.close()
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default=DEFAULT_SOURCE)
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--git-commit', default='unknown')
    args = ap.parse_args()
    meta = build(args.source, args.out, args.git_commit)
    print(json.dumps(meta, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
