#!/usr/bin/env python3
"""Evidence collector for the YouTube-preference fix (NOT a permanent job).

Polls PandaScore + frag.se for the next LIVE match that actually carries a YouTube
stream, then runs the real board picker (/api/esports/slate) and records what it
chose for that match. Writes a receipt so we KNOW whether YouTube won on a real
match instead of asserting it. Exits after the first qualifying observation.
"""
import json, os, time, urllib.request, urllib.error, subprocess

OUT = "/root/legendarypicks/logs/yt-pick-evidence.jsonl"
PS_KEY = ""
for line in open("/root/.hermes/.env"):
    if line.startswith("PANDASCORE_API_KEY="):
        PS_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")


def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def yt_bearing_live_matches():
    """Names of live matches that carry a YouTube stream, per PandaScore + frag.se."""
    found = []
    try:
        ps = _get("https://api.pandascore.co/matches/running?page[size]=40",
                  {"Authorization": f"Bearer {PS_KEY}"})
        for m in ps:
            opps = [(o.get("opponent") or {}).get("name") or "?" for o in (m.get("opponents") or [])]
            yts = [s.get("raw_url") for s in (m.get("streams_list") or []) if "youtu" in (s.get("raw_url") or "")]
            if yts:
                found.append({"src": "pandascore", "teams": opps, "yt": yts})
    except Exception as e:
        pass
    try:
        fr = _get("https://frag.se/api/live")
        ms = fr if isinstance(fr, list) else (fr.get("matches") or fr.get("data") or [])
        for m in ms:
            opps = [(o.get("opponent") or {}).get("name") or "?" for o in (m.get("opponents") or [])]
            yts = [ (s.get("raw_url") or s.get("embed_url")) for s in (m.get("streams") or [])
                    if "youtu" in ((s.get("raw_url") or "") + (s.get("embed_url") or "")) ]
            if yts:
                found.append({"src": "frag", "teams": opps, "yt": yts})
    except Exception:
        pass
    return found


def board_pick():
    try:
        d = _get("http://localhost:8095/api/esports/slate", timeout=25)
    except Exception:
        return []
    out = []
    for m in d.get("matches", []):
        if m.get("state") != "live":
            continue
        w = m.get("watch") or {}
        out.append({
            "teams": [m.get("teamA"), m.get("teamB")],
            "picked_platform": w.get("platform"),
            "picked_url": w.get("url") or w.get("embedUrl"),
            "alternates": [a.get("platform") for a in (m.get("alternates") or w.get("alternates") or [])],
        })
    return out


def main():
    for _ in range(720):  # ~24h at 2-min cadence
        yb = yt_bearing_live_matches()
        if yb:
            picks = board_pick()
            rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "yt_bearing_sources": yb, "board_picks": picks}
            with open(OUT, "a") as f:
                f.write(json.dumps(rec) + "\n")
            print("QUALIFYING MATCH FOUND — receipt written to", OUT)
            print(json.dumps(rec, indent=2))
            return
        time.sleep(120)
    print("no YouTube-bearing live esports match observed in the watch window")


if __name__ == "__main__":
    main()
