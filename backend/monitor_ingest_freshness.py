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


def _parse_when(value):
    """Accept a game date (YYYY-MM-DD) or a full timestamp, and keep the precision.

    Settlement lag is measured in hours, not days: "nothing has settled for 6 hours" is the
    finding, and a date-only comparison cannot see it. A bare date is read as the START of
    that day, so a stale date can only ever be reported as older than it is, never fresher.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            when = dt.datetime.combine(dt.date.fromisoformat(text[:10]), dt.time.min)
        except ValueError:
            return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when


def _newest(con, target):
    where = target.get("where")
    sql = "SELECT max({}) FROM {}".format(target["date_column"], target["table"])
    if where:
        sql += " WHERE " + where
    return _parse_when(con.execute(sql).fetchone()[0])


def check(env, db_path, targets, now=None):
    """Return a list of (level, message). level is OK, INFO or ALERT."""
    now = now or dt.datetime.now(dt.timezone.utc)
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
            age_h = (now - newest).total_seconds() / 3600.0
            threshold = target["stale_hours"]
            if age_h > threshold:
                out.append(("ALERT", "[{}] {} STALE: newest {} is {}, {:.1f}h old "
                            "(threshold {}h)".format(env, label, target["date_column"],
                                                     newest.isoformat(), age_h, threshold)))
            else:
                out.append(("OK", "[{}] {} fresh: newest {} ({:.1f}h, threshold {}h)".format(
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
