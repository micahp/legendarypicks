"""Build the 90-minute cutoff snapshot after the fact for games the runner recorded as missed.

The depth chart file keeps every capture with its dt stamp, so the version at or before each game's cutoff is the same
one the live job would have used (label VERIFIED). The injury and roster files have no publication time and are fetched
now, after the cutoff: they are labelled FETCHED_AFTER_CUTOFF and may hold changes made after the cutoff.
A game moves from missed to done with backfilled_at_utc; the state is saved after every game. An existing snapshot file
is never overwritten: one already written by an earlier backfill is recorded as done, not rebuilt.

Usage: python3 backfill_cutoff.py [GAME_ID ...]   (default: every missed game whose kickoff has passed)
"""
import datetime as dt
import json
import sys

import cutoff_runner as cr


def main(argv):
    now = cr.now_utc()
    state = cr.load_state()
    games = {g[0]: g for g in cr.schedule_rows(now)}
    wanted = argv or sorted(state['missed'])
    run_dir = cr.ROOT / 'runs' / ('backfill-' + now.strftime('%Y%m%dT%H%M%SZ'))
    fetched = cr.fetch_sources(run_dir)
    fetched_at = cr.now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')
    built, refused = 0, []
    for game_id in wanted:
        if game_id not in state['missed'] or game_id not in games:
            refused.append(f'{game_id}: not a missed game in the schedule')
            continue
        _, week, gameday, gametime, away, home = games[game_id]
        kick = cr.kickoff_utc(gameday, gametime)
        cutoff = kick - dt.timedelta(minutes=90)
        if now < kick:
            refused.append(f'{game_id}: kickoff not passed yet; the live job builds it')
            continue
        out = cr.snapshot_path(week, game_id)
        if out.exists():
            existing = json.loads(out.read_text())
            if 'backfilled' not in existing:
                refused.append(f'{game_id}: {out} exists and is not a backfill')
                continue
            state['done'][game_id] = {'cutoff_utc': cutoff.isoformat(), 'fetched_at_utc': existing['fetched_at_utc'],
                                      'file': str(out), 'backfilled_at_utc': existing['backfilled']['built_at_utc']}
            del state['missed'][game_id]
            cr.save_state(state)
            built += 1
            print('RECORDED', game_id, out, flush=True)
            continue
        game = {'game_id': game_id, 'week': week, 'away': away, 'home': home,
                'kickoff_utc': kick.isoformat(), 'cutoff_utc': cutoff.isoformat()}
        snap, problem = cr.build(game, cutoff, fetched, fetched_at)
        if problem:
            refused.append(f'{game_id}: {problem}')
            continue
        basis = (f'nflverse file has no publication time; fetched {fetched_at}, after the cutoff, by backfill_cutoff.py. '
                 'It may hold changes made after the cutoff.')
        snap['fields']['injury_report'] = {'label': 'FETCHED_AFTER_CUTOFF', 'basis': basis}
        snap['fields']['roster_status'] = {'label': 'FETCHED_AFTER_CUTOFF', 'basis': basis}
        snap['backfilled'] = {'built_at_utc': fetched_at, 'reason_missed': state['missed'][game_id].get('reason')}
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('x') as handle:
            handle.write(json.dumps(snap, indent=1) + '\n')
        state['done'][game_id] = {'cutoff_utc': cutoff.isoformat(), 'fetched_at_utc': fetched_at, 'file': str(out),
                                  'backfilled_at_utc': fetched_at}
        del state['missed'][game_id]
        cr.save_state(state)
        built += 1
        print('BACKFILLED', game_id, snap['fields']['depth_chart_version']['value'], flush=True)
    cr.save_state(state)
    for line in refused:
        print('REFUSED', line, flush=True)
    print(f'backfilled {built} of {len(wanted)}; refused {len(refused)}', flush=True)
    return 1 if refused and not built else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
