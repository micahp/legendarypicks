#!/usr/bin/env python3
"""Capture one publicly published swcrockett NFL weekly forecast CSV.

Forecasts come only from swcrockett's CSV. Kickoff instants are joined by the
published game_id to nflverse's games.csv; an absent or conflicting schedule
row fails closed. Captures are immutable at research/swcrockett/<season>-w<week>.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytz

try:
    from .team_codes import normalize
except ImportError:  # direct execution: python3 backend/swcrockett_import.py
    from team_codes import normalize


PREDICTION_URL = (
    "https://raw.githubusercontent.com/swcrockett/nfl-win-probability-model/main/"
    "outputs/predictions/{season}_week_{week:02d}.csv"
)
SCHEDULE_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
ROOT = Path(__file__).resolve().parent.parent
ET = pytz.timezone("America/New_York")
REQUIRED_PREDICTION_COLUMNS = {
    "season", "week", "gameday", "game_id", "away_team", "home_team",
    "away_win_probability", "home_win_probability",
}
REQUIRED_SCHEDULE_COLUMNS = {
    "season", "game_type", "week", "gameday", "gametime", "game_id",
    "away_team", "home_team",
}


class ImportErrorClosed(RuntimeError):
    """A source or identity condition prevents a safe capture."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def kickoff_utc(gameday: str, gametime: str) -> str:
    try:
        local = ET.localize(datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M"))
    except (TypeError, ValueError, pytz.exceptions.InvalidTimeError) as exc:
        raise ImportErrorClosed(f"invalid or missing published kickoff {gameday!r} {gametime!r}") from exc
    return local.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fetch(url: str) -> tuple[bytes, dict[str, object]]:
    request = urllib.request.Request(url, headers={"User-Agent": "lp-swcrockett-research-import/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            fetched_at = utc_now()
            metadata = {
                "url": url,
                "final_url": response.geturl(),
                "http_status": response.status,
                "fetched_at": fetched_at,
                "server_date": response.headers.get("Date"),
                "bytes": len(body),
                "sha256_raw_payload": hashlib.sha256(body).hexdigest(),
            }
            if response.status != 200:
                raise ImportErrorClosed(f"{url} returned HTTP {response.status}")
            return body, metadata
    except urllib.error.HTTPError as exc:
        raise ImportErrorClosed(f"{url} returned HTTP {exc.code}") from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise ImportErrorClosed(f"could not retrieve {url}: {exc}") from exc


def parse_schedule(raw: bytes) -> dict[str, dict[str, str]]:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    missing = REQUIRED_SCHEDULE_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ImportErrorClosed(f"nflverse games.csv lacks required columns: {sorted(missing)}")
    games: dict[str, dict[str, str]] = {}
    for row in reader:
        if not row.get("game_id"):
            continue
        if row["game_id"] in games:
            raise ImportErrorClosed(f"duplicate schedule game_id {row['game_id']!r}")
        games[row["game_id"]] = row
    return games


def probability(value: str, field: str, game_id: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ImportErrorClosed(f"{game_id}: invalid {field} {value!r}") from exc
    if not math.isfinite(result) or not 0.0 < result < 1.0:
        raise ImportErrorClosed(f"{game_id}: {field} must be strictly between 0 and 1, got {value!r}")
    return result


def build_capture(
    prediction_bytes: bytes,
    prediction_meta: dict[str, object],
    schedule_bytes: bytes,
    schedule_meta: dict[str, object],
    season: int,
    week: int,
) -> dict[str, object]:
    schedule = parse_schedule(schedule_bytes)
    reader = csv.DictReader(io.StringIO(prediction_bytes.decode("utf-8-sig"), newline=""))
    missing = REQUIRED_PREDICTION_COLUMNS - set(reader.fieldnames or [])
    if missing:
        raise ImportErrorClosed(f"publisher CSV lacks required columns: {sorted(missing)}")

    fetched_at = str(prediction_meta["fetched_at"])
    fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    source_sha = str(prediction_meta["sha256_raw_payload"])
    seen_ids: set[str] = set()
    seen_matchups: set[tuple[str, str]] = set()
    games: list[dict[str, object]] = []

    for row in reader:
        game_id = (row.get("game_id") or "").strip()
        if not game_id:
            raise ImportErrorClosed("publisher row has no game_id")
        if game_id in seen_ids:
            raise ImportErrorClosed(f"duplicate publisher game_id {game_id!r}")
        seen_ids.add(game_id)
        try:
            row_season, row_week = int(row["season"]), int(row["week"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ImportErrorClosed(f"{game_id}: invalid season/week") from exc
        if row_season != season or row_week != week:
            raise ImportErrorClosed(
                f"{game_id}: source season/week {row_season}/{row_week} != requested {season}/{week}"
            )

        source_away = (row.get("away_team") or "").strip()
        source_home = (row.get("home_team") or "").strip()
        try:
            away = normalize("nfl", source_away)
            home = normalize("nfl", source_home)
        except ValueError as exc:
            raise ImportErrorClosed(f"{game_id}: unknown team code: {exc}") from exc
        matchup = (away, home)
        if matchup in seen_matchups:
            raise ImportErrorClosed(f"duplicate publisher matchup {away}@{home} in {season} week {week}")
        seen_matchups.add(matchup)

        schedule_row = schedule.get(game_id)
        if schedule_row is None:
            raise ImportErrorClosed(f"{game_id}: no matching game_id in the published nflverse schedule")
        schedule_away, schedule_home = schedule_row["away_team"].strip(), schedule_row["home_team"].strip()
        try:
            normalized_schedule_away = normalize("nfl", schedule_away)
            normalized_schedule_home = normalize("nfl", schedule_home)
        except ValueError as exc:
            raise ImportErrorClosed(f"{game_id}: unknown schedule team code: {exc}") from exc
        if (
            int(schedule_row["season"]) != season
            or int(schedule_row["week"]) != week
            or schedule_row["game_type"] != "REG"
            or normalized_schedule_away != away
            or normalized_schedule_home != home
            or schedule_row["gameday"] != row.get("gameday")
        ):
            raise ImportErrorClosed(f"{game_id}: publisher row conflicts with the nflverse schedule identity")

        kickoff = kickoff_utc(schedule_row["gameday"], schedule_row["gametime"])
        kickoff_dt = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
        p_away = probability(row["away_win_probability"], "away_win_probability", game_id)
        p_home = probability(row["home_win_probability"], "home_win_probability", game_id)
        if not math.isclose(p_away + p_home, 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ImportErrorClosed(f"{game_id}: away/home win probabilities do not sum to 1")

        games.append({
            "game_id": game_id,
            "source_url": prediction_meta["url"],
            "fetched_at": fetched_at,
            "season": season,
            "week": week,
            "kickoff_utc": kickoff,
            "home_team": home,
            "away_team": away,
            "p_home_win": p_home,
            "raw_payload_sha256": source_sha,
            "post_kickoff": fetched_dt >= kickoff_dt,
        })

    if not games:
        raise ImportErrorClosed("publisher CSV contains no game rows")
    return {
        "schema_version": 1,
        "source": "swcrockett/nfl-win-probability-model",
        "season": season,
        "week": week,
        "prediction_fetch": prediction_meta,
        "kickoff_schedule": schedule_meta,
        "games": games,
    }


def write_immutable(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() == encoded:
            return
        raise ImportErrorClosed(f"refusing to overwrite existing capture {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(temp_name, path)
        except FileExistsError as exc:
            raise ImportErrorClosed(f"refusing to overwrite existing capture {path}") from exc
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--out", type=Path, help="output JSON; default research/swcrockett/<season>-w<week>.json")
    args = parser.parse_args(argv)
    if args.season < 2000 or not 1 <= args.week <= 18:
        parser.error("season or week is outside the supported NFL range")

    prediction_url = PREDICTION_URL.format(season=args.season, week=args.week)
    prediction_bytes, prediction_meta = fetch(prediction_url)
    schedule_bytes, schedule_meta = fetch(SCHEDULE_URL)
    payload = build_capture(
        prediction_bytes, prediction_meta, schedule_bytes, schedule_meta, args.season, args.week
    )
    output = args.out or ROOT / "research" / "swcrockett" / f"{args.season}-w{args.week}.json"
    if not output.is_absolute():
        output = ROOT / output
    write_immutable(output, payload)
    games = payload["games"]
    post_kickoff = sum(bool(game["post_kickoff"]) for game in games)
    print(json.dumps({
        "output": str(output),
        "season": args.season,
        "week": args.week,
        "games": len(games),
        "post_kickoff": post_kickoff,
        "pre_kickoff": len(games) - post_kickoff,
        "raw_payload_sha256": prediction_meta["sha256_raw_payload"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImportErrorClosed as exc:
        print(f"FAIL CLOSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
