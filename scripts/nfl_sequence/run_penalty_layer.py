#!/usr/bin/env python3
"""Draw a research penalty proposal from the fitted V1.7 layer.

This runs one isolated opportunity, not a full game or an enforcement ruling.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from penalty_fit import Context
from penalty_sampler import PenaltySampler

RESEARCH = Path(__file__).resolve().parents[2] / 'docs/research/slc-v17-penalty-fit-2026-11-13'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', type=Path, default=RESEARCH / 'model.json')
    ap.add_argument('--fit-manifest', type=Path, default=RESEARCH / 'fit-manifest.json')
    ap.add_argument('--source-manifest', type=Path, default=RESEARCH / 'source-manifest.json')
    ap.add_argument('--as-of-utc', required=True)
    ap.add_argument('--season', type=int, required=True)
    ap.add_argument('--offense', required=True)
    ap.add_argument('--defense', required=True)
    ap.add_argument('--down', type=int, required=True)
    ap.add_argument('--to-go', type=int, required=True)
    ap.add_argument('--yardline-100', type=int, required=True)
    ap.add_argument('--phase', choices=('pre_snap', 'live_ball'), required=True)
    ap.add_argument('--play-class', choices=('pre_snap', 'run', 'dropback', 'kick'), required=True)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--opportunity-key', required=True)
    args = ap.parse_args()
    sampler = PenaltySampler.from_artifacts(
        model_path=args.model, manifest_path=args.fit_manifest,
        source_manifest_path=args.source_manifest, as_of_utc=args.as_of_utc)
    context = Context(phase=args.phase, rule_era=args.season, offense_team=args.offense,
                      defense_team=args.defense, down=args.down, to_go=args.to_go,
                      yardline_100=args.yardline_100, play_class=args.play_class)
    proposal = sampler.propose(context, game_seed=args.seed, opportunity_key=args.opportunity_key)
    print(json.dumps({'scope': 'research_proposal_only', 'context': asdict(context),
                      'provenance': sampler.model_provenance,
                      'probabilities': sampler.model.predict(context),
                      'proposal': asdict(proposal)}, indent=2, sort_keys=True))

if __name__ == '__main__':
    main()
