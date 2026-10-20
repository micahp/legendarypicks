#!/usr/bin/env python3
"""Reconcile NHL archived per-player SOG and goalie outcomes to official boxscores.

Default mode is offline and reads only committed gzip responses plus read-only
local source data. Pass --fetch to retrieve missing NHL GameCenter boxscores.
No model fitting, probability forecast, market test, or database write is done.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
CANONICAL = Path(
    "/root/legendarypicks/research/nhl/kalshi-playoff-audit-2025-26/"
    "canonical_games_v1_7cd2fc9a6e84470c.csv"
)
DUCKDB = Path("/root/nhl_database_2025-26-playoffs.duckdb")
ANCHOR_GAME_ID = 2018020160
SEED = 20261020
CUTOFF = "2022-11-27"
EXPECTED_FRAME_COUNTS = {2018: 1271, 2019: 1082, 2020: 868, 2021: 1312, 2022: 343}
EXPECTED_FRAME_TOTAL = 4876
EXPECTED_FRAME_SHA256 = "336d8a8d055febd742dbf31ce7a613bd2e47c2cd8fbc7a8d956fc8967ba47b1c"
EXPECTED_SAMPLE_SHA256 = "0cd5fd97f61d2e945395b7e2b8238746dc3cad5c818fae746f1629c40149222a"
EXPECTED_MEASUREMENT_SHA256 = "13386d4311c7393334c26097b2aa8832a1c10a19a9d05b33ad0372e0907d3d48"
USER_AGENT = "Mozilla/5.0 (compatible; LegendaryPicks-NHL-Outcome-Recon/1.0)"
NETWORK_PAUSE_SECONDS = 0.5
RETRY_PAUSE_SECONDS = 1.0
SEASON_LABELS = {
    2018: "2018-19",
    2019: "2019-20",
    2020: "2020-21",
    2021: "2021-22",
    2022: "2022-23 slice",
}
SOG_LINES = (0.5, 1.5, 2.5, 3.5)
SAVE_LINES = (20.5, 24.5, 28.5)
HIST_BINS = (-3, -2, -1, 0, 1, 2, 3)
TEAM_ALIASES = {"PHX": "ARI"}


class BulkAccessRefused(RuntimeError):
    """The official endpoint refused access; stop before further requests."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def season_label(season: int) -> str:
    return SEASON_LABELS[season]


def canonical_team(value: Any) -> str:
    text = str(value)
    return TEAM_ALIASES.get(text, text)


def canonical_frame(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"canonical schedule missing: {path}")
    required = {"game_id", "season", "game_type", "game_date", "home_team", "away_team"}
    by_id: dict[int, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"canonical schedule lacks columns: {sorted(required - set(reader.fieldnames or []))}")
        for raw in reader:
            season = int(raw["season"])
            if not (2018 <= season <= 2022):
                continue
            if int(raw["game_type"]) != 2 or raw["game_date"] > CUTOFF:
                continue
            game_id = int(raw["game_id"])
            if game_id in by_id:
                raise ValueError(f"duplicate canonical game_id={game_id}")
            by_id[game_id] = {
                "game_id": game_id,
                "season": season,
                "game_date": raw["game_date"],
                "home_team": raw["home_team"],
                "away_team": raw["away_team"],
            }
    frame = sorted(by_id.values(), key=lambda row: (row["season"], row["game_id"]))
    counts = Counter(row["season"] for row in frame)
    if len(frame) != EXPECTED_FRAME_TOTAL or dict(counts) != EXPECTED_FRAME_COUNTS:
        raise ValueError(
            f"canonical frame changed: n={len(frame)} seasons={dict(counts)}; "
            f"expected n={EXPECTED_FRAME_TOTAL} seasons={EXPECTED_FRAME_COUNTS}"
        )
    frame_bytes = "".join(
        f"{r['season']},{r['game_id']},{r['game_date']},{r['home_team']},{r['away_team']}\n"
        for r in frame
    ).encode()
    actual_frame_hash = sha256(frame_bytes)
    if actual_frame_hash != EXPECTED_FRAME_SHA256:
        raise ValueError(f"canonical frame SHA256 changed: {actual_frame_hash}")
    return frame


def draw_sample(frame: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_season: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in frame:
        by_season[row["season"]].append(row)
    rng = random.Random(SEED)
    sample: list[dict[str, Any]] = []
    for season in sorted(by_season):
        games = sorted(by_season[season], key=lambda row: row["game_id"])
        anchor = next((row for row in games if row["game_id"] == ANCHOR_GAME_ID), None)
        take = 59 if anchor is not None else 60
        pool = [row for row in games if row["game_id"] != ANCHOR_GAME_ID]
        if len(pool) < take:
            raise ValueError(f"season {season} cannot supply {take} random games")
        sample.extend(rng.sample(pool, take))
        if anchor is not None:
            sample.append(anchor)
    sample.sort(key=lambda row: (row["season"], row["game_id"]))
    counts = Counter(row["season"] for row in sample)
    if len(sample) != 300 or any(counts[year] != 60 for year in by_season):
        raise ValueError(f"bad stratified sample: n={len(sample)} blocks={dict(counts)}")
    if ANCHOR_GAME_ID not in {row["game_id"] for row in sample}:
        raise ValueError("required anchor game was not sampled")
    sample_hash = sha256(
        "".join(f"{row['season']}:{row['game_id']}\n" for row in sample).encode()
    )
    if sample_hash != EXPECTED_SAMPLE_SHA256:
        raise ValueError(f"sample SHA256 changed: {sample_hash}")
    return sample


def cache_path(game_id: int) -> Path:
    return CACHE / f"{game_id}.json.gz"


def decode_boxscore(raw: bytes, expected_game_id: int) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON for game_id={expected_game_id}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"boxscore is not an object for game_id={expected_game_id}")
    payload_id = payload.get("id", payload.get("gameId", expected_game_id))
    if int(payload_id) != expected_game_id:
        raise ValueError(f"boxscore game id {payload_id} != requested {expected_game_id}")
    if not isinstance(payload.get("playerByGameStats"), dict):
        raise ValueError(f"playerByGameStats missing for game_id={expected_game_id}")
    return payload


def write_gzip_atomic(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb", mtime=0) as zipped:
            zipped.write(body)
    temporary.replace(path)


def fetch_one(game_id: int) -> tuple[bool, str | None]:
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_error = "unknown fetch error"
    for attempt in range(2):
        if attempt:
            time.sleep(RETRY_PAUSE_SECONDS)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
            decode_boxscore(body, game_id)
            write_gzip_atomic(cache_path(game_id), body)
            return True, None
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code} {exc.reason}"
            if exc.code == 403:
                return False, f"REFUSED {last_error}"
            if attempt == 0:
                time.sleep(RETRY_PAUSE_SECONDS)
                continue
        except (OSError, TimeoutError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                continue
        break
    return False, last_error


def fetch_missing(sample: list[dict[str, Any]], probe_only: bool = False) -> dict[int, str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    targets = [next(row for row in sample if row["game_id"] == ANCHOR_GAME_ID)] if probe_only else sample
    errors: dict[int, str] = {}
    network_calls = 0
    for index, game in enumerate(targets, start=1):
        game_id = game["game_id"]
        path = cache_path(game_id)
        if path.is_file():
            payload = decode_boxscore(gzip.decompress(path.read_bytes()), game_id)
            if probe_only:
                parse_official(payload, game_id)
            print(f"CACHE_HIT game_id={game_id}")
            continue
        if network_calls:
            time.sleep(NETWORK_PAUSE_SECONDS)
        network_calls += 1
        okay, error = fetch_one(game_id)
        if okay:
            if probe_only:
                payload = decode_boxscore(gzip.decompress(path.read_bytes()), game_id)
                skaters, goalies = parse_official(payload, game_id)
                print(
                    f"PROBE_OK game_id={game_id} official_skater_rows={len(skaters)} "
                    f"official_goalie_rows={len(goalies)} raw_cache={path.name}"
                )
            elif index % 10 == 0 or index == len(targets):
                print(f"FETCH_PROGRESS complete={index}/{len(targets)} network_requests={network_calls}")
        else:
            errors[game_id] = error or "unknown fetch failure"
            print(f"FAILED game_id={game_id} {errors[game_id]}")
            if (error or "").startswith("REFUSED"):
                raise BulkAccessRefused(f"NHL boxscore endpoint refused game_id={game_id}: {error}")
        if probe_only and not okay:
            break
    print(
        f"FETCH_SUMMARY requested={len(targets)} available_cache="
        f"{sum(cache_path(row['game_id']).is_file() for row in targets)} "
        f"network_requests={network_calls} failed={len(errors)}"
    )
    return errors


def integer_stat(value: Any, label: str, game_id: int, player_id: int) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError(f"missing {label}: game_id={game_id} player_id={player_id}")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}={value!r}: game_id={game_id} player_id={player_id}") from exc
    if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
        raise ValueError(f"non-integer/nonnegative {label}={value!r}: game_id={game_id} player_id={player_id}")
    return int(numeric)


def parse_official(
    payload: dict[str, Any], game_id: int
) -> tuple[dict[int, int], dict[int, dict[str, int]]]:
    stats = payload["playerByGameStats"]
    skaters: dict[int, int] = {}
    goalies: dict[int, dict[str, int]] = {}
    for side in ("awayTeam", "homeTeam"):
        team = stats.get(side)
        if not isinstance(team, dict):
            raise ValueError(f"official {side} stats missing for game_id={game_id}")
        for group in ("forwards", "defense"):
            players = team.get(group)
            if not isinstance(players, list):
                raise ValueError(f"official {side}.{group} missing for game_id={game_id}")
            for player in players:
                if not isinstance(player, dict) or player.get("playerId") is None:
                    raise ValueError(f"official skater playerId missing for game_id={game_id}")
                player_id = int(player["playerId"])
                if player_id in skaters:
                    raise ValueError(f"duplicate official skater game/player: {game_id}/{player_id}")
                skaters[player_id] = integer_stat(player.get("sog"), "sog", game_id, player_id)
        players = team.get("goalies")
        if not isinstance(players, list):
            raise ValueError(f"official {side}.goalies missing for game_id={game_id}")
        for player in players:
            if not isinstance(player, dict) or player.get("playerId") is None:
                raise ValueError(f"official goalie playerId missing for game_id={game_id}")
            player_id = int(player["playerId"])
            if player_id in goalies:
                raise ValueError(f"duplicate official goalie game/player: {game_id}/{player_id}")
            goalies[player_id] = {
                "saves": integer_stat(player.get("saves"), "saves", game_id, player_id),
                "sa": integer_stat(player.get("shotsAgainst"), "shotsAgainst", game_id, player_id),
                "ga": integer_stat(player.get("goalsAgainst"), "goalsAgainst", game_id, player_id),
            }
    return skaters, goalies


def load_official_cache(sample: list[dict[str, Any]]) -> tuple[dict[int, dict[int, int]], dict[int, dict[int, dict[str, int]]]]:
    missing = [row["game_id"] for row in sample if not cache_path(row["game_id"]).is_file()]
    if missing:
        raise FileNotFoundError(
            f"offline cache incomplete: missing {len(missing)} of {len(sample)} games; "
            f"first missing game_ids={missing[:20]}"
        )
    official_skaters: dict[int, dict[int, int]] = {}
    official_goalies: dict[int, dict[int, dict[str, int]]] = {}
    for row in sample:
        game_id = row["game_id"]
        payload = decode_boxscore(gzip.decompress(cache_path(game_id).read_bytes()), game_id)
        official_skaters[game_id], official_goalies[game_id] = parse_official(payload, game_id)
    return official_skaters, official_goalies


def load_archived(
    sample: list[dict[str, Any]], duckdb_path: Path
) -> tuple[dict[int, dict[int, int]], dict[int, dict[int, dict[str, int]]]]:
    if not duckdb_path.is_file():
        raise FileNotFoundError(f"read-only DuckDB missing: {duckdb_path}")
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB unavailable; run with /root/lp-goalie-research/.venv/bin/python") from exc
    connection = duckdb.connect(
        str(duckdb_path), read_only=True, config={"memory_limit": "256MB", "threads": "1"}
    )
    try:
        connection.execute("SET enable_progress_bar=false")
        skater_cols = {row[0] for row in connection.execute("DESCRIBE SELECT * FROM skaters_gamelogs").fetchall()}
        goalie_cols = {row[0] for row in connection.execute("DESCRIBE SELECT * FROM goalies_gamelogs").fetchall()}
        need_skater = {"season", "gameId", "gameDate", "playerId", "playerTeam", "situation", "I_F_shotsOnGoal"}
        need_goalie = {"season", "gameId", "gameDate", "playerId", "playerTeam", "situation", "ongoal", "goals"}
        if not need_skater.issubset(skater_cols):
            raise ValueError(f"skaters_gamelogs lacks {sorted(need_skater - skater_cols)}")
        if not need_goalie.issubset(goalie_cols):
            raise ValueError(f"goalies_gamelogs lacks {sorted(need_goalie - goalie_cols)}")
        ids = [row["game_id"] for row in sample]
        placeholders = ",".join("?" for _ in ids)
        skater_rows = connection.execute(
            "SELECT season, gameId, gameDate, playerId, playerTeam, I_F_shotsOnGoal "
            f"FROM skaters_gamelogs WHERE lower(situation)='all' AND gameId IN ({placeholders})",
            ids,
        ).fetchall()
        goalie_rows = connection.execute(
            "SELECT season, gameId, gameDate, playerId, playerTeam, ongoal, goals "
            f"FROM goalies_gamelogs WHERE lower(situation)='all' AND gameId IN ({placeholders})",
            ids,
        ).fetchall()
    finally:
        connection.close()

    canonical = {row["game_id"]: row for row in sample}
    archived_skaters: dict[int, dict[int, int]] = defaultdict(dict)
    archived_goalies: dict[int, dict[int, dict[str, int]]] = defaultdict(dict)
    for season, raw_game_id, game_date, raw_player_id, team, raw_sog in skater_rows:
        game_id, player_id = int(raw_game_id), int(raw_player_id)
        game = canonical[game_id]
        if int(season) != game["season"] or str(game_date).replace("-", "")[:8] != game["game_date"].replace("-", ""):
            raise ValueError(f"archived skater identity mismatch at {game_id}/{player_id}")
        if canonical_team(team) not in (game["home_team"], game["away_team"]):
            raise ValueError(f"archived skater team mismatch at {game_id}/{player_id}: {team}")
        if player_id in archived_skaters[game_id]:
            raise ValueError(f"duplicate archived skater game/player: {game_id}/{player_id}")
        archived_skaters[game_id][player_id] = integer_stat(raw_sog, "archived SOG", game_id, player_id)
    for season, raw_game_id, game_date, raw_player_id, team, raw_sa, raw_ga in goalie_rows:
        game_id, player_id = int(raw_game_id), int(raw_player_id)
        game = canonical[game_id]
        if int(season) != game["season"] or str(game_date).replace("-", "")[:8] != game["game_date"].replace("-", ""):
            raise ValueError(f"archived goalie identity mismatch at {game_id}/{player_id}")
        if canonical_team(team) not in (game["home_team"], game["away_team"]):
            raise ValueError(f"archived goalie team mismatch at {game_id}/{player_id}: {team}")
        if player_id in archived_goalies[game_id]:
            raise ValueError(f"duplicate archived goalie game/player: {game_id}/{player_id}")
        sa = integer_stat(raw_sa, "archived shotsAgainst", game_id, player_id)
        ga = integer_stat(raw_ga, "archived goalsAgainst", game_id, player_id)
        if ga > sa:
            raise ValueError(f"archived goalsAgainst exceeds shotsAgainst: {game_id}/{player_id}")
        archived_goalies[game_id][player_id] = {"saves": sa - ga, "sa": sa, "ga": ga}
    return dict(archived_skaters), dict(archived_goalies)


def csv_bytes(headers: list[str], rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def player_sog_rows(
    sample: list[dict[str, Any]],
    archived: dict[int, dict[int, int]],
    official: dict[int, dict[int, int]],
) -> list[dict[str, Any]]:
    season_for = {row["game_id"]: season_label(row["season"]) for row in sample}
    result = []
    for game_id in sorted(season_for):
        a, o = archived.get(game_id, {}), official.get(game_id, {})
        for player_id in sorted(set(a) | set(o)):
            av, ov = a.get(player_id), o.get(player_id)
            result.append({
                "game_id": game_id,
                "season": season_for[game_id],
                "player_id": player_id,
                "archived_sog": "" if av is None else av,
                "official_sog": "" if ov is None else ov,
                "diff": "" if av is None or ov is None else av - ov,
            })
    return result


def goalie_rows(
    sample: list[dict[str, Any]],
    archived: dict[int, dict[int, dict[str, int]]],
    official: dict[int, dict[int, dict[str, int]]],
) -> list[dict[str, Any]]:
    season_for = {row["game_id"]: season_label(row["season"]) for row in sample}
    result = []
    for game_id in sorted(season_for):
        a, o = archived.get(game_id, {}), official.get(game_id, {})
        for player_id in sorted(set(a) | set(o)):
            av, ov = a.get(player_id), o.get(player_id)
            result.append({
                "game_id": game_id,
                "season": season_for[game_id],
                "player_id": player_id,
                "archived_saves": "" if av is None else av["saves"],
                "official_saves": "" if ov is None else ov["saves"],
                "archived_sa": "" if av is None else av["sa"],
                "official_sa": "" if ov is None else ov["sa"],
                "archived_ga": "" if av is None else av["ga"],
                "official_ga": "" if ov is None else ov["ga"],
            })
    return result


def signed_hist(diffs: list[int]) -> dict[str, int]:
    hist = {f"neg{abs(value)}" if value < 0 else ("zero" if value == 0 else f"pos{value}"): 0 for value in HIST_BINS}
    hist["abs_2plus"] = 0
    hist["abs_gt3"] = 0
    for diff in diffs:
        key = f"neg{abs(diff)}" if diff < 0 else ("zero" if diff == 0 else f"pos{diff}")
        if key in hist:
            hist[key] += 1
        if abs(diff) >= 2:
            hist["abs_2plus"] += 1
        if abs(diff) > 3:
            hist["abs_gt3"] += 1
    return hist


def swap_stats(by_game: dict[int, dict[int, int]]) -> dict[str, int]:
    pairs = players_paired = other_players = swap_only_games = games_other = 0
    for diffs in by_game.values():
        nonzero = {pid: diff for pid, diff in diffs.items() if diff != 0}
        if not nonzero:
            continue
        magnitude_counts: dict[int, Counter[str]] = defaultdict(Counter)
        for diff in nonzero.values():
            magnitude_counts[abs(diff)]["pos" if diff > 0 else "neg"] += 1
        game_pairs = sum(min(counts["pos"], counts["neg"]) for counts in magnitude_counts.values())
        paired_players = game_pairs * 2
        pairs += game_pairs
        players_paired += paired_players
        other_players += len(nonzero) - paired_players
        if len(nonzero) == paired_players:
            swap_only_games += 1
        else:
            games_other += 1
    return {
        "swap_pairs": pairs,
        "players_in_swap_pairs": players_paired,
        "other_mismatch_players": other_players,
        "swap_only_games": swap_only_games,
        "games_with_other_mismatch_shape": games_other,
    }


def line_impact(
    archive_values: dict[tuple[int, int], int],
    official_values: dict[tuple[int, int], int],
    line: float,
) -> dict[str, Any]:
    keys = sorted(set(archive_values) & set(official_values))
    if not keys:
        return {"n": 0, "archived_base_rate": "", "official_base_rate": "", "archived_base_brier_on_official": "", "official_base_brier_on_official": "", "side_flips": 0, "side_flip_share": ""}
    archive_y = [int(archive_values[key] > line) for key in keys]
    official_y = [int(official_values[key] > line) for key in keys]
    pa = sum(archive_y) / len(keys)
    po = sum(official_y) / len(keys)
    brier_a = sum((pa - outcome) ** 2 for outcome in official_y) / len(keys)
    brier_o = sum((po - outcome) ** 2 for outcome in official_y) / len(keys)
    flips = sum(a != o for a, o in zip(archive_y, official_y))
    return {
        "n": len(keys),
        "archived_base_rate": pa,
        "official_base_rate": po,
        "archived_base_brier_on_official": brier_a,
        "official_base_brier_on_official": brier_o,
        "side_flips": flips,
        "side_flip_share": flips / len(keys),
    }


def make_summary(
    sample: list[dict[str, Any]],
    failed: dict[int, str],
    archive_skaters: dict[int, dict[int, int]],
    official_skaters: dict[int, dict[int, int]],
    archive_goalies: dict[int, dict[int, dict[str, int]]],
    official_goalies: dict[int, dict[int, dict[str, int]]],
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    fields: list[str] = [
        "season", "games_requested", "games_fetched", "games_failed",
        "skater_archive_rows", "skater_official_rows", "skater_shared_rows",
        "skater_archive_only_rows", "skater_official_only_rows", "skater_exact_rows",
        "skater_mismatch_rows", "skater_exact_union_rate", "skater_exact_shared_rate",
        "skater_games_with_mismatch", "skater_game_mismatch_share", "skater_games_2plus_mismatches",
        "skater_swap_pairs", "skater_players_in_swap_pairs", "skater_other_mismatch_players",
        "skater_swap_only_games", "skater_games_with_other_mismatch_shape",
    ]
    for key in ("neg3", "neg2", "neg1", "zero", "pos1", "pos2", "pos3", "abs_2plus", "abs_gt3"):
        fields.append(f"sog_diff_{key}")
    fields.extend([
        "goalie_archive_rows", "goalie_official_rows", "goalie_shared_rows",
        "goalie_archive_only_rows", "goalie_official_only_rows", "goalie_official_only_zero_stat_rows",
        "goalie_official_only_nonzero_stat_rows", "goalie_exact_rows",
        "goalie_mismatch_rows", "goalie_exact_union_rate", "goalie_exact_shared_rate",
        "goalie_games_with_mismatch", "goalie_game_mismatch_share", "goalie_games_2plus_mismatches",
    ])
    for metric in ("saves", "sa", "ga"):
        for key in ("neg3", "neg2", "neg1", "zero", "pos1", "pos2", "pos3", "abs_2plus", "abs_gt3"):
            fields.append(f"goalie_{metric}_diff_{key}")
        for key in ("swap_pairs", "players_in_swap_pairs", "other_mismatch_players", "swap_only_games", "games_with_other_mismatch_shape"):
            fields.append(f"goalie_{metric}_{key}")
    impact_specs: list[tuple[str, float, str]] = []
    for stat, lines in (("sog", SOG_LINES), ("saves", SAVE_LINES)):
        for line in lines:
            key = f"{stat}_{str(line).replace('.', '_')}"
            impact_specs.append((stat, line, key))
            fields.extend([
                f"{key}_paired_player_games", f"{key}_archived_base_rate", f"{key}_official_base_rate",
                f"{key}_archived_base_brier_on_official", f"{key}_official_base_brier_on_official",
                f"{key}_side_flips", f"{key}_side_flip_share",
            ])

    def summarize_scope(scope_games: list[dict[str, Any]], label: str) -> dict[str, Any]:
        game_ids = {row["game_id"] for row in scope_games}
        sk_a = {gid: archive_skaters.get(gid, {}) for gid in game_ids}
        sk_o = {gid: official_skaters.get(gid, {}) for gid in game_ids}
        go_a = {gid: archive_goalies.get(gid, {}) for gid in game_ids}
        go_o = {gid: official_goalies.get(gid, {}) for gid in game_ids}
        result: dict[str, Any] = {
            "season": label,
            "games_requested": len(scope_games),
            "games_fetched": sum(gid not in failed for gid in game_ids),
            "games_failed": sum(gid in failed for gid in game_ids),
        }
        sk_a_pairs = {(gid, pid): value for gid, players in sk_a.items() for pid, value in players.items()}
        sk_o_pairs = {(gid, pid): value for gid, players in sk_o.items() for pid, value in players.items()}
        sk_union = set(sk_a_pairs) | set(sk_o_pairs)
        sk_shared = set(sk_a_pairs) & set(sk_o_pairs)
        sk_diff_by_game: dict[int, dict[int, int]] = defaultdict(dict)
        sk_diffs: list[int] = []
        sk_exact = sk_mismatch_rows = 0
        sk_game_mismatch_rows: Counter[int] = Counter()
        for key in sk_union:
            av, ov = sk_a_pairs.get(key), sk_o_pairs.get(key)
            if av is not None and ov is not None and av == ov:
                sk_exact += 1
            else:
                sk_mismatch_rows += 1
                sk_game_mismatch_rows[key[0]] += 1
            if av is not None and ov is not None:
                diff = av - ov
                sk_diffs.append(diff)
                if diff:
                    sk_diff_by_game[key[0]][key[1]] = diff
        sk_swap = swap_stats(sk_diff_by_game)
        sk_hist = signed_hist(sk_diffs)
        result.update({
            "skater_archive_rows": len(sk_a_pairs),
            "skater_official_rows": len(sk_o_pairs),
            "skater_shared_rows": len(sk_shared),
            "skater_archive_only_rows": len(set(sk_a_pairs) - set(sk_o_pairs)),
            "skater_official_only_rows": len(set(sk_o_pairs) - set(sk_a_pairs)),
            "skater_exact_rows": sk_exact,
            "skater_mismatch_rows": sk_mismatch_rows,
            "skater_exact_union_rate": sk_exact / len(sk_union) if sk_union else "",
            "skater_exact_shared_rate": (len(sk_shared) - sum(diff != 0 for diff in sk_diffs)) / len(sk_shared) if sk_shared else "",
            "skater_games_with_mismatch": sum(v > 0 for v in sk_game_mismatch_rows.values()),
            "skater_game_mismatch_share": sum(v > 0 for v in sk_game_mismatch_rows.values()) / len(scope_games) if scope_games else "",
            "skater_games_2plus_mismatches": sum(v >= 2 for v in sk_game_mismatch_rows.values()),
            **{f"skater_{key}": value for key, value in sk_swap.items()},
            **{f"sog_diff_{key}": value for key, value in sk_hist.items()},
        })

        go_a_pairs = {(gid, pid): value for gid, players in go_a.items() for pid, value in players.items()}
        go_o_pairs = {(gid, pid): value for gid, players in go_o.items() for pid, value in players.items()}
        go_union = set(go_a_pairs) | set(go_o_pairs)
        go_shared = set(go_a_pairs) & set(go_o_pairs)
        go_official_only = set(go_o_pairs) - set(go_a_pairs)
        go_official_only_zero = sum(
            all(go_o_pairs[key][metric] == 0 for metric in ("saves", "sa", "ga"))
            for key in go_official_only
        )
        go_exact = go_mismatch_rows = 0
        go_game_mismatch_rows: Counter[int] = Counter()
        for key in go_union:
            av, ov = go_a_pairs.get(key), go_o_pairs.get(key)
            if av is not None and ov is not None and all(av[m] == ov[m] for m in ("saves", "sa", "ga")):
                go_exact += 1
            else:
                go_mismatch_rows += 1
                go_game_mismatch_rows[key[0]] += 1
        result.update({
            "goalie_archive_rows": len(go_a_pairs),
            "goalie_official_rows": len(go_o_pairs),
            "goalie_shared_rows": len(go_shared),
            "goalie_archive_only_rows": len(set(go_a_pairs) - set(go_o_pairs)),
            "goalie_official_only_rows": len(go_official_only),
            "goalie_official_only_zero_stat_rows": go_official_only_zero,
            "goalie_official_only_nonzero_stat_rows": len(go_official_only) - go_official_only_zero,
            "goalie_exact_rows": go_exact,
            "goalie_mismatch_rows": go_mismatch_rows,
            "goalie_exact_union_rate": go_exact / len(go_union) if go_union else "",
            "goalie_exact_shared_rate": (sum(all(go_a_pairs[key][m] == go_o_pairs[key][m] for m in ("saves", "sa", "ga")) for key in go_shared) / len(go_shared)) if go_shared else "",
            "goalie_games_with_mismatch": sum(v > 0 for v in go_game_mismatch_rows.values()),
            "goalie_game_mismatch_share": sum(v > 0 for v in go_game_mismatch_rows.values()) / len(scope_games) if scope_games else "",
            "goalie_games_2plus_mismatches": sum(v >= 2 for v in go_game_mismatch_rows.values()),
        })
        for metric in ("saves", "sa", "ga"):
            by_game: dict[int, dict[int, int]] = defaultdict(dict)
            diffs = []
            for gid, pid in go_shared:
                diff = go_a_pairs[(gid, pid)][metric] - go_o_pairs[(gid, pid)][metric]
                diffs.append(diff)
                if diff:
                    by_game[gid][pid] = diff
            result.update({f"goalie_{metric}_diff_{k}": v for k, v in signed_hist(diffs).items()})
            result.update({f"goalie_{metric}_{k}": v for k, v in swap_stats(by_game).items()})

        for stat, line, key in impact_specs:
            if stat == "sog":
                a_values = {(gid, pid): value for gid, players in sk_a.items() for pid, value in players.items()}
                o_values = {(gid, pid): value for gid, players in sk_o.items() for pid, value in players.items()}
            else:
                a_values = {(gid, pid): value["saves"] for gid, players in go_a.items() for pid, value in players.items()}
                o_values = {(gid, pid): value["saves"] for gid, players in go_o.items() for pid, value in players.items()}
            impact = line_impact(a_values, o_values, line)
            result[f"{key}_paired_player_games"] = impact["n"]
            result[f"{key}_archived_base_rate"] = impact["archived_base_rate"]
            result[f"{key}_official_base_rate"] = impact["official_base_rate"]
            result[f"{key}_archived_base_brier_on_official"] = impact["archived_base_brier_on_official"]
            result[f"{key}_official_base_brier_on_official"] = impact["official_base_brier_on_official"]
            result[f"{key}_side_flips"] = impact["side_flips"]
            result[f"{key}_side_flip_share"] = impact["side_flip_share"]
        return result

    summary = [summarize_scope([row for row in sample if row["season"] == year], label)
               for year, label in SEASON_LABELS.items()]
    summary.append(summarize_scope(sample, "TOTAL"))
    return fields, summary, {"impact_specs": impact_specs}


def measurement_digest(artifacts: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(artifacts):
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(artifacts[name]).digest())
    return digest.hexdigest()


def pct(value: Any) -> str:
    return "n/a" if value == "" or value is None else f"{float(value) * 100:.3f}%"


def num(value: Any) -> str:
    return "n/a" if value == "" or value is None else f"{float(value):.6f}"


def official_only_goalie_details(rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    zero_stat_zero_toi = 0
    nonzero_details: list[str] = []
    for row in rows:
        if row["archived_saves"] != "" or row["official_saves"] == "":
            continue
        payload = decode_boxscore(
            gzip.decompress(cache_path(int(row["game_id"])).read_bytes()), int(row["game_id"])
        )
        found = []
        for side in ("awayTeam", "homeTeam"):
            found.extend(
                player
                for player in payload["playerByGameStats"][side]["goalies"]
                if int(player["playerId"]) == int(row["player_id"])
            )
        if len(found) != 1:
            raise ValueError(
                f"official-only goalie not unique in cached boxscore: {row['game_id']}/{row['player_id']}"
            )
        player = found[0]
        all_zero = all(int(row[key]) == 0 for key in ("official_saves", "official_sa", "official_ga"))
        toi = str(player.get("toi", "MISSING"))
        if all_zero and toi == "00:00":
            zero_stat_zero_toi += 1
        if not all_zero:
            nonzero_details.append(
                f"game_id={row['game_id']} season={row['season']} player_id={row['player_id']} "
                f"saves={row['official_saves']} shotsAgainst={row['official_sa']} "
                f"goalsAgainst={row['official_ga']} toi={toi}"
            )
    return zero_stat_zero_toi, nonzero_details


def render_results(
    sample: list[dict[str, Any]],
    failed: dict[int, str],
    summary: list[dict[str, Any]],
    impact_specs: list[tuple[str, float, str]],
    sog_rows: list[dict[str, Any]],
    goalie_compare_rows: list[dict[str, Any]],
    digest: str,
) -> str:
    total = summary[-1]
    zero_toi_count, nonzero_goalie_details = official_only_goalie_details(goalie_compare_rows)
    sample_hash = sha256("".join(f"{r['season']}:{r['game_id']}\n" for r in sample).encode())
    lines = [
        "# NHL per-player outcome reconciliation",
        "",
        "This is an outcome-quality audit only. It contains no fitting, forecast, ROI, threshold, keep-rule, or market test.",
        "The boxscore outcomes are from NHL GameCenter `playerByGameStats`; the comparison rows join only by numeric `playerId`.",
        "",
        "## Sampling and coverage",
        "",
        "- Official instrument: `GET https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore`, queried on 2026-10-20, one game per request, sequentially. Raw response bodies are committed as gzip JSON.",
        "- Archive instrument: read-only `/root/nhl_database_2025-26-playoffs.duckdb`; skaters from `skaters_gamelogs` with `situation='all'` and `I_F_shotsOnGoal`; goalies from `goalies_gamelogs` with `situation='all'`, saves calculated as `ongoal - goals`.",
        f"- Canonical frame: {EXPECTED_FRAME_TOTAL:,} regular-season games, start seasons 2018–2022, through {CUTOFF}; frame SHA256 `{EXPECTED_FRAME_SHA256}`.",
        f"- Sample: {len(sample)} games, 60 per season block, seed `{SEED}`, sorted-game-id input; sample game-id SHA256 `{sample_hash}`.",
        f"- Anchor game `{ANCHOR_GAME_ID}` was forced into the 2018–19 block by drawing 59 additional games there; other blocks draw 60 uniformly from their game-id-sorted frame.",
        f"- Games requested: {total['games_requested']}; fetched and cached: {total['games_fetched']}; failed: {total['games_failed']}.",
        f"- Player-rows compared: {total['skater_shared_rows']:,} shared skater rows; {total['skater_archive_only_rows']:,} archive-only and {total['skater_official_only_rows']:,} official-only rows are listed separately. Goalies: {total['goalie_shared_rows']:,} shared rows; {total['goalie_archive_only_rows']:,} archive-only and {total['goalie_official_only_rows']:,} official-only. Among official-only goalie rows, {total['goalie_official_only_zero_stat_rows']:,} have zero saves, shots against, and goals against.",
        "- Every failed request is reported below as FAILED and is excluded from player-missing counts. No failed requests are expected in a complete sample.",
        "",
        "The final block is a partial 2022–23 slice: the canonical frame contains 343 games through November 27, 2022, not a full season. The SBR predecessor archive contains 339 of those games; this audit samples from all canonical games in the declared frame.",
        "",
        "## Skater SOG agreement",
        "",
        f"- Exact agreement: {total['skater_exact_rows']:,}/{total['skater_archive_rows'] + total['skater_official_only_rows']:,} union player-rows = {pct(total['skater_exact_union_rate'])}. On shared rows only: {total['skater_exact_rows']:,}/{total['skater_shared_rows']:,} = {pct(total['skater_exact_shared_rate'])}.",
        f"- Games with at least one row mismatch (including one-sided player rows): {total['skater_games_with_mismatch']}/{total['games_fetched']} = {pct(total['skater_game_mismatch_share'])}. Games with 2+ mismatching player-rows: {total['skater_games_2plus_mismatches']}.",
        f"- Signed diff is archived SOG minus official SOG. Histogram on shared rows: {', '.join(f'{key}={total[f'sog_diff_{key}']}' for key in ('neg3','neg2','neg1','zero','pos1','pos2','pos3','abs_2plus','abs_gt3'))}.",
        f"- Swap analysis among numeric mismatches: {total['skater_swap_pairs']} equal-size opposite-sign swap pairs cover {total['skater_players_in_swap_pairs']} player-rows; {total['skater_other_mismatch_players']} mismatching players remain outside a pair; {total['skater_swap_only_games']} mismatch games are entirely explained by pairs; {total['skater_games_with_other_mismatch_shape']} have another shape.",
        f"- Residual mismatch shape: {total['skater_other_mismatch_players']} shared-row numeric mismatches remain after swap pairing, plus {total['skater_archive_only_rows']} archive-only and {total['skater_official_only_rows']} official-only player-rows.",
        "",
        "## Goalie outcome agreement",
        "",
        f"- A goalie row is exact only when saves, shotsAgainst, and goalsAgainst all agree. Exact: {total['goalie_exact_rows']:,}/{total['goalie_archive_rows'] + total['goalie_official_only_rows']:,} union rows = {pct(total['goalie_exact_union_rate'])}; shared rows only = {pct(total['goalie_exact_shared_rate'])}.",
        f"- The official `.goalies` arrays include {total['goalie_official_only_zero_stat_rows']:,} official-only rows with all three fields zero; {zero_toi_count:,} also have official `toi=00:00`. These are retained as one-sided entries per the parsing specification and are non-appearing goalie slots.",
        f"- Official-only nonzero goalie rows: {total['goalie_official_only_nonzero_stat_rows']}. " + ("; ".join(nonzero_goalie_details) if nonzero_goalie_details else "None."),
        f"- Games with at least one goalie-row mismatch: {total['goalie_games_with_mismatch']}/{total['games_fetched']} = {pct(total['goalie_game_mismatch_share'])}; games with 2+ mismatching goalie rows: {total['goalie_games_2plus_mismatches']}.",
        "- Signed field diff is archived minus official. For each field the histogram includes exact signed bins −3 through +3, an absolute 2+ count, and an absolute >3 overflow count. Swap pairs use equal-size opposite-sign field diffs within the same game.",
        "",
        "| Field | -3 | -2 | -1 | 0 | +1 | +2 | +3 | abs 2+ | abs >3 | swap pairs | other mismatch players |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric, title in (("saves", "Saves"), ("sa", "Shots against"), ("ga", "Goals against")):
        lines.append(
            f"| {title} | " + " | ".join(str(total[f"goalie_{metric}_diff_{k}"]) for k in ("neg3","neg2","neg1","zero","pos1","pos2","pos3","abs_2plus","abs_gt3")) +
            f" | {total[f'goalie_{metric}_swap_pairs']} | {total[f'goalie_{metric}_other_mismatch_players']} |"
        )
    lines.extend([
        "",
        "## Per-season coverage and agreement",
        "",
        "| Season block | Games fetched | Skater shared rows | SOG exact / union | Games with SOG mismatch | SOG swap pairs | Goalie shared rows | Official-only zero goalie rows | Nonzero goalie rows | Goalie exact / union | Games with goalie mismatch |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in summary:
        lines.append(
            f"| {row['season']} | {row['games_fetched']}/{row['games_requested']} | {row['skater_shared_rows']} | {row['skater_exact_rows']}/{row['skater_archive_rows'] + row['skater_official_only_rows']} ({pct(row['skater_exact_union_rate'])}) | {row['skater_games_with_mismatch']}/{row['games_fetched']} | {row['skater_swap_pairs']} | {row['goalie_shared_rows']} | {row['goalie_official_only_zero_stat_rows']} | {row['goalie_official_only_nonzero_stat_rows']} | {row['goalie_exact_rows']}/{row['goalie_archive_rows'] + row['goalie_official_only_rows']} ({pct(row['goalie_exact_union_rate'])}) | {row['goalie_games_with_mismatch']}/{row['games_fetched']} |"
        )
    lines.extend([
        "",
        "## Impact without a model",
        "",
        "This is a data-quality demonstration, not a model and not a market test. Each base rate is a constant over the paired player-games with both archived and official outcomes. Each Brier score evaluates that constant on the official over/under outcome. A side flip is an archived-versus-official over/under disagreement; missing one-sided player rows are disclosed above and are not imputed into this paired denominator.",
        "",
        "| Market stat | Line | Paired player-games | Archived base rate | Official base rate | Archived constant Brier on official | Official constant Brier on official | Side flips | Flip share |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for stat, line, key in impact_specs:
        lines.append(
            f"| {stat.upper()} | {line:.1f} | {total[f'{key}_paired_player_games']} | {pct(total[f'{key}_archived_base_rate'])} | {pct(total[f'{key}_official_base_rate'])} | {num(total[f'{key}_archived_base_brier_on_official'])} | {num(total[f'{key}_official_base_brier_on_official'])} | {total[f'{key}_side_flips']} | {pct(total[f'{key}_side_flip_share'])} |"
        )
    lines.extend([
        "",
        "## Verdict",
        "",
        "The verdict is computed by the signed rule in the audit brief. A random sample of 60 games per block estimates agreement only for these observed games; it cannot certify every game in the archive or establish performance in future seasons. In particular, the earlier 2-of-36 anchor-game discrepancy is not by itself a population estimate; it is retained here as a required sample game.",
    ])
    all_sog_flips = [total[f"{key}_side_flip_share"] for stat, _, key in impact_specs if stat == "sog"]
    all_save_flips = [total[f"{key}_side_flip_share"] for stat, _, key in impact_specs if stat == "saves"]
    all_flips = [v for v in all_sog_flips + all_save_flips if v != ""]
    swap_explained = (
        total["skater_other_mismatch_players"] == 0
        and total["skater_archive_only_rows"] == 0
        and total["skater_official_only_rows"] == 0
    )
    settlement = (
        float(total["skater_exact_union_rate"]) >= 0.995
        and total["skater_games_2plus_mismatches"] == 0
        and all(value <= 0.005 for value in all_flips)
    )
    usable = swap_explained and all(value <= 0.02 for value in all_flips)
    if settlement:
        verdict = "SETTLEMENT_GRADE"
        reason = "All three settlement-grade conditions pass."
    elif usable:
        verdict = "USABLE_WITH_CORRECTION"
        reason = "Every numeric SOG mismatch is an observed swap pair, there are no one-sided skater rows, and every listed side-flip share is at most 2%; use only with an explicit per-player correction step that is itself audited."
    else:
        verdict = "NOT_SETTLEMENT_GRADE"
        reason = "At least one signed settlement-grade or correction condition fails. The lowest-cost official import is one NHL GameCenter boxscore request for each of the 4,876 games in this canonical frame (4,876 sequential requests total; 300 sampled responses are already cached, so 4,576 additional requests remain). Import playerId plus SOG for forwards/defense and playerId plus saves, shotsAgainst, goalsAgainst, and goalie toi for goalies so zero-minute backup slots can be distinguished; retain raw gzip responses under this artifact's cache/ and write a normalized research-only player-game CSV beside the results. Do not start that import in this task."
    lines.extend([
        f"- **{verdict}.** {reason}",
        f"- Decision measurements: SOG union exact agreement is {pct(total['skater_exact_union_rate'])} (passes the 99.5% floor); {total['skater_games_2plus_mismatches']} games have 2+ skater mismatches (fails the zero-game condition); maximum listed side-flip share is {pct(max(all_flips) if all_flips else '')} (passes both caps). The correction rule still fails: {total['skater_other_mismatch_players']} shared numeric SOG mismatches are outside swap pairs, with {total['skater_archive_only_rows']} archive-only and {total['skater_official_only_rows']} official-only skater rows.",
        "",
        "## Failed requests",
        "",
    ])
    if failed:
        for game_id, error in sorted(failed.items()):
            lines.append(f"- FAILED `game_id={game_id}`: {error}")
    else:
        lines.append("- None.")
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Run offline: `/root/lp-goalie-research/.venv/bin/python research/nhl/prop-feasibility-2026-10-20/recon.py`.",
        "- The default run makes no network requests and requires all 300 committed `.json.gz` cache files plus the read-only canonical CSV and DuckDB source paths embedded in `recon.py`.",
        f"- Pinned measurement digest (the three CSV artifacts): `{digest}`.",
        "- The script exits nonzero if the canonical frame hash, sample hash, schema, row identity, cache completeness, or pinned CSV measurement digest changes.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="fetch and cache missing boxscores; otherwise run offline")
    parser.add_argument("--probe-only", action="store_true", help="fetch/parse only the required anchor game")
    parser.add_argument("--canonical", type=Path, default=CANONICAL)
    parser.add_argument("--duckdb", type=Path, default=DUCKDB)
    args = parser.parse_args()
    if args.probe_only and not args.fetch:
        parser.error("--probe-only requires --fetch")
    frame = canonical_frame(args.canonical)
    sample = draw_sample(frame)
    sample_hash = sha256("".join(f"{r['season']}:{r['game_id']}\n" for r in sample).encode())
    print(
        f"FRAME games={len(frame)} seasons={dict(Counter(r['season'] for r in frame))} "
        f"sha256={EXPECTED_FRAME_SHA256}"
    )
    print(f"SAMPLE games={len(sample)} seed={SEED} game_id_sha256={sample_hash}")
    print("SAMPLE_GAME_IDS " + ",".join(str(row["game_id"]) for row in sample))
    if args.fetch:
        try:
            fetch_errors = fetch_missing(sample, probe_only=args.probe_only)
        except BulkAccessRefused as exc:
            print(f"STOP {exc}", file=sys.stderr)
            return 2
        if args.probe_only:
            return 0 if not fetch_errors else 2
    else:
        fetch_errors = {}

    official_skaters, official_goalies = load_official_cache(sample)
    archive_skaters, archive_goalies = load_archived(sample, args.duckdb)
    sog = player_sog_rows(sample, archive_skaters, official_skaters)
    goalie = goalie_rows(sample, archive_goalies, official_goalies)
    summary_fields, summary, extras = make_summary(
        sample, fetch_errors, archive_skaters, official_skaters,
        archive_goalies, official_goalies,
    )
    artifacts = {
        "per_player_sog_compare.csv": csv_bytes(
            ["game_id", "season", "player_id", "archived_sog", "official_sog", "diff"], sog
        ),
        "per_goalie_compare.csv": csv_bytes(
            ["game_id", "season", "player_id", "archived_saves", "official_saves", "archived_sa", "official_sa", "archived_ga", "official_ga"], goalie
        ),
        "recon_summary.csv": csv_bytes(summary_fields, summary),
    }
    digest = measurement_digest(artifacts)
    if EXPECTED_MEASUREMENT_SHA256 and digest != EXPECTED_MEASUREMENT_SHA256:
        raise ValueError(
            f"PINNED MEASUREMENT CHANGED: {digest} != {EXPECTED_MEASUREMENT_SHA256}; "
            "outputs were not overwritten"
        )
    markdown = render_results(
        sample, fetch_errors, summary, extras["impact_specs"], sog, goalie, digest
    ).encode("utf-8")
    for name, body in artifacts.items():
        (HERE / name).write_bytes(body)
    (HERE / "RESULTS-RECON.md").write_bytes(markdown)
    print(
        f"RESULTS requested={summary[-1]['games_requested']} fetched={summary[-1]['games_fetched']} "
        f"failed={summary[-1]['games_failed']} skater_shared={summary[-1]['skater_shared_rows']} "
        f"goalie_shared={summary[-1]['goalie_shared_rows']} measurement_sha256={digest}"
    )
    return 0 if not fetch_errors else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
