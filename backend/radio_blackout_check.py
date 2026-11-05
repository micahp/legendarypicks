#!/usr/bin/env python3
"""radio_blackout_check.py: is the radio a live MLB/NBA card plays a blackout loop right now?

MLB and NBA team radio is limited to each team's home market; outside it the station plays a
looping notice ("you are not in an area where this game is available", "blacked out in your
area due to NBA broadcast guidelines") for the whole game. A browser cannot tell that loop from
real audio, so this samples it here: for every MLB/NBA game the scoreboard has `in`, it takes
the stream the card plays (data/radio-listen.json, home club first, the away club when the home
club has none, the same pick as lib/gameAudio.ts), records SAMPLE_S seconds, transcribes them
with faster-whisper, and matches the notice wording.

The answer describes THIS server's location (a US datacenter): a listener inside the team's
market may still hear the game, which is why the card keeps its play button and only labels it.
NHL team streams are free everywhere and are not checked.

Writes OUT ({"checked_at", "games": {game_id: {"league", "team", "blackout", "heard"}}}),
which GET /api/radio/blackouts serves. One run at a time (lock); cron every 5 minutes.
Needs faster-whisper: run with the prediction-market-trading .venv-ba interpreter.

    LP_DB_PATH=backend/data/picks.dev.db /root/prediction-market-trading/.venv-ba/bin/python \\
        backend/radio_blackout_check.py
"""
import concurrent.futures as cf
import datetime as dt
import fcntl
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
LISTEN = HERE.parent / "data" / "radio-listen.json"
OUT = pathlib.Path(os.environ.get("LP_RADIO_BLACKOUTS", HERE / "data" / "radio-blackouts.json"))
SAMPLE_S = 20
ALIAS = {"nhl": {"UTAH": "UTA"}, "nba": {"UTA": "UTAH"}}
NOTICE = re.compile(
    r"not (?:be )?(?:in an area where this game is available|available in (?:your|this) area)"
    r"|blacked out in your area|due to (?:league|leak) restrictions|broadcast guidelines"
    r"|within a \d+[- ]mile radius", re.I)


def pick(table, league, home, away):
    """The stream the card plays: home club first, else away (mirrors audioForGame()[0])."""
    for team in (home, away):
        key = ALIAS.get(league, {}).get(team, team)
        e = (table.get(league) or {}).get(key)
        if e and e.get("stream"):
            return team, e["stream"]
    return None, None


def record(url, path):
    subprocess.run(["timeout", str(SAMPLE_S + 25), "ffmpeg", "-loglevel", "error", "-y", "-i", url,
                    "-t", str(SAMPLE_S), "-vn", "-ac", "1", "-ar", "16000", path], check=False)
    return os.path.exists(path) and os.path.getsize(path) > 16000 * 2 * 5   # at least 5 s of audio


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lock = open(str(OUT) + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("radio_blackout_check is already running")
    db_path = os.environ.get("LP_DB_PATH")
    if not db_path:
        sys.exit("LP_DB_PATH is required (the scoreboard DB this check reads)")
    table = json.loads(LISTEN.read_text())
    db = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    rows = db.execute(
        "select league, game_id, json_extract(payload,'$.home.abbrev'), json_extract(payload,'$.away.abbrev') "
        "from scoreboard_snapshots where league in ('mlb','nba') and state='in'").fetchall()
    jobs = []
    for league, gid, home, away in rows:
        team, url = pick(table, league, home, away)
        if url:
            jobs.append((league, str(gid), team, url))
    games, tmp = {}, tempfile.mkdtemp(prefix="radio-blackout-")
    with cf.ThreadPoolExecutor(6) as ex:
        ok = dict(zip([j[1] for j in jobs],
                      ex.map(lambda j: record(j[3], os.path.join(tmp, j[1] + ".wav")), jobs)))
    model = None
    for league, gid, team, url in jobs:
        if not ok.get(gid):
            games[gid] = {"league": league, "team": team, "blackout": None, "heard": "no audio recorded"}
            continue
        if model is None:
            from faster_whisper import WhisperModel
            model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=2)
        segs, _ = model.transcribe(os.path.join(tmp, gid + ".wav"), vad_filter=True)
        text = " ".join(s.text.strip() for s in segs)
        games[gid] = {"league": league, "team": team, "blackout": bool(NOTICE.search(text)), "heard": text[:200]}
    for f in pathlib.Path(tmp).glob("*.wav"):
        f.unlink()
    os.rmdir(tmp)
    out = {"checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "games": games}
    tmp_out = str(OUT) + ".tmp"
    with open(tmp_out, "w") as fh:
        json.dump(out, fh, indent=1)
    os.replace(tmp_out, OUT)
    print("%s checked %d live MLB/NBA games, %d blackout" % (out["checked_at"], len(games),
          sum(1 for g in games.values() if g["blackout"])))


if __name__ == "__main__":
    main()
