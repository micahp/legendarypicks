"""SLC V1.5: every layer with a current-season source is shrunk toward the current season (research, off by default).

The rule is the one predeclared for the temporal study (docs/research/TEMPORAL-WINDOW-2026-11-02/temporal_predeclaration.md)
and fixed in SLC-V15-WALKFORWARD-PROTOCOL-2026-11-03.md: a team's historical (V1) estimate keeps the weight

    w = N0 / (N0 + g)

where g is the number of the team's current-season games whose results were available at the target's cutoff, N0 = 4. The
current-season estimate is the layer's own estimator run on those games only, so it is smoothed toward the same historical
league shares as V1. A player-keyed table uses the player's own current-season games for g. A league-only table uses the
league's games per team.

For a count table the blend is written back as counts, so every lookup function is unchanged: for a key with historical counts
H (total h) and current-season counts S (total s), the blended counts are (h + s) * (w * H/h + (1 - w) * S/s). A key with no
current-season counts keeps H exactly, and a key with no history takes S. League-level counts, which are the shrinkage targets
of the team and player estimates, stay historical. With no available games every table is returned unchanged, so V1 is
reproduced.

Cutoff safety: a game counts only if its result was available (AVAILABILITY_LAG_HOURS after kickoff) at the target's cutoff
(CUTOFF_MINUTES before its kickoff), and the target game never counts. Every current-season read goes through
holdout.refuse_unless_cutoff with that cutoff.
"""
import hashlib
import json
import sqlite3
from collections import Counter

import current_season_adapt as csa
import holdout
import team_season_adapt as tsa

METHOD = 'slc_v15_every_layer_season_blend'


class Evidence:
    """The current-season games one target game may use, and the weights they imply."""

    def __init__(self, season, cutoff, target_game_id, game_ids, team_games, undated=(), n0=csa.DEFAULT_N0):
        holdout.refuse_unless_cutoff(season, 'current-season evidence', cutoff)
        self.season = int(season)
        self.cutoff = cutoff
        self.target_game_id = target_game_id
        self.game_ids = tuple(sorted(game_ids))
        self.team_games = dict(team_games)
        self.undated = tuple(sorted(undated))
        self.n0 = float(n0)

    @classmethod
    def for_target(cls, db, season, target_game_id, kickoff, n0=csa.DEFAULT_N0):
        cutoff = tsa.cutoff_utc(kickoff)
        game_ids, undated = tsa.available_games(tsa.load_schedule(db, season), season, cutoff, target_game_id)
        return cls(season, cutoff, target_game_id, game_ids, games_by_team(db, season, game_ids, cutoff), undated, n0)

    def weight(self, games):
        """The weight on the historical estimate for an entity with `games` current-season games."""
        return csa.effective_weight_on_history(games, self.n0)

    def team_weight(self, team):
        return self.weight(self.team_games.get(team, 0))

    def league_games(self):
        """Games per team across the league, the league-only tables' g."""
        return sum(self.team_games.values()) / len(self.team_games) if self.team_games else 0.0

    def sql_filter(self, alias=''):
        """(clause, params) selecting the available games of the season; `alias` is a table prefix such as 'p.'."""
        holdout.refuse_unless_cutoff(self.season, 'current-season rows', self.cutoff)
        marks = ', '.join('?' for _ in self.game_ids) or 'NULL'
        return f'{alias}season = ? AND {alias}game_id IN ({marks})', [self.season, *self.game_ids]

    def manifest(self):
        return {'method': METHOD, 'season': self.season, 'cutoff_utc': self.cutoff.isoformat(),
                'target_game_id': self.target_game_id, 'n0': self.n0, 'season_games': list(self.game_ids),
                'undated_games': list(self.undated), 'team_games': dict(sorted(self.team_games.items()))}


def games_by_team(db, season, game_ids, cutoff):
    """{team: number of the given games it played}, from the published schedule."""
    holdout.refuse_unless_cutoff(season, 'current-season schedule', cutoff)
    if not game_ids:
        return {}
    marks = ', '.join('?' for _ in game_ids)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(f"SELECT home_team, away_team FROM nfl_schedule WHERE season = ? AND game_type = 'REG' "
                           f"AND game_id IN ({marks})", (int(season), *game_ids)).fetchall()
    finally:
        con.close()
    if len(rows) != len(set(game_ids)):
        raise ValueError(f'{len(set(game_ids))} available games but {len(rows)} schedule rows: the team game counts would be wrong')
    counts = Counter()
    for home, away in rows:
        counts[home] += 1
        counts[away] += 1
    return dict(counts)


def blend_counts(hist, season, weight_on_history):
    """Counts whose shares are the weighted blend of the two, with the pooled total. See the module docstring."""
    h = sum(hist.values()) if hist else 0
    s = sum(season.values()) if season else 0
    if s <= 0:
        return hist
    if h <= 0:
        return Counter(season)
    total = h + s
    w = float(weight_on_history)
    keys = list(hist) + [k for k in season if k not in hist]
    return Counter({k: total * (w * hist.get(k, 0) / h + (1.0 - w) * season.get(k, 0) / s) for k in keys})


def blend_keyed(hist, season, weight_of_key, stats=None):
    """A new {key: counts} with each key blended at its own weight. `stats` (a Counter) records how many keys were blended,
    kept as history, or taken from the current season alone."""
    stats = Counter() if stats is None else stats
    out = dict(hist)
    for key, counts in season.items():
        if not sum(counts.values()):
            continue
        if key in hist and sum(hist[key].values()):
            out[key] = blend_counts(hist[key], counts, weight_of_key(key))
            stats['blended'] += 1
        else:
            out[key] = Counter(counts)
            stats['season_only'] += 1
    stats['history_only'] += sum(1 for key in hist if key not in season)
    return out


def digest(value):
    """A stable SHA-256 of a blended table's counts, for the layer manifest."""
    def plain(v):
        if isinstance(v, dict):
            return sorted(([plain(k), plain(x)] for k, x in v.items()), key=lambda pair: json.dumps(pair[0], default=str))
        if isinstance(v, (list, tuple, set, frozenset)):
            return [plain(x) for x in v]
        if isinstance(v, float):
            return round(v, 12)
        return v
    return hashlib.sha256(json.dumps(plain(value), default=str, separators=(',', ':')).encode()).hexdigest()


def player_games(db, evidence):
    """{(role, player): current-season games with an opportunity in that role}: dropbacks for a QB (passer), targets for a
    receiver, carries for a rusher. The player-keyed tables weight each player by these games."""
    where, params = evidence.sql_filter()
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        out = {}
        for role, column, condition in (('qb', 'passer_player_id', 'qb_dropback = 1'),
                                        ('receiver', 'receiver_player_id', 'pass_attempt = 1'),
                                        ('rusher', 'rusher_player_id', 'rush_attempt = 1')):
            for player, games in con.execute(f"SELECT {column}, COUNT(DISTINCT game_id) FROM nfl_pbp WHERE {where} "
                                             f"AND week <= 18 AND {condition} AND {column} IS NOT NULL GROUP BY {column}",
                                             params):
                out[(role, player)] = games
        return out
    finally:
        con.close()


def _summary(stats, extra=None):
    return {'keys_blended': stats['blended'], 'keys_from_season_only': stats['season_only'],
            'keys_history_only': stats['history_only'], **(extra or {})}


def adapt_target_roles(table, db, evidence):
    import target_roles as tr
    season = tr.load(db, None, evidence=evidence)
    stats = Counter()
    team = blend_keyed(table['team'], season['team'], lambda key: evidence.team_weight(key[0]), stats)
    return {**table, 'team': team}, _summary(stats)


def adapt_decision(table, db, evidence):
    """(blended decision table, the current-season decision fit, summary). The fit is reused by the playbook blend."""
    import decision_layer as dl
    rows = dl.load_rows(db, None, evidence=evidence)
    season = dl.fit(rows, prior_season=evidence.season)
    stats = Counter()
    team = {cat: blend_keyed(table['team'][cat], season['team'][cat], lambda key: evidence.team_weight(key[0]), stats)
            for cat in table['team']}
    return {**table, 'team': team}, season, _summary(stats, {'charted_plays': len(rows)})


def adapt_playbook(table, season_decision, evidence):
    """The playbook prior's categories (pass depth, pass location, run gap) take the current season's decision labels for the
    same categories; there are no current-season playbook files, and the labels describe the same plays."""
    stats = Counter()
    team = {cat: blend_keyed(table['team'][cat], season_decision['team'].get(cat, {}),
                             lambda key: evidence.team_weight(key[0]), stats)
            for cat in table['team']}
    return {**table, 'team': team}, _summary(stats)


QB_TEAM_KEYS = ('team_cell', 'target_team_cell', 'qb_run_team_cell', 'qb_run_team_all')
QB_PLAYER_KEYS = ('qb_cell', 'target_qb_cell', 'qb_run_player_cell', 'qb_run_player_all')


def adapt_qb_decisions(table, db, evidence, games_of_player):
    import qb_decisions as qb
    season = qb.load(db, evidence.season, evidence=evidence)
    stats = Counter()
    out = dict(table)
    for name in QB_TEAM_KEYS:
        team_of = (lambda key: key) if name == 'qb_run_team_all' else (lambda key: key[0])
        out[name] = blend_keyed(table[name], season[name], lambda key, t=team_of: evidence.team_weight(t(key)), stats)
    for name in QB_PLAYER_KEYS:
        out[name] = blend_keyed(table[name], season[name],
                                lambda key: evidence.weight(games_of_player.get(('qb', key[1]), 0)), stats)
    out['historical_sha256'] = table['sha256']
    out['sha256'] = digest({name: out[name] for name in QB_TEAM_KEYS + QB_PLAYER_KEYS})
    return out, _summary(stats, {'season_dropbacks': season['source_counts']['qb_dropbacks_in_model_state']})


def adapt_player_outcomes(table, db, evidence, games_of_player):
    import player_outcomes as po
    season = po.load(db, evidence.season, evidence=evidence)
    stats = Counter()
    out = dict(table)
    out['event_counts'] = {role: blend_keyed(table['event_counts'][role], season['event_counts'][role],
                                             lambda player, r=role: evidence.weight(games_of_player.get((r, player), 0)), stats)
                           for role in table['event_counts']}
    out['team_player_events'] = {role: blend_keyed(table['team_player_events'][role], season['team_player_events'][role],
                                                   lambda key, r=role: evidence.weight(games_of_player.get((r, key[1]), 0)))
                                 for role in table['team_player_events']}
    results = {}
    for role, by_player in table['result_counts'].items():
        results[role] = dict(by_player)
        for player, by_event in season['result_counts'][role].items():
            w = evidence.weight(games_of_player.get((role, player), 0))
            results[role][player] = blend_keyed(by_player.get(player, {}), by_event, lambda _event, w=w: w)
    out['result_counts'] = results
    out['historical_sha256'] = table['sha256']
    out['sha256'] = digest({'events': out['event_counts'], 'results': out['result_counts']})
    return out, _summary(stats)


def adapt_shares(table, db, evidence):
    """Each player's base share of his team's targets or carries: w * the prior-season share + (1 - w) * the current-season
    share, over the union of both seasons' players on that team. The concentrations stay as fitted."""
    import share_distributions as sd
    base = {}
    teams_blended = Counter()
    for role, hist_base in table['base'].items():
        _games, counts = sd.team_game_counts(db, evidence.season, role, evidence=evidence)
        season_base = sd.base_shares(counts)
        by_team = {}
        for (team, player), share in hist_base.items():
            by_team.setdefault(team, {})[player] = [share, 0.0]
        for (team, player), share in season_base.items():
            by_team.setdefault(team, {}).setdefault(player, [0.0, 0.0])[1] = share
        blended = {}
        for team, players in by_team.items():
            if team not in counts:
                blended.update({(team, p): h for p, (h, _s) in players.items() if h})
                continue
            w = evidence.team_weight(team)
            blended.update({(team, p): w * h + (1.0 - w) * s for p, (h, s) in players.items()})
            teams_blended[role] += 1
        base[role] = blended
    return {**table, 'base': base}, {'teams_blended': dict(teams_blended)}


PBP_RELEASE = '/root/lp-snapshots/nfl-backfill-2026-11-03/raw/pbp/play_by_play_{season}.parquet'
SHIFT_STRENGTH = 25.0  # the point and streak splits' own prior strength, used for the score-clock offset too


def release_scores(season, path=None):
    """((game_id, play_id) -> pre-play scores, file SHA-256) from the nflverse play-by-play release. The pinned raw files of
    earlier seasons do not cover the current season, so its file is identified by the hash recorded here."""
    import pyarrow.parquet as pq
    path = path or PBP_RELEASE.format(season=season)
    with open(path, 'rb') as source:
        sha = hashlib.sha256(source.read()).hexdigest()
    table = pq.read_table(path, columns=['game_id', 'play_id', 'season_type', 'posteam_score', 'defteam_score',
                                         'score_differential', 'goal_to_go']).to_pydict()

    def whole(value):
        return None if value is None or value != value else int(value)
    scores = {}
    for i, (game, play) in enumerate(zip(table['game_id'], table['play_id'])):
        if play is None or table['season_type'][i] != 'REG':
            continue
        scores[(game, int(play))] = {key: whole(table[key][i]) for key in
                                     ('posteam_score', 'defteam_score', 'score_differential', 'goal_to_go')}
    return scores, sha


def season_frame(db, evidence, scores):
    """The play-call frame of the available current-season games, built by the same observation and frame code as V1."""
    import playcall_model as pm
    import playcall_observations as pco
    where, params = evidence.sql_filter()
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(f"SELECT {', '.join(pco.COLUMNS)} FROM nfl_pbp WHERE {where} AND week <= 18 "
                           "ORDER BY game_id, play_id", params).fetchall()
    finally:
        con.close()
    released = {game for game, _play in scores}
    unscored = sorted({row['game_id'] for row in rows} - released)
    if unscored:  # a game the other layers read would silently leave this frame with no pre-play scores
        raise ValueError(f'the play-by-play release has no scores for {len(unscored)} available game(s): {unscored}')
    observations = (pco.observation(dict(row), scores.get((row['game_id'], int(row['play_id'])))) for row in rows)
    return pm.frame_from_observations(observations, (evidence.season,))


def season_streak_states(db, evidence):
    """{game_id: {team: bucket}} for the available current-season games, from their published results."""
    import streak_splits as ss
    where, params = evidence.sql_filter()
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(f"SELECT season, week, game_id, home_team, away_team, home_score, away_score FROM nfl_schedule "
                           f"WHERE {where} AND game_type = 'REG' AND home_score IS NOT NULL", params).fetchall()
    finally:
        con.close()
    results = []
    for season, week, game_id, home, away, hs, aw in rows:
        outcome = None if hs == aw else hs > aw
        results.append((season, week, game_id, home, outcome))
        results.append((season, week, game_id, away, None if outcome is None else not outcome))
    return ss.streak_states(results)


def blend_shifts(hist, season, hist_teams, season_teams, weight_of_team, league_key=None, league_weight=None):
    """Shift tables keyed (team index, bucket): w * historical shift + (1 - w) * current-season shift. The two frames number
    their teams differently, so the current season's keys are mapped through the team code. A team with no current-season
    shift keeps its history; `league_key` rows (the league table) take `league_weight`."""
    code_of_season = {index: code for code, index in season_teams.items()}
    out = dict(hist['shift'])
    blended = 0
    for (index, bucket), shift in season['shift'].items():
        if league_key is not None and index == league_key:
            key, w = (index, bucket), league_weight
        else:
            code = code_of_season[int(index)]
            if code not in hist_teams:
                continue  # the artifact has no index for a team that is not in its history
            key, w = (hist_teams[code], bucket), weight_of_team(code)
        out[key] = w * hist['shift'].get(key, 0.0) + (1.0 - w) * shift
        blended += 1
    return {**hist, 'shift': out}, {'shifts_blended': blended}


def score_clock_offsets(layer, frame, evidence):
    """{(team, down - 1): log-odds offset} moving the artifact's team-by-down term toward the current season.

    For a team and down, the current-season residual is logit((Y + K * P) / (N + K)) - logit(P), where N plays had Y dropbacks
    and P is the artifact's mean predicted dropback probability on those same plays (K = SHIFT_STRENGTH). The offset applied is
    (1 - w) times that residual, so a team with no current-season games keeps the artifact unchanged."""
    import math
    import playcall_model as pm
    code_of = {index: code for code, index in frame.teams.items()}
    a = frame.a
    sums = {}
    for t, d, dist, field, score, clock, y in zip(a['team'], a['down'], a['dist'], a['field'], a['score'], a['clock'], a['y']):
        team = code_of[int(t)]
        p = float(pm.expit(layer.logit_of_buckets(int(d), int(dist), int(field), int(score), int(clock), team)))
        n, yy, pp = sums.get((team, int(d)), (0, 0.0, 0.0))
        sums[(team, int(d))] = (n + 1, yy + float(y), pp + p)

    def logit(p):
        p = min(max(p, 1e-6), 1 - 1e-6)
        return math.log(p / (1 - p))
    offsets = {}
    for (team, d), (n, y, p_sum) in sorted(sums.items()):
        p = p_sum / n
        residual = logit((y + SHIFT_STRENGTH * p) / (n + SHIFT_STRENGTH)) - logit(p)
        offsets[(team, d)] = (1.0 - evidence.team_weight(team)) * residual
    return offsets


UNCHANGED = {
    'formation_personnel_outcomes': 'no current-season participation release (nflverse pbp_participation ends at 2025 in the '
                                    '2026-10-27 backfill), so the formation and personnel priors stay historical',
    'defensive_coverage_outcomes': 'coverage comes from the same participation release, so the coverage priors stay historical',
    'outcome_pool_and_kicks': 'the drawn outcome rows, kick tables and participant lookups stay the historical pool; the team '
                              'outcome splits move which outcome type is drawn toward the current season',
    'current_streak_context': 'already the current season: each team\'s streak entering the game',
}


def apply(ref, db, evidence):
    """Blend every loaded layer of `ref` that has a current-season source toward the current season, in place, and record
    what was done on the sampler (season_blend_manifest, which the reference fingerprint and the layer manifest include)."""
    import point_splits as sp
    import streak_splits as ss
    sampler = ref.contextual_sampler
    layers = {}
    manifest = {'evidence': evidence.manifest(), 'rule': 'w = N0 / (N0 + g); counts blended as (h + s) * (w * H/h + (1 - w) * S/s)',
                'layers': layers, 'unchanged': dict(UNCHANGED)}
    if evidence.game_ids:
        games_of_player = player_games(db, evidence)
        if sampler.team_outcomes is not None:
            rows = tsa.load_plays(db, evidence.season, list(evidence.game_ids), evidence.cutoff)
            sampler.team_outcomes, diagnostics = tsa.adapt(sampler.team_outcomes, rows, n0=evidence.n0,
                                                           team_games=evidence.team_games)
            layers['team_offense_defense_outcomes'] = {k: diagnostics[k] for k in
                                                       ('plays', 'cells_blended', 'plays_without_history_cell')}
        if sampler.role_table is not None:
            sampler.role_table, layers['target_role_priors'] = adapt_target_roles(sampler.role_table, db, evidence)
        season_decision = None
        if sampler.decision_table is not None or sampler.playbook_table is not None:
            import decision_layer as dl
            if sampler.decision_table is not None:
                sampler.decision_table, season_decision, layers['decision_labels'] = adapt_decision(
                    sampler.decision_table, db, evidence)
            else:
                season_decision = dl.fit(dl.load_rows(db, None, evidence=evidence), prior_season=evidence.season)
        if sampler.playbook_table is not None:
            sampler.playbook_table, layers['playbook_priors'] = adapt_playbook(sampler.playbook_table, season_decision, evidence)
        if sampler.qb_decision_table is not None:
            sampler.qb_decision_table, layers['qb_decisions'] = adapt_qb_decisions(
                sampler.qb_decision_table, db, evidence, games_of_player)
        if sampler.player_outcome_table is not None:
            sampler.player_outcome_table, layers['player_conditioned_outcomes'] = adapt_player_outcomes(
                sampler.player_outcome_table, db, evidence, games_of_player)
        if sampler.share_table is not None:
            sampler.share_table, layers['dirichlet_player_target_carry_shares'] = adapt_shares(sampler.share_table, db, evidence)
        frame_layers = (sampler.point_shifts, sampler.streak_shifts, sampler.streak_league)
        if any(table is not None for table in frame_layers) or sampler.score_clock_playcalling_enabled:
            scores, scores_sha = release_scores(evidence.season)
            frame = season_frame(db, evidence, scores)
            manifest['season_frame'] = {'plays': len(frame), 'games': len(frame.games), 'score_source_sha256': scores_sha,
                                        'score_source': PBP_RELEASE.format(season=evidence.season)}
            cutoff = evidence.season + 1  # the frame holds only the current season
            team_index = sampler.layer.team_index  # the key space every shift lookup uses
            if sampler.point_shifts is not None:
                sampler.point_shifts, layers['point_splits'] = blend_shifts(
                    sampler.point_shifts, sp.priors(frame, cutoff), team_index, frame.teams, evidence.team_weight)
            if sampler.streak_shifts is not None or sampler.streak_league is not None:
                states = season_streak_states(db, evidence)
                if sampler.streak_shifts is not None:
                    sampler.streak_shifts, layers['team_streak_splits'] = blend_shifts(
                        sampler.streak_shifts, ss.priors(frame, states, cutoff), team_index, frame.teams, evidence.team_weight)
                if sampler.streak_league is not None:
                    league_w = evidence.weight(evidence.league_games())
                    sampler.streak_league, layers['league_streak_splits'] = blend_shifts(
                        sampler.streak_league, ss.league_priors(frame, states, cutoff), team_index, frame.teams,
                        evidence.team_weight, league_key=ss.LEAGUE, league_weight=league_w)
                    layers['league_streak_splits']['weight_on_history'] = league_w
            if sampler.score_clock_playcalling_enabled:
                sampler.season_team_down = score_clock_offsets(sampler.layer, frame, evidence)
                layers['score_clock_playcalling'] = {'team_down_offsets': len(sampler.season_team_down)}
    for name, table in (('team_offense_defense_outcomes', sampler.team_outcomes), ('target_role_priors', sampler.role_table),
                        ('decision_labels', sampler.decision_table), ('playbook_priors', sampler.playbook_table),
                        ('qb_decisions', sampler.qb_decision_table),
                        ('player_conditioned_outcomes', sampler.player_outcome_table),
                        ('dirichlet_player_target_carry_shares', sampler.share_table),
                        ('point_splits', sampler.point_shifts), ('team_streak_splits', sampler.streak_shifts),
                        ('league_streak_splits', sampler.streak_league), ('score_clock_playcalling', sampler.season_team_down)):
        if name not in layers:
            continue
        if hasattr(table, 'manifest'):  # team tendencies carry their own content hash
            layers[name]['table_sha256'] = table.manifest['sha256']
        elif isinstance(table, dict) and 'historical_sha256' in table:  # QB and player outcome tables: rehashed when blended
            layers[name]['table_sha256'] = table['sha256']
        else:
            layers[name]['table_sha256'] = digest(table)
    sampler.season_blend_manifest = manifest
    sampler.season_adapt = manifest
    return manifest
