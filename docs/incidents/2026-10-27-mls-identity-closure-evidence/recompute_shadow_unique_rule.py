"""Re-apply the production date-of-birth rule to a saved live shadow report. Offline: no publisher is contacted.

Usage: python recompute_shadow_unique_rule.py SHADOW_REPORT.json OUT.json

Each known-record check in the report already holds the live readings from both publishers. This applies
mls_identity.corroborated_dob to those readings and compares the result with the audit's expectation.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, "..", "..", "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))

import mls_identity  # noqa: E402


def main(argv):
    report = json.load(open(argv[1]))
    rows = []
    for c in report["checks"]:
        mls = sorted(set(c["live_mls_dates"]))
        fotmob = sorted(set(c["live_fotmob_dates"]))
        dob, reason = mls_identity.corroborated_dob(mls, fotmob)
        expected = c["audit_status"] in ("supported", "supported_order_unresolved")
        rows.append({"player_id": c["player_id"], "audit_status": c["audit_status"], "live_mls_dates": mls,
                     "live_fotmob_dates": fotmob, "accepted_dob": dob, "reason": reason,
                     "agrees_with_audit": (dob is not None) == expected})
    out = {"source_report": os.path.basename(argv[1]), "sample": len(rows),
           "accepted": sum(1 for r in rows if r["accepted_dob"] is not None),
           "agree_with_audit": sum(1 for r in rows if r["agrees_with_audit"]),
           "reasons": dict(collections.Counter(r["reason"] or "accepted" for r in rows)),
           "disagreements": [r for r in rows if not r["agrees_with_audit"]],
           "checks": rows}
    with open(argv[2], "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print(json.dumps({k: out[k] for k in ("sample", "accepted", "agree_with_audit", "reasons")}, indent=1))


if __name__ == "__main__":
    main(sys.argv)
