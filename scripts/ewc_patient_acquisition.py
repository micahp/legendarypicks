#!/usr/bin/env python3
"""Patient EWC acquisition: wait for the Liquipedia throttle to clear, then run the
approved sequential fetch for all titles without a published snapshot.

- Probe once per PROBE_INTERVAL_S with a lightweight action=query (1 request, no parse slot).
- On first 200, launch the fetcher for the remaining titles in one process (30s parse slot).
- Log everything to EWC_ACQ_LOG; exit 0 only when every missing title has a snapshot or
  was honestly recorded as source-unavailable.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
VENV_PY = "/root/legendarypicks/backend/venv/bin/python"
FETCHER = os.path.join(BACKEND, "fetch_ewc_title_schedules.py")
SCHED_DIR = os.path.join(BACKEND, "data", "esports_ewc_schedules")
LOG = os.environ.get("EWC_ACQ_LOG", "/tmp/ewc-acquisition.log")

PROBE_INTERVAL_S = 300      # 5 min between light probes while blocked
MAX_WAIT_S = int(os.environ.get("EWC_ACQ_MAX_WAIT_S", str(6 * 3600)))  # 6h budget

API_UA = ("LegendaryPicks/1.0 (EWC title schedule ingest; "
          "contact via github.com/legendarypicks)")


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def probe(sub):
    url = ("https://liquipedia.net/%s/api.php?action=query&prop=info"
           "&titles=Esports_World_Cup/2026&format=json" % sub)
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": API_UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        return True
    except urllib.error.HTTPError as exc:
        log("probe HTTP %s (%s)" % (exc.code, sub))
        return False
    except Exception as exc:  # noqa: BLE001
        log("probe error %s (%s)" % (type(exc).__name__, sub))
        return False


def missing_titles():
    manifest_path = os.path.join(SCHED_DIR, "manifest.json")
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    return [slug for slug, entry in manifest.get("titles", {}).items()
            if entry.get("status") != "published"]


def main():
    # Collect the exact requested set once (the fetcher reads the manifest itself too).
    missing = missing_titles()
    if missing is None:
        log("cannot read manifest; aborting")
        return 2
    if not missing:
        log("no missing titles; nothing to do")
        return 0
    log("waiting for Liquipedia throttle; %d titles pending: %s" %
        (len(missing), ",".join(sorted(missing))))
    deadline = time.time() + MAX_WAIT_S
    while time.time() < deadline:
        if probe("chess"):
            log("throttle cleared; starting sequential fetch")
            cmd = [VENV_PY, FETCHER] + sorted(missing)
            proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, timeout=7200)
            with open(LOG, "a") as f:
                f.write(proc.stdout)
                if proc.stderr:
                    f.write("STDERR:\n" + proc.stderr + "\n")
            log("fetcher exit=%d" % proc.returncode)
            still_missing = missing_titles()
            log("still missing after run: %s" % (still_missing or "none"))
            return proc.returncode if not still_missing else 1
        # Only parse-slot consumers need spacing; a light probe is fine at this cadence.
        time.sleep(PROBE_INTERVAL_S)
    log("throttle did not clear within %ds budget" % MAX_WAIT_S)
    return 1


if __name__ == "__main__":
    sys.exit(main())
