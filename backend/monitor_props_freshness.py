#!/usr/bin/env python3
"""
monitor_props_freshness.py — guard against props data silently dropping off.

Prod once went 8 days stale because nothing was feeding it AND nothing noticed. This checks each
environment's most-recent prop capture; if it's older than the threshold it (1) logs a loud ALERT,
(2) SELF-HEALS by re-triggering that env's ingest service, and (3) exits non-zero so the systemd
timer records a failure. Run every 30 min by legendarypicks-props-freshness.timer.

Add an env to ENVS the moment it is supposed to be fed (prod → enable at deploy, once prod has its
own ingest service).
"""
import sys, json, subprocess, urllib.request, datetime as dt

STALE_HOURS = 3.0  # ingest runs every 30 min; >3h without a fresh capture = something is wrong

# env -> (backend base url, systemd ingest service to re-trigger on staleness)
ENVS = {
    "dev": ("http://127.0.0.1:8096", "legendarypicks-props.service"),
    "prod": ("http://127.0.0.1:8100", "legendarypicks-props-prod.service"),  # enabled at v0.5.5 prod deploy 2026-07-19
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
    for env, (base, service) in ENVS.items():
        try:
            latest = latest_capture(base)
        except Exception as e:
            print(f"ALERT [{env}] props freshness check FAILED: {e} ({base})", flush=True)
            stale.append(env)
            continue
        if latest is None:
            print(f"ALERT [{env}] no props in DB at all ({base})", flush=True)
            stale.append(env)
            _self_heal(env, service)
            continue
        age_h = (now - latest).total_seconds() / 3600
        if age_h > STALE_HOURS:
            print(f"ALERT [{env}] props STALE: last capture {latest.isoformat()} "
                  f"({age_h:.1f}h ago, threshold {STALE_HOURS}h) — self-healing via {service}", flush=True)
            stale.append(env)
            _self_heal(env, service)
        else:
            print(f"OK [{env}] fresh: last capture {age_h:.1f}h ago", flush=True)

    if stale:
        sys.exit(1)  # non-zero → the timer logs a failure; hook OnFailure for a push alert later


def _self_heal(env, service):
    """Re-trigger the env's ingest so a stopped/failed run recovers on its own."""
    try:
        subprocess.run(["systemctl", "start", service], timeout=15, check=False)
        print(f"  [{env}] triggered {service}", flush=True)
    except Exception as e:
        print(f"  [{env}] self-heal failed: {e}", flush=True)


if __name__ == "__main__":
    main()
