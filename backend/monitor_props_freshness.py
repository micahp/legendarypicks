#!/usr/bin/env python3
"""
monitor_props_freshness.py — guard against props data silently dropping off.

Prod once went 8 days stale because nothing was feeding it AND nothing noticed. This checks each
environment's most-recent prop capture; if it's older than the threshold it logs a loud ALERT and
exits non-zero so the systemd timer records a failure. It deliberately does **not** start a props
ingest service while scheduled props work is disabled: a self-healer must not bypass league-source
policy or revive a prohibited World Cup sweep.

Add an env to ENVS the moment it is supposed to be fed (prod → enable at deploy, once prod has its
own ingest service).
"""
import sys, json, urllib.request, datetime as dt

STALE_HOURS = 3.0  # ingest runs every 30 min; >3h without a fresh capture = something is wrong

# env -> backend base url. Re-enabling a props ingest is a separate, explicit
# operational decision after its target list and capture migration are verified.
ENVS = {
    "dev": "http://127.0.0.1:8096",
    "prod": "http://127.0.0.1:8100",
}


def latest_capture(base):
    """Most-recent prop capture_at (UTC datetime) for an env, or None if unreachable/empty."""
    req = urllib.request.Request(base + "/api/props?limit=1")
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.load(r)
    if not rows:
        return None
    ts = rows[0].get("captured_at")
    return dt.datetime.fromisoformat(ts) if ts else None


def main():
    now = dt.datetime.now(dt.timezone.utc)
    stale = []
    for env, base in ENVS.items():
        try:
            latest = latest_capture(base)
        except Exception as e:
            print(f"ALERT [{env}] props freshness check FAILED: {e} ({base})", flush=True)
            stale.append(env)
            continue
        if latest is None:
            print(f"ALERT [{env}] no props in DB at all ({base})", flush=True)
            stale.append(env)
            continue
        age_h = (now - latest).total_seconds() / 3600
        if age_h > STALE_HOURS:
            print(f"ALERT [{env}] props STALE: last capture {latest.isoformat()} "
                  f"({age_h:.1f}h ago, threshold {STALE_HOURS}h) — automatic ingest held by policy", flush=True)
            stale.append(env)
        else:
            print(f"OK [{env}] fresh: last capture {age_h:.1f}h ago", flush=True)

    if stale:
        sys.exit(1)  # non-zero → the timer logs a failure; hook OnFailure for a push alert later


if __name__ == "__main__":
    main()
