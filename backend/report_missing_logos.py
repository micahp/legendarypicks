"""report_missing_logos.py — list every team currently on the esports board with no crest.

Logo gaps come from one of two places: a team no source (PandaScore/frag) has a crest for at all
(e.g. minor-qualifier sides), or a name-variant that isn't matching the logo index. This report makes
the gaps visible so they can be triaged — added to `_TEAM_ALIASES`, or accepted as genuine no-crest
teams. Prints a table and appends a JSONL line to logs/esports-missing-logos.jsonl for trend-watching.

Run:
    LP_MONITOR_BACKEND=http://localhost:8095 venv/bin/python3 report_missing_logos.py
"""

import json
import os
import time
import urllib.request as _u

_BACKEND = os.environ.get("LP_MONITOR_BACKEND", "http://localhost:8095")
_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "esports-missing-logos.jsonl")


def _fetch():
    req = _u.Request(f"{_BACKEND}/api/esports/upcoming", headers={"Accept": "application/json"})
    with _u.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode()).get("matches", [])


def run():
    matches = _fetch()
    # team -> {"title":.., "count":n, "leagues":set, "phases":set}
    missing = {}
    for m in matches:
        phase = "live" if m.get("live") else "finished" if m.get("finished") else "scheduled"
        for side in ("A", "B"):
            name = m.get("team" + side)
            if not name:
                continue
            if not m.get("logo" + side):
                e = missing.setdefault((m.get("title"), name), {"count": 0, "leagues": set(), "phases": set()})
                e["count"] += 1
                e["leagues"].add(m.get("league") or "")
                e["phases"].add(phase)

    total_teams = {(m.get("title"), m.get("team" + s)) for m in matches for s in ("A", "B") if m.get("team" + s)}
    print(f"{len(missing)} teams missing a crest, of {len(total_teams)} distinct teams on the board "
          f"({len(matches)} matches)\n")
    for (title, name), e in sorted(missing.items(), key=lambda x: (-x[1]["count"], x[0][0])):
        phases = ",".join(sorted(e["phases"]))
        print(f"  [{title:12}] {name:32} x{e['count']:<2} ({phases})  {sorted(e['leagues'])[0] if e['leagues'] else ''}")

    try:
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        with open(_LOG, "a") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "missing": len(missing), "total_teams": len(total_teams), "matches": len(matches),
                "teams": [{"title": t, "team": n, "count": e["count"]} for (t, n), e in missing.items()],
            }) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    run()
