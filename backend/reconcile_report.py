#!/usr/bin/env python3
"""The reconcile report: checks plus the per-(league, season) coverage verdict.

Extracted from reconcile_totals.py 2026-08-08 (monolith split). Standalone —
no sibling imports. No behavior change.
"""
from typing import Dict, List, Optional, Tuple

class Report:
    """Checks, plus a per-(league, season) verdict the coverage registry can store.

    The verdict is deliberately three-valued and deliberately not derivable from a
    count of passes. `unverified` is what an unreachable oracle produces, and it is
    NOT the same as `partial`: one says our data disagrees with the publisher, the
    other says nobody knows. Collapsing them is how "evidence unavailable" gets read
    as green.
    """

    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str, str]] = []
        self.failed = 0
        self.current: Optional[Tuple[str, int]] = None
        self.scopes: Dict[Tuple[str, int], Dict[str, int]] = {}

    def _tally(self, outcome: str) -> None:
        if self.current is None:
            return
        self.scopes.setdefault(
            self.current, {"pass": 0, "mismatch": 0, "no_oracle": 0}
        )[outcome] += 1

    def scope(self, league: str, season: int) -> None:
        self.current = (league, season)
        self.scopes.setdefault(
            self.current, {"pass": 0, "mismatch": 0, "no_oracle": 0}
        )

    def verdict(self, league: str, season: int) -> str:
        tally = self.scopes.get((league, season))
        if not tally or not any(tally.values()):
            return "unverified"           # nothing ran; never good
        if tally["no_oracle"]:
            return "unverified"           # evidence unavailable is not evidence of health
        if tally["mismatch"]:
            return "partial"
        return "complete"

    def check(self, name: str, ours: int, theirs: int, note: str = "") -> None:
        ok = ours == theirs
        if not ok:
            self.failed += 1
        self._tally("pass" if ok else "mismatch")
        delta = "" if ok else f"  ({ours - theirs:+d})"
        self.rows.append(
            ("PASS" if ok else "MISMATCH", name, f"ours={ours} published={theirs}{delta}", note)
        )

    def unreachable(self, name: str, why: str) -> None:
        self.failed += 1
        self._tally("no_oracle")
        self.rows.append(("NO-ORACLE", name, "expected total unavailable", why))

    def note(self, name: str, text: str) -> None:
        self.rows.append(("INFO", name, text, ""))

    def render(self) -> str:
        width = max((len(r[1]) for r in self.rows), default=0)
        lines = []
        for status, name, detail, note in self.rows:
            line = f"{status:<10} {name:<{width}}  {detail}"
            if note:
                line += f"   [{note}]"
            lines.append(line)
        return "\n".join(lines)
