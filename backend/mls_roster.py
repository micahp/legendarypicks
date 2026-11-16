"""One MLS roster cycle: complete squads in, identity writes and one membership snapshot out, in one transaction.

Order inside the transaction:
1. Refuse if the squads are incomplete (nothing is written, the current snapshot stays).
2. Onboard: create, bind, rekey, or queue every publisher key that is not bound yet (mls_identity).
3. Build the membership snapshot from the binds as they now stand (mls_snapshot).
4. Publish it, or refuse. Refusal rolls back the onboarding writes too.

An exception at any point rolls the whole cycle back. The last valid snapshot is never superseded by a partial write.
"""
from dataclasses import dataclass, field
from typing import List, Optional

import mls_identity
import mls_snapshot as ms


@dataclass
class Cycle:
    status: str  # "publish" or "refused"
    outcome: str  # "published", "unchanged" or "refused"
    result: Optional[ms.Result] = None
    reasons: List[str] = field(default_factory=list)
    onboarded: List[int] = field(default_factory=list)
    rekeyed: List[dict] = field(default_factory=list)
    queued: List[dict] = field(default_factory=list)
    snapshot_id: Optional[int] = None


def run_cycle(con, squads, captured_at, lookup=None):
    """Run one complete MLS cycle. `lookup(source, key)` returns the publisher's dates of birth for a key."""
    mls_identity.ensure_schema(con)
    prior = ms.prior_state(con)
    reasons = ms.check_completeness(squads, prior["counts"] if prior else None)
    if reasons:
        return Cycle(status="refused", outcome="refused", reasons=reasons)

    if con.in_transaction:
        con.commit()
    con.execute("BEGIN IMMEDIATE")
    try:
        onboarding = mls_identity.onboard(con, squads, lookup, captured_at)
        result = ms.build(con, squads, ms.binds_from_db(con), captured_at=captured_at,
                          rekeyed=onboarding["rekeyed"])
        if result.status != "publish":
            con.execute("ROLLBACK")
            return Cycle(status="refused", outcome="refused", reasons=result.reasons)
        outcome, snapshot_id = ms.publish(con, result, captured_at)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return Cycle(status="publish", outcome=outcome, result=result, reasons=[],
                 onboarded=onboarding["created"], rekeyed=onboarding["rekeyed"],
                 queued=onboarding["queued"], snapshot_id=snapshot_id)
