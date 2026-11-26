#!/usr/bin/env python3
"""Step through one simulated game play by play (debug mode).

Write the traces with the batch runner: simulate_pregame_batch.py ... --trace-dir DIR. Each seed gets DIR/seed-<n>.json.
Then:

    python3 step_trace.py DIR/seed-300001.json            # one play at a time
    python3 step_trace.py DIR/seed-300001.json --all      # every play, no prompts
    python3 step_trace.py DIR/seed-300001.json --start 40 # begin at play 40

Each play is shown in the order the engine decides it: the situation, the call model's dropback probability, the
personnel (and the previous personnel, the PBV1 package and the lineup), the formation, the dropback probability given
the personnel, the call, the players, and the outcome with its source play. Keys: Enter next, b back, a number jumps to
that play, r prints this play's full decision and play record, q quits.

The engine records one decision per play, in play order (slc_engine.validate_decision_outcomes refuses anything else), so
plays and decisions are paired by position. A game that failed partway has more decisions than plays; the extra decisions
are shown with no outcome.
"""
import argparse
import json
import sys


def plays_of(record):
    if not record:
        return []
    plays = [play for drive in record.get('drives', []) for play in drive.get('plays', [])]
    return plays + list((record.get('blocked_attempt') or {}).get('plays_before_block') or [])


def player_names(record):
    """gsis_id -> name, from any player entry the record carries."""
    names = {}

    def walk(value):
        if isinstance(value, dict):
            pid = value.get('gsis_id') or value.get('player_id')
            name = value.get('name') or value.get('player_name') or value.get('full_name')
            if isinstance(pid, str) and isinstance(name, str):
                names.setdefault(pid, name)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(record or {})
    return names


def clock_text(seconds):
    seconds = int(seconds)
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def field_text(yardline_100, offense, defense):
    """yardline_100 is the distance to the opponent's goal line."""
    yards = int(yardline_100)
    if yards == 50:
        return 'midfield'
    return f'{defense} {yards}' if yards < 50 else f'{offense} {100 - yards}'


def ordinal(down):
    return {1: '1st', 2: '2nd', 3: '3rd', 4: '4th'}.get(int(down), f'{down}th')


def _p(value):
    return '-' if value is None else f'{float(value):.3f}'


def render(index, total, decision, play, sides, names):
    """The text for one play: one line per decision step, in the engine's order."""
    state = decision.get('state') or {}
    offense = sides.get(state.get('offense'), state.get('offense'))
    defense = sides.get(state.get('defense'), state.get('defense'))
    lines = [f"Play {index + 1} of {total}   Q{state.get('quarter')} {clock_text(state.get('clock', 0))}   "
             f"{offense} ball   {ordinal(state.get('down', 1))} & {state.get('togo')} at "
             f"{field_text(state.get('yardline_100', 50), offense, defense)}   "
             f"score diff {state.get('score_diff', 0):+d} for {offense}"]
    order = decision.get('draw_order')
    lines.append(f"  1 call model   p(dropback) {_p(decision.get('p_dropback'))}   point shift "
                 f"{decision.get('point_shift', 0):+.3f}   streak shift {decision.get('streak_shift', 0):+.3f}   "
                 f"kick share {_p(decision.get('kick_share'))}")
    participants = decision.get('participants') or {}
    lineup = participants.get('lineup') or {}
    personnel = f"  2 personnel    {decision.get('personnel')}"
    if decision.get('previous_personnel') is not None:
        personnel += f"   previous {decision['previous_personnel']}"
    if decision.get('pbv1_package') is not None:
        personnel += f"   PBV1 package {decision['pbv1_package']}"
    if lineup:
        personnel += f"   lineup group {lineup.get('group')}"
    lines.append(personnel)
    if lineup.get('on_field'):
        lines.append('                 on field: ' + ', '.join(names.get(pid, pid) for pid in lineup['on_field']))
    if lineup.get('entrants') or lineup.get('leavers'):
        lines.append(f"                 in: {', '.join(names.get(p, p) for p in lineup.get('entrants') or []) or '-'}"
                     f"   out: {', '.join(names.get(p, p) for p in lineup.get('leavers') or []) or '-'}")
    lines.append(f"  3 formation    {decision.get('formation')}")
    lines.append(f"  4 call         {decision.get('intent')}   draw order {order or '-'}   "
                 f"p(dropback | personnel, formation) {_p(decision.get('p_dropback_given_personnel'))}"
                 + (f"   QB action {decision['qb_action']}" if decision.get('qb_action') else ''))
    roles = {role: pid for role, pid in participants.items() if isinstance(pid, str) and role != 'target_role'}
    if roles:
        lines.append('  5 players      ' + '   '.join(f'{role} {names.get(pid, pid)}' for role, pid in sorted(roles.items())))
    if participants.get('target_role'):
        lines.append(f"                 target role {participants['target_role']}")
    if decision.get('labels'):
        lines.append(f"                 labels {decision['labels']}")
    source = decision.get('source') or {}
    fallbacks = [name for name in ('fallback', 'source_fallback', 'outcome_fallback', 'formation_fallback',
                                   'coverage_fallback', 'streak_fallback') if decision.get(name)]
    lines.append(f"  6 outcome      event {decision.get('event')}   source {source.get('game_id')} play {source.get('play_id')}"
                 + (f"   fallbacks: {', '.join(f'{n}={decision[n]}' for n in fallbacks)}" if fallbacks else ''))
    if play is None:
        lines.append('                 no play record: the game stopped before this play was emitted')
    else:
        outcome = play.get('outcome') or {}
        result = f"                 {play.get('event_type')}   yards {outcome.get('yards_gained')}"
        for flag in ('touchdown', 'turnover'):
            if outcome.get(flag):
                result += f'   {flag.upper()}'
        lines.append(result)
        after = play.get('state_after') or {}
        if after:
            lines.append('                 after: ' + '   '.join(f'{key} {after[key]}' for key in sorted(after)
                                                                if not isinstance(after[key], (dict, list))))
    return '\n'.join(lines)


def load(path):
    with open(path, encoding='utf-8') as handle:
        trace = json.load(handle)
    if trace.get('schema') != 'lp-nfl-slc-play-trace-1':
        raise ValueError(f"{path} is not a play trace (schema {trace.get('schema')!r}); write one with --trace-dir")
    return trace


def main(argv=None, read=input, write=print):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('trace')
    ap.add_argument('--all', action='store_true', help='print every play, no prompts')
    ap.add_argument('--start', type=int, default=1, help='the first play to show (1 is the first)')
    args = ap.parse_args(argv)
    trace = load(args.trace)
    decisions, plays = trace['decisions'], plays_of(trace.get('record'))
    sides, names = trace.get('sides') or {}, player_names(trace.get('record'))
    total = len(decisions)
    write(f"{trace.get('game_id')}   seed {trace.get('seed')}   {total} decisions, {len(plays)} plays"
          + (f"   ERROR: {trace['error']}" if trace.get('error') else ''))
    if not total:
        return 0
    index = max(0, min(total - 1, args.start - 1))
    while True:
        write(render(index, total, decisions[index], plays[index] if index < len(plays) else None, sides, names))
        if args.all:
            if index == total - 1:
                return 0
            index += 1
            write('')
            continue
        try:
            key = read('[Enter] next  [b] back  [number] jump  [r] raw  [q] quit > ').strip().lower()
        except EOFError:
            return 0
        if key == 'q':
            return 0
        if key == 'r':
            write(json.dumps({'decision': decisions[index], 'play': plays[index] if index < len(plays) else None},
                             indent=1, sort_keys=True, default=str))
            continue
        if key == 'b':
            index = max(0, index - 1)
        elif key.isdigit():
            index = max(0, min(total - 1, int(key) - 1))
        elif index == total - 1:
            write('last play')
        else:
            index += 1


if __name__ == '__main__':
    sys.exit(main())
