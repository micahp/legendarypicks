"""zombie_fix_assertions.py — targeted proof of the freshness-gated live-evidence fix.

Runnable:  cd backend && venv/bin/python routers/esports/zombie_fix_assertions.py

Unit-asserts _derive_state (from slate_state.py) directly with synthetic evidence — the couple
of assertions that prove the zombie-live fix and its winner-resolution, without a big sim harness.
Covers the exact live case (Prestige v Vasteras: stale GRID started&&!finished, no other source)
plus the branches that prove FRESH live survives and a demoted zombie WITH a result resolves to it.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # backend/ on path for `routers` pkg
from routers.esports import slate_state as sl  # noqa: E402
NOW = 1_800_000_000_000  # fixed reference now (ms)
MIN = 60 * 1000
H = 60 * MIN
S_LIVE, S_FIN, S_SCHED, S_UNK = sl.S_LIVE, sl.S_FINISHED, sl.S_SCHEDULED, sl.S_ENDED_UNKNOWN


def grid(started=True, finished=False, age_min=None, won=None):
    """A GRID evidence entry; age_min = how stale its updatedAt is (None => no timestamp)."""
    return {"started": started, "finished": finished, "winner": won,
            "updatedAtMs": (NOW - age_min * MIN) if age_min is not None else None}


def state(ev, start_off_h=None, bov_live=False, finishedAt=None):
    row = {"startTime": (NOW - start_off_h * H) if start_off_h is not None else None,
           "_bov_live": bov_live, "finishedAt": finishedAt}
    return sl._derive_state(row, ev, NOW)


CASES = [
    # (label, expected, ev, kwargs)
    # THE BUG: stale GRID started&&!finished, +4.5h past start, no other source -> NOT live.
    ("zombie: stale GRID (229m), no result -> ENDED_UNKNOWN",
     S_UNK, {"grid": grid(age_min=229)}, dict(start_off_h=4.5)),
    # FRESH GRID live must survive (no false demotion in a real match / map break).
    ("real live: fresh GRID (3m) -> LIVE",
     S_LIVE, {"grid": grid(age_min=3)}, dict(start_off_h=1.0)),
    ("real live: GRID stale 20m but < 30m threshold -> LIVE",
     S_LIVE, {"grid": grid(age_min=20)}, dict(start_off_h=0.8)),
    # Demoted zombie WITH a Kalshi settlement -> resolves to FINISHED (freshness UNBLOCKS Kalshi).
    ("demoted zombie + Kalshi winner -> FINISHED (real result)",
     S_FIN, {"grid": grid(age_min=200), "kalshi": "a"}, dict(start_off_h=5.0)),
    # Explicit finish always wins over a stale-live signal.
    ("GRID finished flag -> FINISHED even if stale",
     S_FIN, {"grid": grid(finished=True, age_min=120)}, dict(start_off_h=3.0)),
    ("PS finished -> FINISHED though GRID still started&&!finished (lag)",
     S_FIN, {"grid": grid(age_min=5), "ps": {"finished": True, "live": False}}, dict(start_off_h=2.0)),
    # Hard cap: NOTHING is live past 6h, even a source that still claims running.
    ("hard cap: PS running but +7h past start -> NOT live (ENDED_UNKNOWN)",
     S_UNK, {"ps": {"live": True, "finished": False}}, dict(start_off_h=7.0)),
    ("hard cap: fresh GRID but +6.5h -> NOT live",
     S_UNK, {"grid": grid(age_min=2)}, dict(start_off_h=6.5)),
    # Kalshi must NOT kill a genuinely-live match (fuzzy same-pair rematch guard).
    ("Kalshi winner but FRESH GRID live -> stays LIVE",
     S_LIVE, {"grid": grid(age_min=4), "kalshi": "b"}, dict(start_off_h=1.0)),
    # Stale bovada-only live flag on an old match -> demoted; within-window bov flag -> LIVE.
    ("bov_live only, +5h, no PS -> demoted (ENDED_UNKNOWN)",
     S_UNK, {}, dict(start_off_h=5.0, bov_live=True)),
    ("bov_live only, +1h (within window), no PS -> LIVE",
     S_LIVE, {}, dict(start_off_h=1.0, bov_live=True)),
    # Future / just-started scheduling unaffected.
    ("future start, no evidence -> SCHEDULED",
     S_SCHED, {}, dict(start_off_h=-0.5)),
    # No-timestamp GRID (older grid.py): don't manufacture a zombie past start.
    ("GRID started&&!finished, NO updatedAt, +3h past -> NOT live",
     S_UNK, {"grid": grid(age_min=None)}, dict(start_off_h=3.0)),
    ("GRID started&&!finished, NO updatedAt, just started -> LIVE",
     S_LIVE, {"grid": grid(age_min=None)}, dict(start_off_h=0.1)),
]

if __name__ == "__main__":
    fails = 0
    for label, expected, ev, kw in CASES:
        got = state(ev, **kw)
        ok = got == expected
        fails += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {label:60} -> {got}"
              + ("" if ok else f"  (expected {expected})"))
    print(f"\n{len(CASES)-fails}/{len(CASES)} passed")
    sys.exit(1 if fails else 0)
