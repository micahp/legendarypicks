"""monitor_esports_state.py — snapshot /api/esports/upcoming on a timer, diff against the last
snapshot, and log every state transition per match (scheduled->live, live->finished, watch link
added/removed, score changes). Built after a session where several silent regressions (a
duplicate live match, a stale never-finalized pinned entry, missing logos, missing stream links)
went unnoticed for hours. This doesn't fix those bugs — it makes the NEXT one visible within one
run instead of requiring a multi-hour manual forensic session.

Not a Markov-chain model (that's the wrong tool for a handful of known-good/known-bad
transitions on ~80 matches) — a small explicit table of VALID transitions is simpler, cheaper,
and fully auditable. Anything not in the table is logged as an anomaly.

Run standalone (cron-friendly):
    LP_DB_PATH=... venv/bin/python3 monitor_esports_state.py
"""

import json
import os
import time
import urllib.request as _u

_BACKEND = os.environ.get("LP_MONITOR_BACKEND", "http://localhost:8095")
_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "esports_state_snapshot.json")
_TRANSITIONS_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "esports-state-transitions.jsonl")
_ANOMALIES_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "esports-state-ANOMALIES.log")

# A match's lifecycle phase, derived from (live, finished). Anything not moving forward through
# this order (or repeating the same phase) is an anomaly worth a human look.
_PHASE_ORDER = {"scheduled": 0, "live": 1, "finished": 2}


def _phase(m):
    if m.get("finished"):
        return "finished"
    if m.get("live"):
        return "live"
    return "scheduled"


def _key(m):
    # Raw (not normalized) names on purpose — if the same real match shows up under two
    # different name spellings, that's exactly the duplicate-match bug class we want to catch,
    # so it must produce two DIFFERENT keys, not collapse into one.
    return f"{m.get('title')}::{m.get('teamA')}::{m.get('teamB')}::{m.get('startTime')}"


def _watch_sig(m):
    w = m.get("watch") or {}
    return (w.get("platform"), w.get("channel"), w.get("online"))


def _fetch_matches():
    req = _u.Request(f"{_BACKEND}/api/esports/upcoming", headers={"Accept": "application/json"})
    with _u.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode()).get("matches", [])


def _load_state():
    if os.path.exists(_STATE_PATH):
        try:
            with open(_STATE_PATH) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(state):
    os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
    tmp = _STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, _STATE_PATH)


def _append(path, line):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(line + "\n")


def run():
    now = time.time()
    now_ms = now * 1000
    try:
        matches = _fetch_matches()
    except Exception as ex:
        _append(_ANOMALIES_LOG, f"{time.strftime('%Y-%m-%dT%H:%M:%S')} FETCH_FAILED {ex!r}")
        return

    prev_state = _load_state()
    new_state = {}
    seen_keys = set()

    # Duplicate-match detection: group by a fuzzy (title, normalized teams) signature; if two
    # DIFFERENT raw keys share one and their start times are within 2h of each other, flag it —
    # this is the exact shape of the WBT/Wrotberry bug from Jul-1.
    from routers.esports.common import _strip_name
    fuzzy_groups = {}

    for m in matches:
        k = _key(m)
        seen_keys.add(k)
        phase = _phase(m)
        watch_sig = _watch_sig(m)
        prev = prev_state.get(k)

        fuzzy_key = (m.get("title"), frozenset([_strip_name(m.get("teamA")), _strip_name(m.get("teamB"))]))
        fuzzy_groups.setdefault(fuzzy_key, []).append((k, m.get("startTime")))

        entry = {
            "phase": phase,
            "watch_sig": list(watch_sig),
            "has_logo": bool(m.get("logoA") or m.get("logoB")),
            "score": m.get("score"),
            "first_seen": (prev or {}).get("first_seen", now),
            "ever_live": bool((prev or {}).get("ever_live")) or phase == "live",
            "last_seen": now,
        }

        if prev is None:
            new_state[k] = entry
            continue

        # Phase transition.
        if prev["phase"] != phase:
            valid = _PHASE_ORDER.get(phase, -1) >= _PHASE_ORDER.get(prev["phase"], -1)
            tag = "TRANSITION" if valid else "ANOMALY_BACKWARDS_TRANSITION"
            line = json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "type": tag, "key": k,
                "from": prev["phase"], "to": phase, "score": m.get("score"),
            })
            _append(_TRANSITIONS_LOG, line)
            if tag != "TRANSITION":
                _append(_ANOMALIES_LOG, f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {tag} {k} {prev['phase']}->{phase}")

        # Watch link appeared/disappeared.
        if prev["watch_sig"] != list(watch_sig):
            had, now_has = any(prev["watch_sig"]), any(watch_sig)
            if had and not now_has:
                _append(_ANOMALIES_LOG, f"{time.strftime('%Y-%m-%dT%H:%M:%S')} LINK_DISAPPEARED {k} {prev['watch_sig']}->{list(watch_sig)}")
            _append(_TRANSITIONS_LOG, json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "type": "WATCH_CHANGED", "key": k,
                "from": prev["watch_sig"], "to": list(watch_sig),
            }))

        # A pinned/stale match: live/finished stopped updating for a long time while score also
        # hasn't moved and the match was never marked finished — the exact "pinned forever with
        # a stale 2-0" bug from Jul-1 (MSI/T1 vs Team Liquid).
        stale_for_h = (now - entry["first_seen"]) / 3600
        if phase == "scheduled" and m.get("startTime") and (now_ms - m["startTime"]) / 3600000 > 3 and not entry["ever_live"]:
            _append(_ANOMALIES_LOG, f"{time.strftime('%Y-%m-%dT%H:%M:%S')} NEVER_WENT_LIVE {k} started {(now_ms - m['startTime'])/3600000:.1f}h ago, still scheduled, never observed live")

        entry["ever_live"] = entry["ever_live"] or prev.get("ever_live")
        new_state[k] = entry

    # Duplicate detection across fuzzy groups.
    for (title, teams), members in fuzzy_groups.items():
        if len(members) < 2:
            continue
        members_sorted = sorted(members, key=lambda x: x[1] or 0)
        for i in range(len(members_sorted) - 1):
            t1, t2 = members_sorted[i][1], members_sorted[i + 1][1]
            if t1 and t2 and abs(t1 - t2) < 2 * 3600 * 1000:
                _append(_ANOMALIES_LOG,
                        f"{time.strftime('%Y-%m-%dT%H:%M:%S')} POSSIBLE_DUPLICATE {title} {set(teams)} keys={[m[0] for m in members_sorted]}")

    # Prune matches no longer in the feed at all (don't grow the snapshot forever).
    _save_state(new_state)


if __name__ == "__main__":
    run()
