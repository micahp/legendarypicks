#!/usr/bin/env python3
"""monitor_ingest_freshness.py: is every registry job's table actually advancing?

`monitor_props_freshness.py` answers this for the three props providers by reading
`run_props_ingest.PROVIDERS`. Nothing answered it for anything else, which is how
`ingest_soccer_logs.py` ran never while every instrument read healthy: prod answered 200,
timers fired, tests passed, and MLS appearance rows had not moved since 2026-08-08.

This reads the `freshness` declarations in `ingest_registry.JOBS`, so a job cannot be added
without becoming checkable. It reports only and never starts an ingest.

Exit 1 on any stale target, any target whose table is missing, and any target that cannot be
evaluated. Evidence unavailable is a FAIL, never a pass and never a skip: a check that cannot
tell "clean" from "never ran" is the state the news collector sat in for its whole existence.
Say the zero, so a run that finds nothing wrong still prints every target it looked at.
"""
import datetime as dt
import os
import sqlite3
import sys

import ingest_registry

HERE = os.path.dirname(os.path.abspath(__file__))
ENVS = {
    "dev": os.path.join(HERE, "data", "picks.dev.db"),
    "prod": os.path.join(HERE, "data", "picks.db"),
}


def _parse_date(value):
    """A date column here is a game date (YYYY-MM-DD), not a capture timestamp."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _newest(con, target):
    where = target.get("where")
    sql = "SELECT max({}) FROM {}".format(target["date_column"], target["table"])
    if where:
        sql += " WHERE " + where
    return _parse_date(con.execute(sql).fetchone()[0])


def check(env, db_path, targets, today=None):
    """Return a list of (level, message). level is OK, INFO or ALERT."""
    today = today or dt.date.today()
    out = []
    if not os.path.isfile(db_path):
        return [("ALERT", "[{}] database missing, cannot check anything: {}".format(env, db_path))]
    try:
        con = sqlite3.connect("file:{}?mode=ro".format(db_path), uri=True, timeout=20)
    except sqlite3.Error as exc:
        return [("ALERT", "[{}] cannot open {}: {}".format(env, db_path, exc))]
    try:
        for target in targets:
            label = "{}/{}".format(target["job"], target["label"])
            try:
                newest = _newest(con, target)
            except sqlite3.Error as exc:
                # A missing table is not "fresh by default". It means the job has never
                # written anything here, which is the loudest version of stale.
                out.append(("ALERT", "[{}] {}: cannot read {} ({})".format(
                    env, label, target["table"], exc)))
                continue
            if newest is None:
                out.append(("ALERT", "[{}] {}: NO ROWS at all in {}".format(
                    env, label, target["table"])))
                continue
            age_h = (today - newest).days * 24
            threshold = target["stale_hours"]
            if age_h > threshold:
                out.append(("ALERT", "[{}] {} STALE: newest {} is {}, {}h old (threshold {}h)"
                            .format(env, label, target["date_column"], newest.isoformat(),
                                    age_h, threshold)))
            else:
                out.append(("OK", "[{}] {} fresh: newest {} ({}h, threshold {}h)".format(
                    env, label, newest.isoformat(), age_h, threshold)))
    finally:
        con.close()
    return out


def main(argv=None):
    ingest_registry.validate()
    targets = list(ingest_registry.freshness_targets())
    if not targets:
        print("ALERT: the registry declares no freshness targets at all", flush=True)
        return 1
    stale = 0
    for env, db_path in ENVS.items():
        for level, message in check(env, db_path, targets):
            print("{} {}".format(level, message), flush=True)
            if level == "ALERT":
                stale += 1
    print("Checked {} target(s) across {} environment(s): {} alert(s)".format(
        len(targets), len(ENVS), stale), flush=True)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
