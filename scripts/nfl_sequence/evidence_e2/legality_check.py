#!/usr/bin/env python3
"""Independent legality checker for E2 game records.

Reads a game record (the engine's dict, as in docs/fixtures/e2/e2-game-seed1.json) and checks it against the rules as
restated here. It imports nothing from the engine (game_state, rules_matrix, e1_drive, game_stats): the checks read the
record's own event, state and drive fields and nothing else.

A record is legal when every check returns no findings. A blocked record is never a complete game. Checks that need a
complete game are skipped only for blocked records, and then the blocked status itself is checked.

Usage: python3 legality_check.py RECORD.json
"""
import json
import sys

TEAMS = ('A', 'B')
QUARTERS = (1, 2, 3, 4)
DOWNS = (1, 2, 3, 4, None)
MAX_TIMEOUTS = 3
FULL_QUARTER = 900
def plays_of(record):
    for d in record['drives']:
        for p in d['plays']:
            yield d, p


def check_blocked(record):
    findings = []
    if record.get('status') == 'blocked' and (record.get('complete_regulation') or record.get('complete_game')):
        findings.append(f'blocked record ({record.get("blocker")}) marked as a complete game')
    if record.get('valid_full_game') is True and (
            record.get('mode') != 'pregame_full_game' or not record.get('complete_regulation')
            or record.get('blocker') is not None or record.get('tied')
            or record.get('unsupported_rules') or record.get('unmodelled_transitions')):
        findings.append('valid_full_game is true while its full-game acceptance gate is not satisfied')
    return findings


def check_clock_state_guard(record):
    """A full-game record carries the clock state and explicit transition that starts the next interval."""
    findings = []
    if record.get('mode') != 'pregame_full_game':
        return findings
    for d, p in plays_of(record):
        transition = p.get('outcome', {}).get('clock_transition')
        if not isinstance(transition, dict):
            findings.append(f'drive {d["index"]} play {p["sequence"]}: explicit clock transition is missing')
            continue
        if transition.get('clock_interval') != 'observed_snap_to_next_snap':
            findings.append(f'drive {d["index"]} play {p["sequence"]}: clock interval basis is missing')
        if transition.get('runoff_seconds') != p['outcome'].get('clock_runoff_seconds'):
            findings.append(f'drive {d["index"]} play {p["sequence"]}: transition runoff disagrees with the outcome')
        if p['state_before'].get('clock_status') != 'running_at_snap':
            findings.append(f'drive {d["index"]} play {p["sequence"]}: clock is not running at the snap')
        if transition.get('restart_trigger') not in ('next_snap', 'period_restart', 'free_kick_or_next_snap',
                                                       'referee_signal', 'continuous'):
            findings.append(f'drive {d["index"]} play {p["sequence"]}: unknown clock restart trigger')
        if transition.get('restart_trigger') != 'continuous' and transition.get('restart_clock_seconds') != p['state_after']['clock_seconds']:
            findings.append(f'drive {d["index"]} play {p["sequence"]}: restart clock disagrees with state_after')
    for i, kick in enumerate(record.get('kickoffs', [])):
        transition = kick.get('clock_transition')
        if (not isinstance(transition, dict) or transition.get('clock_starts_on') != 'legal_touch'
                or transition.get('runoff_seconds') != kick.get('runoff_seconds')
                or transition.get('restart_clock_seconds') != kick.get('clock_after')):
            findings.append(f'kickoff {i}: free-kick clock transition is missing or inconsistent')
    return findings


def check_completion(record):
    if not record.get('complete_regulation'):
        return []
    findings = []
    if record.get('final_quarter') != 4 or record.get('final_clock_seconds') != 0:
        findings.append(f'complete regulation ends in Q{record.get("final_quarter")} with {record.get("final_clock_seconds")} s')
    quarters = {s['quarter'] for _, p in plays_of(record) for s in (p['state_before'],)}
    missing = [q for q in QUARTERS if q not in quarters]
    if missing:
        findings.append(f'complete regulation with no plays in quarter(s) {missing}')
    return findings


def check_points(record):
    scored = {t: 0 for t in TEAMS}
    for d in record['drives']:
        pts = d.get('points_scored_on_drive') or {}
        if pts:
            scored[pts['team']] += pts['points']
    findings = []
    for t in TEAMS:
        if scored[t] != record['points'].get(t, 0):
            findings.append(f'team {t}: points on drives {scored[t]} != record points {record["points"].get(t, 0)}')
    return findings


def check_drives(record):
    findings = []
    indices = [d['index'] for d in record['drives']]
    if indices != list(range(1, len(indices) + 1)):
        findings.append(f'drive indices are not 1..{len(indices)}: {indices[:6]}')
    for d in record['drives']:
        if d['offense_team'] not in TEAMS:
            findings.append(f'drive {d["index"]}: offense {d["offense_team"]!r} is not A or B')
        for p in d['plays']:
            if p['state_before'].get('drive_index') != d['index'] or p['state_after'].get('drive_index') != d['index']:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: drive_index does not match the drive')
    return findings


def check_clock_and_quarter(record):
    findings = []
    for d in record['drives']:
        seq = d['plays']
        for i, p in enumerate(seq):
            s = p['state_before']
            if not 0 <= s['clock_seconds'] <= FULL_QUARTER:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: clock {s["clock_seconds"]} outside 0..900')
            if s['quarter'] not in QUARTERS:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: quarter {s["quarter"]} is not 1..4')
            if i + 1 < len(seq):
                nxt = seq[i + 1]['state_before']
                if nxt['quarter'] < s['quarter']:
                    findings.append(f'drive {d["index"]}: quarter falls from {s["quarter"]} to {nxt["quarter"]}')
                elif nxt['quarter'] == s['quarter'] and nxt['clock_seconds'] > s['clock_seconds']:
                    findings.append(f'drive {d["index"]}: clock rises from {s["clock_seconds"]} to {nxt["clock_seconds"]} '
                                    f'inside Q{s["quarter"]}')
    return findings


def check_state_continuity(record):
    findings = []
    for d in record['drives']:
        for p in d['plays']:
            before, after = p['state_before'], p['state_after']
            if after['clock_seconds'] > before['clock_seconds'] and after['quarter'] == before['quarter']:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: state_after clock rises inside the quarter')
            if after['quarter'] < before['quarter']:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: state_after quarter falls')
    for d, nxt_d in zip(record['drives'], record['drives'][1:]):
        last = d['plays'][-1] if d['plays'] else None
        if last is None:
            continue
        if nxt_d['plays']:
            first_next = nxt_d['plays'][0]['state_before']
            if first_next['quarter'] == last['state_after']['quarter'] and first_next['clock_seconds'] > last['state_after']['clock_seconds']:
                findings.append(f'drive {nxt_d["index"]}: clock rises at the start of the drive')
    return findings


def check_downs_and_field(record):
    findings = []
    for d, p in plays_of(record):
        for side in ('state_before', 'state_after'):
            s = p[side]
            if s.get('down') not in DOWNS:
                findings.append(f'drive {d["index"]} play {p["sequence"]} {side}: down {s.get("down")!r} is not 1..4')
            if s.get('down') is not None and (s.get('yards_to_go') is None or s['yards_to_go'] < 0):
                findings.append(f'drive {d["index"]} play {p["sequence"]} {side}: yards to go {s.get("yards_to_go")} invalid')
            yl = s.get('yardline_100')
            if yl is not None and not 1 <= yl <= 99:
                findings.append(f'drive {d["index"]} play {p["sequence"]} {side}: yardline_100 {yl} outside 1..99')
    return findings


def check_timeouts(record):
    """Counts stay in 0..3, never rise inside a half, and are three for each side when the second half begins."""
    findings = []
    previous = None  # (quarter, home, away) of the last play's state_before
    for d, p in plays_of(record):
        for side in ('state_before', 'state_after'):
            s = p[side]
            for key in ('home_timeouts', 'away_timeouts'):
                if not 0 <= s[key] <= MAX_TIMEOUTS:
                    findings.append(f'drive {d["index"]} play {p["sequence"]} {side}: {key} {s[key]} outside 0..3')
        s = p['state_before']
        if previous is not None:
            prev_q, prev_home, prev_away = previous
            if prev_q == 2 and s['quarter'] == 3:
                if s['home_timeouts'] != MAX_TIMEOUTS or s['away_timeouts'] != MAX_TIMEOUTS:
                    findings.append(f'drive {d["index"]} play {p["sequence"]}: timeouts do not reset to three at halftime')
            elif (prev_q <= 2) == (s['quarter'] <= 2):
                if s['home_timeouts'] > prev_home or s['away_timeouts'] > prev_away:
                    findings.append(f'drive {d["index"]} play {p["sequence"]}: a team gained timeouts inside a half')
        previous = (s['quarter'], s['home_timeouts'], s['away_timeouts'])
        participants = p.get('participants', {})
        if participants.get('timeout') and (
                record.get('mode') == 'pregame_full_game' or 'timeout_applied' in participants):
            team = participants.get('timeout_charged_to')
            applied = participants.get('timeout_applied') is True
            if not applied or team not in TEAMS:
                findings.append(f'drive {d["index"]} play {p["sequence"]}: timeout is uncharged or unassigned')
            else:
                key = 'home_timeouts' if team == 'A' else 'away_timeouts'
                before, after = p['state_before'][key], p['state_after'][key]
                if before - after != 1:
                    findings.append(f'drive {d["index"]} play {p["sequence"]}: timeout count did not drop for team {team}')
                transition = p.get('outcome', {}).get('clock_transition')
                if ((record.get('mode') == 'pregame_full_game' or transition is not None)
                        and not any(item.get('kind') == 'team_timeout' and item.get('team') == team
                                    for item in (transition or {}).get('stoppages', []))):
                    findings.append(f'drive {d["index"]} play {p["sequence"]}: timeout clock stop is missing')
    return findings


def check_possession(record):
    """The side with the next drive is the side the record says has the ball.

    At halftime the next drive is the receiver of the second-half kickoff. After a score or a made field goal it is the
    receiver of the kickoff recorded after that drive. After a punt, a turnover or a missed field goal it is the side on
    the ball in the last play's state_after. A drive with no such record (for example a skipped post-score kickoff at a
    quarter end) is not checked, and the record does not say who gets the ball there.
    """
    findings = []
    drives = record['drives']
    halftime_after = {b['drive_index'] for b in record['boundaries'] if b['kind'] == 'halftime'}
    half_start = {k['quarter']: k for k in record['kickoffs'] if k['kind'] == 'half_start'}
    kick_after = {k['after_drive']: k for k in record['kickoffs'] if k['kind'] != 'half_start'}
    for d, nxt in zip(drives, drives[1:]):
        want = None
        if d['index'] in halftime_after and 3 in half_start:
            want = half_start[3]['receiving_team']
        elif d['index'] in kick_after:
            want = kick_after[d['index']]['receiving_team']
        elif d['terminal'] == 'field_goal_attempt' and d['field_goal_made'] is False:
            want = 'B' if d['offense_team'] == 'A' else 'A'  # a missed kick: the other side takes over at the kick spot
        elif d['terminal'] in ('punt', 'turnover', 'turnover_on_downs'):
            want = d['plays'][-1]['state_after']['offense_team']
        if want is not None and nxt['offense_team'] != want:
            findings.append(f'drive {d["index"]} ends {d["terminal"]}: the next drive is {nxt["offense_team"]}, '
                            f'the record gives the ball to {want}')
    return findings


def check_events(record):
    findings = []
    for d in record['drives']:
        for i, p in enumerate(d['plays']):
            ev = p['event_type']
            # A punt ends its drive, or it runs the clock out in Q2 or Q4: then the half or the game ends the drive, on that punt.
            clock_ends = (d['terminal'] in LATE_CLOCK_TERMINALS and i == len(d['plays']) - 1
                          and p['state_after']['clock_seconds'] == 0)
            if ev == 'punt' and d['terminal'] != 'punt' and not clock_ends:
                findings.append(f'drive {d["index"]}: a punt play in a drive that ends {d["terminal"]}')
            if ev == 'field_goal_attempt' and (i != len(d['plays']) - 1 or d['terminal'] != 'field_goal_attempt'):
                findings.append(f'drive {d["index"]}: a field goal attempt that is not the last play of the drive')
            if p['outcome'].get('touchdown') and d['terminal'] != 'touchdown':
                findings.append(f'drive {d["index"]}: a touchdown play in a drive that ends {d["terminal"]}')
    for d in record['drives']:
        if d['terminal'] == 'touchdown' and (d.get('points_scored_on_drive') or {}).get('points', 0) < 6:
            findings.append(f'drive {d["index"]}: a touchdown with fewer than six points')
    return findings


def check_blocked_kicks(record):
    """Independently verify blocked-kick classification, pinned source provenance and the resulting possession."""
    findings = []
    observed = (((record.get('pregame_snapshot') or {}).get('model_reference') or {}).get('observed_reference') or {})
    fixture_hash = observed.get('blocked_kick_source_sha256')
    input_hashes = observed.get('blocked_kick_input_source_sha256') or {}
    supported = {'classified_recovery', 'classified_dead_ball_spot', 'classified_next_snap', 'touchdown', 'safety'}
    for drive, play in plays_of(record):
        event = play['event_type']
        outcome = play['outcome']
        blocked = outcome.get('blocked_kick')
        if event not in ('blocked_punt', 'blocked_field_goal'):
            if blocked or outcome.get('field_goal_result') == 'blocked':
                findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked-kick result has no blocked event')
            continue
        kick_type = 'punt' if event == 'blocked_punt' else 'field_goal'
        if not isinstance(blocked, dict) or blocked.get('kick_type') != kick_type:
            findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked event has no matching outcome record')
            continue
        if blocked.get('classification_status') not in supported:
            findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked outcome is unresolved')
        source = blocked.get('source_sha256')
        if (not isinstance(source, str) or len(source) != 64 or not blocked.get('source_file')
                or not blocked.get('game_id') or not isinstance(blocked.get('play_id'), int)):
            findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked outcome lacks source provenance')
        elif fixture_hash and blocked.get('reference_fixture_sha256') != fixture_hash:
            findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked fixture is not pinned by the snapshot')
        if input_hashes and input_hashes.get(blocked.get('source_file')) != source:
            findings.append(f'drive {drive["index"]} play {play["sequence"]}: raw source file is not pinned by the snapshot')
        if kick_type == 'field_goal':
            if not outcome.get('field_goal_attempt') or outcome.get('field_goal_result') != 'blocked':
                findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked field goal is not counted as a blocked attempt')
        elif not outcome.get('punt_attempt'):
            findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked punt is not counted as a punt attempt')

        before, after = play['state_before'], play['state_after']
        role = blocked.get('recovery_role')
        if outcome.get('touchdown') or outcome.get('safety'):
            scoring_role = blocked.get('scoring_role')
            expected_scorer = before['offense_team'] if scoring_role == 'kicking_team' else before['defense_team']
            if (scoring_role not in ('kicking_team', 'receiving_team')
                    or outcome.get('scoring_team') != expected_scorer
                    or (drive.get('points_scored_on_drive') or {}).get('team') != expected_scorer):
                findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked-kick score is credited to the wrong team')
            continue
        if after.get('end_of_drive') in ('halftime', 'end_of_regulation'):
            continue  # the half/game ends on the kick; there is no next scrimmage state to compare
        if blocked.get('classification_status') == 'classified_next_snap':
            possession_role = blocked.get('possession_after_role')
            spot, down, togo = (blocked.get('next_snap_yardline_100'), blocked.get('next_snap_down'),
                                blocked.get('next_snap_ydstogo'))
            if (possession_role not in ('receiving_team', 'kicking_team')
                    or not all(type(value) is int for value in (spot, down, togo))
                    or not 1 <= spot <= 99 or not 1 <= down <= 4 or not 1 <= togo <= spot):
                findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked next snap has illegal spot, down or distance')
                continue
            expected_offense = before['defense_team'] if possession_role == 'receiving_team' else before['offense_team']
            expected_defense = before['offense_team'] if possession_role == 'receiving_team' else before['defense_team']
            if (after.get('offense_team') != expected_offense or after.get('defense_team') != expected_defense
                    or after.get('yardline_100') != spot or after.get('down') != down
                    or after.get('yards_to_go') != togo):
                findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked next snap disagrees with the projected state')
            if (bool(outcome.get('turnover')) != (possession_role == 'receiving_team')
                    or bool(outcome.get('turnover_on_downs'))):
                findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked next-snap possession is misclassified')
            continue
        if role == 'receiving_team' or blocked.get('classification_status') == 'classified_dead_ball_spot':
            delta = (blocked.get('return_endpoint_yards_from_los') if role == 'receiving_team'
                     else blocked.get('dead_ball_yards_from_los'))
            expected_spot = 100 - before['yardline_100'] + delta if isinstance(delta, int) else None
            if (after.get('offense_team') != before['defense_team'] or not outcome.get('turnover')
                    or after.get('yardline_100') != expected_spot):
                findings.append(f'drive {drive["index"]} play {play["sequence"]}: receiving-team recovery has the wrong possession or spot')
        elif role == 'kicking_team' and isinstance(blocked.get('recovery_yards_from_los'), int):
            crossed = blocked['recovery_yards_from_los'] > 0
            if crossed:
                touched = blocked.get('receiving_team_touched_beyond_line')
                if touched not in (0, 1, False, True):
                    findings.append(f'drive {drive["index"]} play {play["sequence"]}: beyond-line recovery has no receiver-touch classification')
                elif bool(touched):
                    if after.get('offense_team') != before['offense_team'] or after.get('down') != 1:
                        findings.append(f'drive {drive["index"]} play {play["sequence"]}: legal beyond-line recovery did not award a new series')
                elif after.get('offense_team') != before['defense_team'] or not outcome.get('turnover'):
                    findings.append(f'drive {drive["index"]} play {play["sequence"]}: beyond-line recovery without a receiver touch has the wrong possession')
            elif after.get('yardline_100') is not None:
                endpoint_delta = blocked.get('return_endpoint_yards_from_los')
                endpoint = before['yardline_100'] - endpoint_delta if isinstance(endpoint_delta, int) else None
                gained = endpoint_delta if isinstance(endpoint_delta, int) else None
                if gained is None:
                    findings.append(f'drive {drive["index"]} play {play["sequence"]}: kicking-team recovery has no return endpoint')
                elif gained >= before['yards_to_go']:
                    if after.get('offense_team') != before['offense_team'] or after.get('down') != 1:
                        findings.append(f'drive {drive["index"]} play {play["sequence"]}: kicking-team recovery conversion is wrong')
                elif before['down'] == 4:
                    if after.get('offense_team') != before['defense_team'] or not outcome.get('turnover_on_downs'):
                        findings.append(f'drive {drive["index"]} play {play["sequence"]}: fourth-down blocked-kick failure is wrong')
                elif after.get('offense_team') != before['offense_team'] or after.get('down') != before['down'] + 1:
                    findings.append(f'drive {drive["index"]} play {play["sequence"]}: kicking-team recovery did not continue its series')
        elif blocked.get('classification_status') not in ('period_expired', 'touchdown', 'safety'):
            findings.append(f'drive {drive["index"]} play {play["sequence"]}: blocked outcome has no recovery or award team')
    return findings


TRY_FIELDS = {'extra_point': ('extra_point_result', {'good': True, 'failed': False}),
              'two_point': ('two_point_conv_result', {'success': True, 'failure': False})}
TWO_MINUTE_MARK = 120
LATE_QUARTERS = (2, 4)


def check_conversions(record):
    """Every extra-point and two-point try carries its publisher result field, with a value that matches its made flag. An
    EPA-derived `success` flag is never accepted as a try result, and a touchdown needs a try record unless the game is blocked.
    """
    findings = []
    for d in record['drives']:
        t = (d.get('points_scored_on_drive') or {}).get('try')
        if t is None:
            if d['terminal'] == 'touchdown' and record.get('status') != 'blocked':
                findings.append(f'drive {d["index"]}: a touchdown with no try record')
            continue
        kind = t.get('kind')
        if kind not in TRY_FIELDS:
            findings.append(f'drive {d["index"]}: try kind {kind!r} has no publisher field')
            continue
        field, values = TRY_FIELDS[kind]
        if field not in t:
            findings.append(f'drive {d["index"]}: {kind} try lacks the publisher field {field}')
        elif values.get(t[field]) is None or values[t[field]] != bool(t.get('made')):
            findings.append(f'drive {d["index"]}: {kind} try {field}={t[field]!r} disagrees with made={t.get("made")!r}')
        if 'success' in t or any('epa' in k.lower() for k in t):
            findings.append(f'drive {d["index"]}: {kind} try carries an EPA-derived success flag')
    return findings


def check_unmodelled(record):
    """Derive unmodelled events without trusting the record's transition list."""
    findings = []
    for d in record['drives']:
        if d['terminal'] == 'field_goal_attempt' and d.get('field_goal_made') is False:
            returned = d['plays'][-1]['outcome'].get('field_goal_return')
            if not isinstance(returned, dict) or returned.get('status') not in (
                    'sampled_historical_next_drive_spot', 'period_expired'):
                findings.append(f'missed field goal return not modelled: drive {d["index"]}')
            else:
                snap = d['plays'][-1]['state_before']['yardline_100']
                kick_spot = min(99, snap + 7)
                base_spot = 80 if 100 - kick_spot > 80 else 100 - kick_spot
                if returned.get('baseline_yardline_100') != base_spot:
                    findings.append(f'missed field goal baseline is wrong: drive {d["index"]}')
                elif returned.get('status') == 'period_expired':
                    if (d['end_clock'] != 0 or d['end_quarter'] not in (2, 4)
                            or returned.get('receiving_start_yardline_100') is not None):
                        findings.append(f'missed field goal period-expiry transition is invalid: drive {d["index"]}')
                else:
                    spot = returned.get('receiving_start_yardline_100')
                    adjustment = returned.get('spot_adjustment_yards')
                    if (not isinstance(spot, int) or not 1 <= spot <= 99 or not isinstance(adjustment, int)
                            or spot != base_spot + adjustment or returned.get('pool_sample_count', 0) < 30
                            or not isinstance(returned.get('source'), dict)):
                        findings.append(f'missed field goal receiving spot is invalid: drive {d["index"]}')
                    elif d['index'] < len(record['drives']) and not (
                            d['end_clock'] == 0 and d['end_quarter'] in (2, 4)):
                        nxt = record['drives'][d['index']]
                        if (nxt['offense_team'] != d['plays'][-1]['state_after']['defense_team']
                                or nxt['plays'][0]['state_before']['yardline_100'] != spot):
                            findings.append(f'missed field goal next possession disagrees with sampled spot: drive {d["index"]}')
        for p in d['plays']:
            if p['outcome'].get('penalty'):
                findings.append(f'penalty transition not modelled: drive {d["index"]} play {p["sequence"]}')
            if p['participants'].get('timeout') and not p['participants'].get('timeout_applied'):
                findings.append(f'timeout stoppage not modelled: drive {d["index"]} play {p["sequence"]}')
            before, after = p['state_before'], p['state_after']
            if (before['quarter'] in LATE_QUARTERS and after['quarter'] == before['quarter']
                    and before['clock_seconds'] > TWO_MINUTE_MARK >= after['clock_seconds'] > 0):
                transition = p['outcome'].get('clock_transition') or {}
                stoppages = transition.get('stoppages', [])
                if (not p['outcome'].get('two_minute_warning')
                        or not any(item.get('kind') == 'automatic_two_minute_warning' for item in stoppages)
                        or transition.get('restart_trigger') != 'next_snap'):
                    findings.append(f'two-minute warning clock transition missing: drive {d["index"]} play {p["sequence"]}')
    for i, kick in enumerate(record['kickoffs']):
        clock_after = kick.get('clock_after', max(0, kick['clock_before'] - kick['runoff_seconds']))
        expired = kick.get('clock_expired_during_kickoff', kick['runoff_seconds'] >= kick['clock_before'])
        if (kick['quarter'] in LATE_QUARTERS and not expired
                and kick['clock_before'] > TWO_MINUTE_MARK >= clock_after > 0):
            transition = kick.get('clock_transition') or {}
            stoppages = transition.get('stoppages', [])
            if (not kick.get('two_minute_warning')
                    or not any(item.get('kind') == 'automatic_two_minute_warning' for item in stoppages)
                    or transition.get('restart_trigger') != 'next_snap'):
                findings.append(f'two-minute warning clock transition missing: kickoff {i}')
    return findings


def check_two_minute(record):
    """Independently derive each warning from the down's actual end clock, including kickoffs.

    Rule 3 Section 41 places the automatic timeout at the end of the down that crosses 2:00. The clock keeps its observed value
    at the dead ball; a play that expires the period does not trigger another warning.
    """
    findings = []
    expected_plays, expected_kicks = set(), set()
    for d in record['drives']:
        for p in d['plays']:
            b, a = p['state_before'], p['state_after']
            if (b['quarter'] in LATE_QUARTERS and a['quarter'] == b['quarter'] and
                    b['clock_seconds'] > TWO_MINUTE_MARK >= a['clock_seconds'] > 0):
                expected_plays.add((d['index'], p['sequence'], a['clock_seconds']))
    for i, k in enumerate(record['kickoffs']):
        clock_after = k.get('clock_after', max(0, k['clock_before'] - k['runoff_seconds']))
        expired = k.get('clock_expired_during_kickoff', k['runoff_seconds'] >= k['clock_before'])
        if (k['quarter'] in LATE_QUARTERS and not expired and
                k['clock_before'] > TWO_MINUTE_MARK >= clock_after > 0):
            expected_kicks.add((i, clock_after))

    marked_plays = {(d['index'], p['sequence'], p['state_after']['clock_seconds'])
                    for d in record['drives'] for p in d['plays'] if p['outcome'].get('two_minute_warning')}
    marked_kicks = {(i, k.get('clock_after', max(0, k['clock_before'] - k['runoff_seconds'])))
                    for i, k in enumerate(record['kickoffs'])
                    if k.get('two_minute_warning')}
    if marked_plays != expected_plays:
        findings.append(f'play warning markers disagree with derived crossings: {len(marked_plays)} marked, '
                        f'{len(expected_plays)} expected')
    if marked_kicks != expected_kicks:
        findings.append(f'kickoff warning markers disagree with derived crossings: {len(marked_kicks)} marked, '
                        f'{len(expected_kicks)} expected')
    for d, p in plays_of(record):
        marked = bool(p['outcome'].get('two_minute_warning'))
        transition = p['outcome'].get('clock_transition')
        has_stop = any(item.get('kind') == 'automatic_two_minute_warning'
                       for item in (transition or {}).get('stoppages', []))
        if (record.get('mode') == 'pregame_full_game' or transition is not None) and marked != has_stop:
            findings.append(f'drive {d["index"]} play {p["sequence"]}: warning marker and clock stop disagree')
    for i, k in enumerate(record['kickoffs']):
        marked = bool(k.get('two_minute_warning'))
        transition = k.get('clock_transition')
        has_stop = any(item.get('kind') == 'automatic_two_minute_warning'
                       for item in (transition or {}).get('stoppages', []))
        if (record.get('mode') == 'pregame_full_game' or transition is not None) and marked != has_stop:
            findings.append(f'kickoff {i}: warning marker and clock stop disagree')
    for q in LATE_QUARTERS:
        count = sum(1 for d in record['drives'] for p in d['plays']
                    if p['outcome'].get('two_minute_warning') and p['state_before']['quarter'] == q)
        count += sum(1 for k in record['kickoffs'] if k.get('two_minute_warning') and k['quarter'] == q)
        if count > 1:
            findings.append(f'more than one two-minute warning in Q{q}: {count}')
    return findings


POSSESSION_TERMINALS = ('turnover', 'turnover_on_downs', 'punt')
LATE_CLOCK_TERMINALS = ('halftime', 'end_of_regulation')


def check_half_end(record):
    """A possession change on the play that runs out the clock in Q2 or Q4 ends the half, so no drive ends on it. Derived from
    each drive's last play, not from the terminal alone."""
    findings = []
    for d in record['drives']:
        last = d['plays'][-1]['state_after']
        if d['terminal'] in POSSESSION_TERMINALS and last['quarter'] in LATE_QUARTERS and last['clock_seconds'] == 0:
            findings.append(f'drive {d["index"]} ends by {d["terminal"]} at the end of Q{last["quarter"]}: the half or the game '
                            f'ends the drive')
    return findings


MODELLED_CHECKS = (check_blocked, check_blocked_kicks, check_clock_state_guard, check_completion, check_points, check_drives, check_clock_and_quarter, check_two_minute,
                   check_half_end, check_state_continuity, check_downs_and_field, check_timeouts, check_possession, check_events,
                   check_conversions)
UNMODELLED_CHECKS = (check_unmodelled,)
CHECKS = MODELLED_CHECKS + UNMODELLED_CHECKS


def run(record):
    """{check name: findings} for every check, modelled and unmodelled."""
    return {fn.__name__: fn(record) for fn in CHECKS}


def legal_modelled(record):
    """Every check on what the engine models passes. Unmodelled transitions are not judged here."""
    return all(not findings for fn in MODELLED_CHECKS for findings in [fn(record)])


def legal_complete_game(record):
    """A legal complete game: consistent under the modelled rules, complete regulation, and with no unmodelled transition."""
    return (legal_modelled(record) and bool(record.get('complete_regulation'))
            and not check_unmodelled(record)
            and (record.get('mode') != 'pregame_full_game' or record.get('valid_full_game') is True))


def legal(record):
    """Kept for the earlier evidence: the modelled-rule verdict."""
    return legal_modelled(record)


def main():
    with open(sys.argv[1]) as f:
        record = json.load(f)
    record = record.get('record', record)
    results = run(record)
    failed = {k: v for k, v in results.items() if v}
    print(json.dumps({'legal_modelled': legal_modelled(record), 'legal_complete_game': legal_complete_game(record),
                      'checks': len(results), 'failed': failed}, indent=1))
    return 0 if legal_modelled(record) else 1


if __name__ == '__main__':
    sys.exit(main())
