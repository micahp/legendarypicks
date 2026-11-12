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


def adapt_historical_jsonl(source_path: Path, output_path: Path) -> dict:
    """Adapt externally audited records to the strict model JSONL contract.

    The V2 text parser alone cannot satisfy these gates. Every record must carry
    independent opportunity-denominator and official-record verification, plus
    stable source IDs and a source publication vintage. This function checks
    the declared audit evidence and model schema; it does not itself adjudicate
    gamebooks or turn parsed descriptions into verified labels.
    """
    source_path = source_path.expanduser().resolve(strict=True)
    output_path = output_path.expanduser().resolve()
    audit_path = output_path.with_name(output_path.name + ".audit.json")
    if output_path.exists() or audit_path.exists():
        raise FileExistsError(f"refusing to overwrite adapter output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    seen = set()
    evidence_rows = []
    with source_path.open("r", encoding="utf-8") as source, output_path.open("x", encoding="utf-8") as output:
        for line_no, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                evidence = doc.pop("audit_evidence")
                if evidence.get("official_record_verified") is not True:
                    raise ValueError("official_record_verified must be true")
                if evidence.get("opportunity_denominator_verified") is not True:
                    raise ValueError("opportunity_denominator_verified must be true")
                if not evidence.get("official_record_url"):
                    raise ValueError("official_record_url is required")
                if not evidence.get("source_row_id"):
                    raise ValueError("source_row_id is required")
                if evidence.get("source_text_disposition_only") is True:
                    raise ValueError("parsed text disposition is not official verification")
                context = Context(**doc.pop("context"))
                opportunity = Opportunity(context=context, **doc)
                opportunity.validate("9999-12-31T00:00:00+00:00")
                key = (context.phase, opportunity.opportunity_id)
                if key in seen:
                    raise ValueError(f"duplicate opportunity ID: {key}")
                seen.add(key)
                adapted = {
                    "context": context.__dict__,
                    "opportunity_id": opportunity.opportunity_id,
                    "game_kickoff_utc": opportunity.game_kickoff_utc,
                    "source_published_utc": opportunity.source_published_utc,
                    "outcome": opportunity.outcome,
                    "label_verified": opportunity.label_verified,
                    "foul_count": opportunity.foul_count,
                    "disposition": opportunity.disposition,
                }
                output.write(json.dumps(adapted, sort_keys=True) + "\n")
                evidence_rows.append({"opportunity_id": opportunity.opportunity_id,
                                      **evidence})
                count += 1
            except (ValueError, TypeError, KeyError) as exc:
                output_path.unlink(missing_ok=True)
                raise ValueError(f"{source_path}:{line_no}: historical adapter rejected row: {exc}") from exc
    if count == 0:
        output_path.unlink()
        raise ValueError("historical adapter produced zero verified opportunities")
    audit = {"status": "declared_audit_evidence_recorded_not_independently_adjudicated_by_adapter",
             "source_path": str(source_path), "source_sha256": sha256_file(source_path),
             "adapted_path": str(output_path), "adapted_sha256": sha256_file(output_path),
             "rows": count, "evidence": evidence_rows}
    with audit_path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(audit, sort_keys=True, indent=2) + "\n")
    return {"rows": count, "source_sha256": sha256_file(source_path),
            "output_sha256": sha256_file(output_path),
            "audit_manifest": str(audit_path),
            "interpretation": "Rows declared independently adjudicated and denominator-verified; adapter is not an adjudicator."}


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
    parser.add_argument("--train-jsonl", type=Path)
    parser.add_argument("--adapt-historical-jsonl", type=Path,
                        help="adapt independently audited source JSONL to model JSONL")
    parser.add_argument("--adapted-output", type=Path)
    parser.add_argument("--as-of-utc")
    parser.add_argument("--source-sha256")
    parser.add_argument("--model-out", type=Path)
    parser.add_argument("--holdout-jsonl", type=Path)
    parser.add_argument("--context-strength", type=float, default=30.)
    parser.add_argument("--team-strength", type=float, default=100.)
    args = parser.parse_args(argv)
    if args.adapt_historical_jsonl is not None:
        if args.train_jsonl is not None or args.adapted_output is None:
            parser.error("--adapt-historical-jsonl requires --adapted-output and excludes --train-jsonl")
        print(json.dumps(adapt_historical_jsonl(args.adapt_historical_jsonl,
                                                args.adapted_output), indent=2, sort_keys=True))
        return
    if (args.train_jsonl is None or args.adapted_output is not None
            or args.as_of_utc is None or args.source_sha256 is None or args.model_out is None):
        parser.error("training requires --train-jsonl, --as-of-utc, --source-sha256, and --model-out")
    result = train(train_jsonl=args.train_jsonl, as_of_utc=args.as_of_utc,
                   source_sha256=args.source_sha256, model_out=args.model_out,
                   holdout_jsonl=args.holdout_jsonl,
                   context_strength=args.context_strength,
                   team_strength=args.team_strength)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
