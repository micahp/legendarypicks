#!/usr/bin/env python3
"""Build one matchup's frozen inputs and write them into the repository.

Everything is built in a temporary directory, from one clean commit, and then copied into --out-dir with a MANIFEST.json
that lists the SHA-256 of every file. The steps are:

1. News: export every stored RotoWire payload acquired strictly before the cutoff from the database's raw store.
2. Starters: run the 28-starter builder on the nflverse depth chart and roster, with a provenance file that pins both.
3. Full roster: run the full-depth roster builder on the starters, with its own provenance.
4. Snapshot: build the matchup snapshot at the cutoff, apply the pinned roster, and run the news and starter check
   on that same snapshot. A conflict or an unverifiable check stops the freeze.

Refusals, none of which are overridden:
- the cutoff must be 90 minutes before the verified kickoff;
- the repository must have no uncommitted changes (the full-depth builder records and requires a clean tree);
- nflverse artifacts must have been published at or before the cutoff;
- an existing frozen output (status CUTOFF) is never overwritten.

Until the cutoff has passed, the output is labelled PREVIEW.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import build_matchup_snapshot as bms
import export_news_captures
import pregame_snapshot
import source_preflight
import starter_consistency

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
STARTER_BUILDER = REPO / 'backend' / 'build_nfl_starters_snapshot.py'
FULL_BUILDER = HERE / 'build_full_depth_roster_snapshot.py'
STARTER_BUILDER_PIN = {
    'repository': 'micahp/legendarypicks',
    'branch': 'feat/nfl-roster-full-depth-2026-10-26',
    'commit': '4ee931a4379567978d87491b3c0e4ae55055b8b9',
    'file': 'backend/build_nfl_starters_snapshot.py',
    'file_sha256': '7fe1923608c5bd72396fe3dff52020a9df9697d97935959a8f32cd727060738e',
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True).strip()


def run(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f'step failed: {" ".join(command)}\n{result.stdout}{result.stderr}')
    return result.stdout


def parse_utc(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(timezone.utc)


def build(args, tmp):
    tmp = Path(tmp)
    inputs = tmp / 'inputs'
    inputs.mkdir()
    artifacts = []
    for label, source, url, published in (
            ('depth_charts', args.depth_parquet, args.depth_url, args.depth_last_modified),
            ('roster_weekly', args.roster_parquet, args.roster_url, args.roster_last_modified)):
        target = inputs / Path(source).name
        shutil.copy(source, target)
        if parse_utc(published) > args.cutoff:
            raise SystemExit(f'{label} was published after the cutoff; it cannot be frozen')
        artifacts.append({'name': target.name, 'sha256': sha256(target), 'last_modified_utc': published, 'url': url,
                          'role': label})
    depth, roster = inputs / Path(args.depth_parquet).name, inputs / Path(args.roster_parquet).name

    captures = tmp / 'news-captures'
    exported = export_news_captures.export(args.db, args.cutoff, captures)

    if sha256(STARTER_BUILDER) != STARTER_BUILDER_PIN['file_sha256']:
        raise SystemExit('the starter builder file does not match its pinned hash')
    starters = tmp / 'starters.json'
    run([sys.executable, str(STARTER_BUILDER), str(depth), '--away', args.away, '--home', args.home,
         '--roster', str(roster), '--db', args.db, '--out', str(starters)])
    starters_prov = tmp / 'starters_provenance.json'
    starters_prov.write_text(json.dumps({
        'builder': STARTER_BUILDER_PIN, 'source_artifacts': artifacts,
        'output': {'sha256': sha256(starters), 'file': starters.name}}, indent=1, sort_keys=True) + '\n')

    full = tmp / 'full_depth_roster.json'
    full_prov = tmp / 'full_depth_provenance.json'
    run([sys.executable, str(FULL_BUILDER), '--depth-charts', str(depth), '--roster', str(roster),
         '--starter-snapshot', str(starters), '--starter-provenance', str(starters_prov), '--db', args.db,
         '--out', str(full), '--provenance-out', str(full_prov), '--jersey-week', str(args.jersey_week)])

    snapshot = pregame_snapshot.build(args.db, args.game, args.as_of, kickoff_utc=args.kickoff_utc,
                                      kickoff_source_url=args.kickoff_source_url, evaluation=args.evaluation)
    pregame_snapshot.apply_full_depth_roster_snapshot(snapshot, str(full), str(full_prov))
    check_args = argparse.Namespace(db=args.db, news_evidence_dir=str(captures), roster_snapshot=str(full),
                                    availability_snapshot=None, availability_store=None)
    evidence = source_preflight.validate_news_evidence(check_args, snapshot)

    (tmp / 'snapshot.json').write_text(json.dumps(snapshot, indent=1, sort_keys=True) + '\n')
    (tmp / 'evidence.json').write_text(json.dumps(evidence, indent=1, sort_keys=True, default=str) + '\n')
    return exported, snapshot, evidence


def write_outputs(tmp, out, status, args, exported, snapshot, evidence, commit):
    tmp = Path(tmp)
    summary = [status,
               f'game {args.game}; cutoff {args.cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")}; kickoff {args.kickoff_utc}',
               f'repository commit {commit}',
               f'snapshot sha256 {snapshot["snapshot_sha256"]}',
               f'evidence sha256 {evidence["evidence_sha256"]}; news payloads exported {len(exported)}',
               starter_consistency.summary_line(evidence['starter_consistency'])]
    (tmp / 'summary.txt').write_text('\n'.join(summary) + '\n')
    (tmp / 'status.txt').write_text(status + '\n')
    files = sorted(p for p in tmp.rglob('*') if p.is_file() and p.name != 'MANIFEST.json')
    manifest = {
        'status': status, 'game': args.game, 'cutoff_utc': args.cutoff.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'kickoff_utc': args.kickoff_utc, 'kickoff_source_url': args.kickoff_source_url,
        'built_from_commit': commit, 'evaluation': snapshot.get('evaluation'),
        'snapshot_sha256': snapshot['snapshot_sha256'], 'evidence_sha256': evidence['evidence_sha256'],
        'news_payloads': exported,
        'files': {str(p.relative_to(tmp)): sha256(p) for p in files},
    }
    (tmp / 'MANIFEST.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    out = Path(out)
    if out.exists():
        previous = out / 'MANIFEST.json'
        if previous.exists() and json.loads(previous.read_text())['status'].startswith('CUTOFF'):
            raise SystemExit(f'{out} holds a frozen CUTOFF output; it is never overwritten')
        shutil.rmtree(out)
    shutil.copytree(tmp, out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True)
    ap.add_argument('--game', required=True)
    ap.add_argument('--kickoff-utc', required=True)
    ap.add_argument('--kickoff-source-url', required=True)
    ap.add_argument('--depth-parquet', required=True)
    ap.add_argument('--depth-url', required=True)
    ap.add_argument('--depth-last-modified', required=True)
    ap.add_argument('--roster-parquet', required=True)
    ap.add_argument('--roster-url', required=True)
    ap.add_argument('--roster-last-modified', required=True)
    ap.add_argument('--away', required=True)
    ap.add_argument('--home', required=True)
    ap.add_argument('--jersey-week', type=int, default=9)
    ap.add_argument('--evaluation', default='exploratory_replay')
    ap.add_argument('--out-dir', required=True)
    a = ap.parse_args(argv)

    kickoff = parse_utc(a.kickoff_utc)
    a.cutoff = bms.cutoff_for(a.kickoff_utc)
    a.as_of = a.cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')
    if git('status', '--porcelain'):
        raise SystemExit('the repository has uncommitted changes; commit them, then freeze from the clean commit')
    commit = git('rev-parse', 'HEAD')
    status = bms.status_for(datetime.now(timezone.utc), a.cutoff)
    if kickoff <= a.cutoff:
        raise SystemExit('the cutoff must be before the kickoff')

    tmp = tempfile.mkdtemp(prefix='freeze-')
    try:
        exported, snapshot, evidence = build(a, tmp)
        out = write_outputs(tmp, a.out_dir, status, a, exported, snapshot, evidence, commit)
    except source_preflight.PreflightError as exc:
        print(f'FREEZE REFUSED: {exc}', file=sys.stderr)
        return 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'{status}\nwrote {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
