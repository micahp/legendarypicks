"""Project an E2 game record onto the shared GRIDIRON-CONTRACT v1 document, and check the result against the contract.

The contract text is docs/GRIDIRON-CONTRACT-v1.md in the Gridiron repository, byte-identical in both repositories
(sha256 in CONTRACT_SHA256 below). This module reads nothing from the engine's own flags for the checks:
`check_document` works from the document alone, so the checker is independent of the projection.

Nothing is invented to satisfy a field. A field the source cannot supply is null and is reported as a violation with its
reason. valid_full_game stays false.

Usage: python3 shared_v1.py RECORD_JSON OUT_JSON   (a record as written by emit_game.py)
"""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import game_state as gs  # noqa: E402

CONTRACT_SHA256 = 'ae7b8a304dda480c3708b2543172f3fdc5064b156bf1b25816855acf31bc21b7'
CONTRACT_VERSION = '1.0'
EVENT_VOCABULARY = ('run', 'pass_complete', 'pass_incomplete', 'interception', 'sack', 'qb_scramble', 'punt',
                    'field_goal', 'extra_point', 'two_point_try', 'kickoff', 'kneel', 'spike', 'fumble', 'penalty',
                    'safety', 'period_end', 'game_end')
E1_TO_CONTRACT = {'run': 'run', 'pass_complete': 'pass_complete', 'pass_incomplete': 'pass_incomplete',
                  'interception': 'interception', 'sack': 'sack', 'punt': 'punt', 'field_goal_attempt': 'field_goal',
                  'fumble_lost': 'fumble'}
REQUIRED_TOP = ('schema_version', 'mode', 'simulation_id', 'game_id', 'scheduled_kickoff_utc', 'as_of_utc',
                'snapshot_hash', 'model_version', 'rules_version', 'seed', 'teams', 'roster_snapshot_id', 'provenance',
                'plays', 'summary')
REQUIRED_STATE = ('quarter', 'clock_seconds', 'offense_team', 'defense_team', 'home_score', 'away_score', 'down',
                  'yards_to_go', 'yardline_100', 'home_timeouts', 'away_timeouts', 'drive_index')
REQUIRED_OUTCOME = ('passer_id', 'receiver_id', 'air_yards', 'yac', 'yards_gained', 'duration_seconds',
                    'clock_runoff_seconds', 'out_of_bounds', 'touchdown', 'turnover')
UNRESOLVED_REASON = {
    'game_id': 'no scheduled game key: the game is an authored hypothetical, not a fixture',
    'scheduled_kickoff_utc': 'no scheduled kickoff: not a pregame simulation',
    'as_of_utc': 'no as-of time: not a pregame simulation',
    'snapshot_hash': 'no pregame snapshot: the record is not built from one',
    'roster_snapshot_id': 'no roster snapshot: lineups are not modelled',
}


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _elapsed(q, c):
    return (q - 1) * gs.QUARTER_LENGTH + (gs.QUARTER_LENGTH - c)


def _state(quarter, clock, offense, defense, yl, down, togo, scores, timeouts, drive_index):
    return {'quarter': quarter, 'clock_seconds': clock, 'offense_team': offense, 'defense_team': defense,
            'home_score': scores[0], 'away_score': scores[1], 'down': down, 'yards_to_go': togo,
            'yardline_100': yl, 'home_timeouts': timeouts[0], 'away_timeouts': timeouts[1],
            'drive_index': drive_index}


def project(record):
    """The v1 document for one engine record. Events are renumbered in chronological order."""
    sim = record['simulation_id']
    events = []
    running = {'scores': (0, 0), 'timeouts': (3, 3)}
    boundaries_by_drive = {}
    for b in record['boundaries']:
        boundaries_by_drive.setdefault(b['drive_index'], []).append(b)
    kicks_by_drive = {}
    for k in record['kickoffs']:
        kicks_by_drive.setdefault(k['after_drive'], []).append(k)
    drives = record['drives']

    tracker = {'state': None}

    def emit(event):
        events.append(event)
        if event.get('state_after') is not None:
            tracker['state'] = event['state_after']

    def kickoff_event(k):
        nxt = drives[k['after_drive']] if k['after_drive'] < len(drives) else None
        spot = k['spot_yardline_100']
        end = _state(nxt['quarter_start'], nxt['clock_start'], k['receiving_team'], k['kicking_team'], spot, 1,
                     min(10, spot), running['scores'], running['timeouts'], k['after_drive'] + 1) if nxt else None
        before = _state(k['quarter'], k['clock_before'], k['kicking_team'], k['receiving_team'], None, None, None,
                        running['scores'], running['timeouts'], k['after_drive'] + 1)
        emit({'event_type': 'kickoff', 'state_before': before, 'state_after': end,
              'decision': {'type': 'kickoff', 'reason': k['kind'], 'concept': None, 'coverage': None},
              'outcome': {'kickoff_spot_yardline_100': spot, 'runoff_seconds': k['runoff_seconds'],
                          'clock_clamped_to_zero': k['clock_clamped_to_zero'], 'source_play': k['source']}})

    for k in kicks_by_drive.get(0, []):
        kickoff_event(k)
    for i, d in enumerate(drives):
        for play in d['plays']:
            ev = play['event_type']
            contract_ev = E1_TO_CONTRACT.get(ev, ev)
            if d['terminal'] == 'safety' and play is d['plays'][-1]:
                contract_ev = 'safety'
            sb, sa = play['state_before'], play['state_after']
            part = play['participants']
            yards = int(play['outcome']['yards_gained'] or 0)
            runoff = play['outcome']['clock_runoff_seconds']
            outcome = {
                'passer_id': (part['passer_id']
                              if ev in ('pass_complete', 'pass_incomplete', 'interception', 'sack') else None),
                'receiver_id': part['receiver_id'] if ev == 'pass_complete' else None,
                'rusher_id': part['rusher_id'] if ev == 'run' else None,
                'air_yards': part['air_yards'] if ev in ('pass_complete', 'pass_incomplete', 'interception') else None,
                'yac': part['yards_after_catch'] if ev == 'pass_complete' else None,
                'yards_gained': yards,
                'duration_seconds': None,  # not in the published table: stays null
                'clock_runoff_seconds': runoff,
                'out_of_bounds': bool(part['out_of_bounds']),
                'touchdown': bool(play['outcome']['touchdown']),
                'turnover': bool(play['outcome']['turnover']),
            }
            state_b = _state(sb['quarter'], sb['clock_seconds'], sb['offense_team'], sb['defense_team'],
                             sb['yardline_100'],
                             sb['down'], sb['yards_to_go'], (sb['home_score'], sb['away_score']),
                             (sb['home_timeouts'], sb['away_timeouts']), i + 1)
            state_a = _state(sa['quarter'], sa['clock_seconds'], sa['offense_team'], sa['defense_team'],
                             sa['yardline_100'],
                             sa['down'], sa['yards_to_go'], (sa['home_score'], sa['away_score']),
                             (sa['home_timeouts'], sa['away_timeouts']), i + 1)
            emit({'event_type': contract_ev, 'state_before': state_b, 'state_after': state_a,
                  'decision': {'type': play['decision']['type'], 'concept': None, 'coverage': None},
                  'outcome': outcome, 'participants_attribution': part['attribution']})
            if play['outcome']['quarter_change']:
                emit({'event_type': 'period_end', 'state_before': state_a, 'state_after': state_a,
                      'decision': {'type': 'period_end', 'concept': None, 'coverage': None},
                      'outcome': {'from_quarter': sb['quarter'], 'to_quarter': sa['quarter']}})
        scored = d['points_scored_on_drive']
        if scored and scored.get('try'):
            t = scored['try']
            last = d['plays'][-1]['state_after']
            kind = 'extra_point' if t['kind'] == 'extra_point' else 'two_point_try'
            st = _state(last['quarter'], last['clock_seconds'], d['offense_team'], last['defense_team'],
                        None, None, None,
                        (last['home_score'], last['away_score']), (last['home_timeouts'], last['away_timeouts']), i + 1)
            emit({'event_type': kind, 'state_before': st, 'state_after': st,
                  'decision': {'type': kind, 'concept': None, 'coverage': None},
                  'outcome': {'result': ('good' if kind == 'extra_point' else 'success') if t['made'] else
                              ('failed' if kind == 'extra_point' else 'failure'),
                              'points': gs.TRY_POINTS[t['kind']] if t['made'] else 0}})
        # running score and timeouts after the drive, from the drive's own last play
        last = d['plays'][-1]['state_after']
        running['scores'] = (last['home_score'], last['away_score'])
        running['timeouts'] = (last['home_timeouts'], last['away_timeouts'])
        for b in boundaries_by_drive.get(d['index'], []):
            if b['kind'] in ('change_of_ends', 'halftime'):
                held = dict(tracker['state'], clock_seconds=0)
                emit({'event_type': 'period_end', 'state_before': held, 'state_after': held,
                      'decision': {'type': 'period_end', 'concept': None, 'coverage': None},
                      'outcome': {'from_quarter': b['from_quarter'], 'to_quarter': b['to_quarter'], 'kind': b['kind']}})
        for k in kicks_by_drive.get(d['index'], []):
            kickoff_event(k)
    final = dict(tracker['state'], clock_seconds=0)
    emit({'event_type': 'game_end', 'state_before': final, 'state_after': final,
          'decision': {'type': 'game_end', 'concept': None, 'coverage': None},
          'outcome': {'final_home_score': record['points']['A'], 'final_away_score': record['points']['B']}})
    plays = []
    for seq, ev in enumerate(events, start=1):
        ev = dict(ev, sequence=seq, id=f'{sim}:{seq}')
        plays.append(ev)
    return plays


def build_document(record, legacy_seed_label=None):
    plays = project(record)
    doc = {
        'schema_version': CONTRACT_VERSION,
        'mode': record['mode'],
        'simulation_id': record['simulation_id'],
        'game_id': None,
        'scheduled_kickoff_utc': None,
        'as_of_utc': None,
        'snapshot_hash': None,
        'model_version': record['model_version'],  # stamped by versions.stamp; a record without it fails here
        'rules_version': record['rules_version'],
        'seed': record['seed'],
        'teams': {'home': 'A', 'away': 'B'},
        'roster_snapshot_id': None,
        'provenance': {'outcomes': 'sampled_observed_plays', 'lineups': 'sampled_observed_participants',
                       'routes': 'not_modelled', 'motion': 'not_modelled', 'sources_as_of_verified': False},
        'plays': plays,
        'summary': {'home_score': record['points']['A'], 'away_score': record['points']['B'],
                    'player_stats': recompute_player_stats(plays), 'team_stats': recompute_team_stats(plays),
                    'valid_full_game': bool(record['valid_full_game'])},
        'unresolved': dict(UNRESOLVED_REASON),
        'engine_status': {'status': record['status'], 'blocker': record['blocker'],
                          'complete_game': record['complete_game'], 'unsupported_rules': record['unsupported_rules']},
    }
    return doc


def recompute_team_stats(plays):
    """Team lines summed from the play log alone. The summary must equal these, and the checker recomputes them."""
    teams = {'A': Counter(), 'B': Counter()}
    for p in plays:
        if p['event_type'] not in ('run', 'pass_complete', 'pass_incomplete', 'interception', 'sack', 'punt',
                                   'field_goal', 'fumble', 'safety'):
            continue
        off = p['state_before']['offense_team'] if p['state_before'] else None
        if off not in teams:
            continue
        t = teams[off]
        t['plays'] += 1
        y = p['outcome'].get('yards_gained') or 0
        if p['event_type'] == 'run':
            t['rush_att'] += 1
            t['rush_yds'] += y
        if p['event_type'] in ('pass_complete', 'pass_incomplete', 'interception'):
            t['pass_att'] += 1
        if p['event_type'] == 'pass_complete':
            t['pass_comp'] += 1
            t['pass_yds'] += y
        if p['event_type'] == 'sack':
            t['sacks'] += 1
        if p['outcome'].get('touchdown'):
            t['touchdowns'] += 1
        if p['outcome'].get('turnover'):
            t['turnovers'] += 1
    return {k: dict(sorted(v.items())) for k, v in teams.items()}


def recompute_player_stats(plays):
    """Player lines summed from the play log: passing for the passer, receiving for the receiver, rushing for the
    rusher.
    """
    lines = {}

    def line(pid):
        return lines.setdefault(pid, {'passing': Counter(), 'receiving': Counter(), 'rushing': Counter()})

    for p in plays:
        ev = p['event_type']
        out = p['outcome']
        y = out.get('yards_gained') or 0
        if ev in ('pass_complete', 'pass_incomplete', 'interception') and out.get('passer_id'):
            pl = line(out['passer_id'])['passing']
            pl['att'] += 1
            if ev == 'pass_complete':
                pl['comp'] += 1
                pl['yds'] += y
                pl['td'] += int(bool(out.get('touchdown')))
            if ev == 'interception':
                pl['int'] += 1
        if ev == 'pass_complete' and out.get('receiver_id'):
            rc = line(out['receiver_id'])['receiving']
            rc['rec'] += 1
            rc['yds'] += y
            rc['td'] += int(bool(out.get('touchdown')))
        if ev == 'run' and out.get('rusher_id'):
            ru = line(out['rusher_id'])['rushing']
            ru['att'] += 1
            ru['yds'] += y
            ru['td'] += int(bool(out.get('touchdown')))
    return {pid: {k: dict(v) for k, v in cats.items() if v} for pid, cats in sorted(lines.items())}


def check_document(doc):
    """Violations of the contract, by ID, computed from the document alone. An empty list means no violation."""
    v = []

    def bad(vid, text):
        v.append({'id': vid, 'text': text})

    if doc.get('schema_version') != CONTRACT_VERSION:
        bad('V-schema', f"schema_version {doc.get('schema_version')!r}, contract is {CONTRACT_VERSION!r}")
    for key in REQUIRED_TOP:
        if key not in doc:
            bad(f'V-missing-{key}', f'top-level {key} is absent')
    if doc.get('mode') != 'pregame_full_game':
        bad('V-mode', f"mode {doc.get('mode')!r}; the contract's full-game mode is pregame_full_game, and this "
                      "record is not built from a pregame snapshot")
    for key, reason in UNRESOLVED_REASON.items():
        if doc.get(key) is None:
            bad(f'V-unresolved-{key}', f'{key} is null: {reason}')
    if 'provenance' in doc:
        prov = doc['provenance']
        for key in ('outcomes', 'lineups', 'routes', 'motion', 'sources_as_of_verified'):
            if key not in prov:
                bad(f'V-prov-{key}', f'provenance.{key} is absent')
    plays = doc.get('plays', [])
    seqs = [p.get('sequence') for p in plays]
    if seqs != list(range(1, len(plays) + 1)):
        bad('V-sequence', 'plays are not numbered 1..n in order')
    for p in plays:
        if p.get('id') != f"{doc.get('simulation_id')}:{p.get('sequence')}":
            bad('V-id', f"play {p.get('sequence')} id {p.get('id')!r} is not <simulation_id>:<sequence>")
            break
    for p in plays:
        ev = p.get('event_type')
        if ev not in EVENT_VOCABULARY:
            bad('V-event-vocabulary', f"play {p.get('sequence')} event_type {ev!r} is outside the contract vocabulary")
            break
    for p in plays:
        st = p.get('state_before')
        if st is None:
            continue
        for side in ('state_before', 'state_after'):
            s = p.get(side)
            if s is None:
                continue
            missing = [k for k in REQUIRED_STATE if k not in s]
            if missing:
                bad('V-state-fields', f"play {p['sequence']} {side} lacks {missing}")
                break
    for p in plays:
        if p.get('event_type') in ('run', 'pass_complete', 'pass_incomplete', 'interception', 'sack', 'field_goal',
                                   'punt', 'safety', 'fumble'):
            out = p.get('outcome', {})
            missing = [k for k in REQUIRED_OUTCOME if k not in out]
            if missing:
                bad('V-outcome-fields', f"play {p['sequence']} outcome lacks {missing}")
                break
    nulls = [p['sequence'] for p in plays if p.get('outcome') is not None
             and p['event_type'] in ('run', 'pass_complete', 'pass_incomplete', 'interception', 'sack', 'punt',
                                     'field_goal', 'fumble', 'safety')
             and p['outcome'].get('duration_seconds') is None]
    if nulls:
        bad('V-duration-seconds', f'{len(nulls)} plays have duration_seconds null: the published table has no play '
                                  'duration, so the value cannot be sourced')
    summary = doc.get('summary', {})
    if summary:
        if summary.get('player_stats') != recompute_player_stats(plays):
            bad('V-player-stats', 'summary.player_stats is not the sum of the play log')
        if summary.get('team_stats') != recompute_team_stats(plays):
            bad('V-team-stats', 'summary.team_stats is not the sum of the play log')
        if plays:
            last_scored = [p for p in plays if p.get('state_after')]
            if last_scored:
                st = last_scored[-1]['state_after']
                if (st['home_score'], st['away_score']) != (summary.get('home_score'), summary.get('away_score')):
                    bad('V-final-score', 'the final state score does not equal summary.home_score/away_score')
        if summary.get('valid_full_game') is True:
            bad('V-valid-claim', 'valid_full_game is true, which this record cannot support')
    return v


def main():
    record = json.loads(Path(sys.argv[1]).read_text())
    if 'record' in record:
        record = record['record']
    doc = build_document(record)
    Path(sys.argv[2]).write_text(json.dumps(doc, indent=1) + '\n')
    violations = check_document(doc)
    print(f'wrote {sys.argv[2]}: {len(doc["plays"])} events, {len(violations)} contract violations')
    for item in violations:
        print(f"  {item['id']}: {item['text']}")


if __name__ == '__main__':
    main()
