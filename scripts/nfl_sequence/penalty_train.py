#!/usr/bin/env python3
"""Offline V1.7 penalty fit/evaluation from the verified opportunity-level contract.

Input JSONL is deliberately *not* the raw nflverse PBP/penalty flag extract:
the data agent must supply all denominators, including verified no-foul
opportunities, and resolve single-foul dispositions before model fitting.

This command neither simulates nor enforces a penalty.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from penalty_fit import Context, Opportunity, PenaltyModel


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def opportunities_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                context = Context(**doc.pop("context"))
                yield Opportunity(context=context, **doc)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"{path}:{line_no}: invalid verified opportunity: {exc}") from exc


def train(*, train_jsonl: Path, as_of_utc: str, source_sha256: str, model_out: Path,
          holdout_jsonl: Path | None = None, context_strength: float = 30.,
          team_strength: float = 100.) -> dict:
    """Train without mutating inputs or overwriting an existing release artifact."""
    model_out = model_out.expanduser().resolve()
    manifest_path = model_out.with_name(model_out.name + ".manifest.json")
    if model_out.exists() or manifest_path.exists():
        raise FileExistsError("model or manifest already exists; choose another output path")
    train_jsonl = train_jsonl.expanduser().resolve(strict=True)
    train_input_sha256 = sha256_file(train_jsonl)
    model = PenaltyModel(
        train_before_utc=as_of_utc, source_sha256=source_sha256,
        context_strength=context_strength, team_strength=team_strength,
        team_effects=True).fit(opportunities_jsonl(train_jsonl))
    evidence = {
        "status": "research_only_not_release_validated",
        "model_schema": "lp.slc.penalty-occurrence.v1",
        "train_input_path": str(train_jsonl),
        "train_input_sha256": train_input_sha256,
        "source_manifest_sha256": source_sha256,
        "train_before_utc": as_of_utc,
        "observed_opportunities": model.opportunities,
        "model_sha256": model.sha256(),
        "validation": None,
    }
    if holdout_jsonl is not None:
        holdout_jsonl = holdout_jsonl.expanduser().resolve(strict=True)
        baseline = PenaltyModel(
            train_before_utc=as_of_utc, source_sha256=source_sha256,
            context_strength=context_strength, team_strength=team_strength,
            team_effects=False).fit(opportunities_jsonl(train_jsonl))
        evidence["validation"] = {
            "holdout_input_path": str(holdout_jsonl),
            "holdout_input_sha256": sha256_file(holdout_jsonl),
            "team_adjusted": model.score(opportunities_jsonl(holdout_jsonl)),
            "context_only_control": baseline.score(opportunities_jsonl(holdout_jsonl)),
        }
    model_out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive-create both outputs; never overwrite a previous frozen candidate.
    with model_out.open("x", encoding="utf-8") as handle:
        handle.write(model.to_json() + "\n")
    with manifest_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--as-of-utc", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--model-out", type=Path, required=True)
    parser.add_argument("--holdout-jsonl", type=Path)
    parser.add_argument("--context-strength", type=float, default=30.)
    parser.add_argument("--team-strength", type=float, default=100.)
    args = parser.parse_args(argv)
    result = train(train_jsonl=args.train_jsonl, as_of_utc=args.as_of_utc,
                   source_sha256=args.source_sha256, model_out=args.model_out,
                   holdout_jsonl=args.holdout_jsonl,
                   context_strength=args.context_strength,
                   team_strength=args.team_strength)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
