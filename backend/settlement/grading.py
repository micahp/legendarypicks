#!/usr/bin/env python3
"""grading.py — write one numeric actual to prop_results."""
import sqlite3


def _grade_actual(con: sqlite3.Connection, prop, actual: float, now: str) -> bool:
    """Write one numeric actual. Return False when the prop side is unsupported."""
    line = prop["line"]
    side = (prop["side"] or "").lower()
    if side == "over":
        hit = 1 if actual > line else (0 if actual < line else None)
    elif side == "under":
        hit = 1 if actual < line else (0 if actual > line else None)
    else:
        return False
    con.execute(
        "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) VALUES (?,?,?,?)",
        (prop["id"], actual, hit, now))
    return True
