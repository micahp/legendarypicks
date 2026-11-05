#!/usr/bin/env python3
"""Build one matchup snapshot and run its news and starter checks, writing every output to one directory.

Steps:
1. pregame_snapshot.build for the game, at the cutoff, with the verified kickoff supplied (the build refuses a same-day
   cutoff unless a kickoff is verified).
2. news_evidence.build from the raw captures acquired at or before the cutoff, bound to the snapshot.
3. starter_consistency.check: announced starters in the news against the snapshot's depth rank 1.

Writes snapshot.json, evidence.json and summary.txt. The summary lists every count, including zeros. Nothing is written to
the database. Run it again at the cutoff to freeze the inputs, since the database and captures keep changing until then.

Usage: build_matchup_snapshot.py --db PATH --capture-dir DIR --game GAME_ID --as-of UTC --kickoff-utc UTC
                                 --kickoff-source-url URL --out-dir DIR [--evaluation exploratory_replay]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import news_evidence
import pregame_snapshot
import source_preflight
import starter_consistency


CUTOFF_BEFORE_KICKOFF = timedelta(minutes=90)


def cutoff_for(kickoff_utc):
    """The pregame cutoff: 90 minutes before the verified kickoff."""
    return datetime.fromisoformat(kickoff_utc.replace('Z', '+00:00')) - CUTOFF_BEFORE_KICKOFF


def status_for(now, cutoff):
    """PREVIEW until the cutoff has passed. Only a build run at or after the cutoff may be called a cutoff snapshot."""
    if now < cutoff:
        return f'PREVIEW: the cutoff is {cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")}; inputs can still change until then'
    return f'CUTOFF SNAPSHOT: built at {now.strftime("%Y-%m-%dT%H:%M:%SZ")}, after the cutoff'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    ap.add_argument('--capture-dir', required=True)
    ap.add_argument('--game', required=True)
    ap.add_argument('--as-of', required=True)
    ap.add_argument('--kickoff-utc', required=True)
    ap.add_argument('--kickoff-source-url', required=True)
    ap.add_argument('--evaluation', default='exploratory_replay')
    ap.add_argument('--out-dir', required=True)
    a = ap.parse_args(argv)
    cutoff = cutoff_for(a.kickoff_utc)
    as_of = datetime.fromisoformat(a.as_of.replace('Z', '+00:00'))
    if as_of != cutoff:
        raise SystemExit(f'--as-of {a.as_of} must be the cutoff, 90 minutes before the kickoff: '
                         f'{cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")}')
    status = status_for(datetime.now(timezone.utc), cutoff)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    snapshot = pregame_snapshot.build(a.db, a.game, a.as_of, kickoff_utc=a.kickoff_utc,
                                      kickoff_source_url=a.kickoff_source_url, evaluation=a.evaluation)
    (out / 'snapshot.json').write_text(json.dumps(snapshot, indent=1, sort_keys=True) + '\n')
    (out / 'status.txt').write_text(status + '\n')

    args = argparse.Namespace(db=a.db, news_evidence_dir=a.capture_dir, roster_snapshot=None,
                              availability_snapshot=None, availability_store=None)
    try:
        evidence = source_preflight.validate_news_evidence(args, snapshot)
    except source_preflight.PreflightError as exc:
        (out / 'summary.txt').write_text(f'{status}\nREFUSED\n{exc}\n')
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 2
    (out / 'evidence.json').write_text(json.dumps(evidence, indent=1, sort_keys=True, default=str) + '\n')

    rosters = {side: snapshot['rosters'][side]['team'] for side in ('away', 'home')}
    summary = [status,
               f'game {a.game}; as of {a.as_of}; kickoff {a.kickoff_utc}; evaluation {snapshot["evaluation"]}',
               f'snapshot sha256 {snapshot["snapshot_sha256"]}',
               f'teams {rosters["away"]} (away) and {rosters["home"]} (home)',
               f'news evidence sha256 {evidence["evidence_sha256"]}; items {len(evidence["items"])}',
               starter_consistency.summary_line(evidence['starter_consistency'])]
    summary += [f"  depth rank 1 {key[0]} {key[1]}: {player['player_name']} (gsis {player['gsis_id']})"
                for key, player in sorted(starter_consistency.depth_rank_one(snapshot).items())]
    (out / 'summary.txt').write_text('\n'.join(summary) + '\n')
    print('\n'.join(summary))
    return 0


if __name__ == '__main__':
    sys.exit(main())
