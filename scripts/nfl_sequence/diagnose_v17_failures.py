"""Inspect preserved, immutable V1.7 failure envelopes; never re-run simulations.

Input: research report's v1.7-1000-pr43-errors.jsonl.gz.
Output: a compact aggregate and a per-seed diagnostics table, preserving exact
exception messages and the offending decision/state without guessing causes.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path


def iter_records(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for row in stream:
            if row.strip():
                yield json.loads(row)


def flatten(value, prefix="", depth=0):
    if depth > 6:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                yield from flatten(v, p, depth + 1)
            elif any(word in k.lower() for word in
                     ("message", "error", "reason", "failure", "blocker",
                      "class", "type", "decision", "outcome", "event", "terminal", "ruling")):
                yield p, str(v)[:500]
    elif isinstance(value, list):
        for i, item in enumerate(value[:8]):
            yield from flatten(item, f"{prefix}[{i}]", depth + 1)


def diagnostic(row):
    outcome = row.get("outcome") or {}
    failure = row.get("assertion_failure") or outcome.get("assertion_failure") or {}
    unresolved = row.get("unresolved_transition") or outcome.get("unresolved_transition") or {}
    d = {
        "seed": row.get("seed"),
        "status": outcome.get("status"),
        "blocker": outcome.get("blocker"),
        "error": outcome.get("error"),
        "boxscore_error": str(outcome.get("boxscore_error") or "")[:1500],
        "failure_class": failure.get("failure_class") or failure.get("class"),
        "failure_message": failure.get("message") or failure.get("error"),
        "play_index": failure.get("play_index"),
        "decision": failure.get("decision"),
        "state_before": failure.get("state_before"),
        "state_after": failure.get("state_after"),
        "offending_outcome": failure.get("outcome"),
        "unresolved_reason": unresolved.get("reason") or unresolved.get("blocker"),
        "failing_record": row.get("failed_record") or outcome.get("failed_record"),
        "interesting_fields": dict(list(flatten(
            {"failure": failure, "unresolved": unresolved}))[:34]),
    }
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--errors", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    records = list(iter_records(args.errors))
    manifest = records[0]
    rows = [diagnostic(r) for r in records[1:]]
    if len(rows) != 47 or len({x["seed"] for x in rows}) != 47:
        raise ValueError(f"expected 47 distinct errors; got {len(rows)}")
    by_status = Counter(x["status"] for x in rows)
    by_blocker = Counter(x["blocker"] for x in rows)
    by_class = Counter(x["failure_class"] for x in rows)
    messages = Counter()
    samples = defaultdict(list)
    for row in rows:
        event = row.get("offending_outcome")
        errmsg = (row.get("error") or row.get("failure_message") or
                  (event.get("message") if isinstance(event, dict) else None) or
                  row.get("boxscore_error") or row.get("unresolved_reason") or "")
        signature = str(errmsg).split(" source_artifact_hashes=", 1)[0][:200]
        messages[signature] += 1
        if len(samples[signature]) < 5:
            samples[signature].append(row["seed"])
    summary = {
        "source_manifest": {k: manifest.get(k) for k in
                            ("record_type", "run_id", "failure_record_count", "configuration_hash")},
        "count": len(rows),
        "status": dict(by_status), "blockers": dict(by_blocker),
        "failure_classes": dict(by_class),
        "error_signatures": [
            {"count": n, "seeds": samples[k], "signature": k}
            for k, n in messages.most_common()],
        "seeds": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print("SAVED_RECORD_KEYS", list(records[1]))
    print("FAILURE_ENVELOPE_KEYS", list((records[1].get("assertion_failure") or {}).keys()))
    print("FIRST_RECORD_CONTEXT", json.dumps({k: v for k, v in records[1].items()
          if k not in ("assertion_failure", "unresolved_transition", "failed_record", "boxscore")},
          default=str)[:4000])
    print("TOTAL", len(rows))
    print("STATUS", dict(by_status))
    print("BLOCKERS", dict(by_blocker))
    print("CLASSES", dict(by_class))
    print("SIGNATURES", json.dumps(summary["error_signatures"], indent=2))
    for row in rows:
        # Printing compact diagnostics lets reviewers inspect the actual seed
        # envelope through the immutable CI log without downloading artifacts.
        cause = row.get("offending_outcome")
        cause = cause.get("message") if isinstance(cause, dict) else str(cause or "")
        cause = cause or ""
        before = row.get("state_before")
        after = row.get("state_after")
        print("SEED", json.dumps({
            "seed": row["seed"], "failure_class": row["failure_class"],
            "play_index": row["play_index"], "cause": cause[:470],
            "before": str(before)[:330], "after": str(after)[:330],
            "blocker": row["blocker"], "unresolved": row["unresolved_reason"]
        }, default=str)[:1250])


if __name__ == "__main__":
    main()
