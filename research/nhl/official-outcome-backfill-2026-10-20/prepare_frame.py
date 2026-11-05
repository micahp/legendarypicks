#!/usr/bin/env python3
"""Freeze and reconcile the canonical 4,876-game frame for the outcome import."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CANONICAL = Path(
    "/root/lp-data/nhl-official-outcome-backfill-2026-10-20/source/"
    "canonical_games_source.csv"
)
DEFAULT_SBR = Path(
    "/root/lp-data/nhl-official-outcome-backfill-2026-10-20/source/"
    "sbr_games_2018_2023.jsonl.gz"
)
CANONICAL_SOURCE_SHA256 = "7cd2fc9a6e84470c177b704aa56ba328ad67522698244ce1f182ddcb9e439f52"
SBR_SOURCE_SHA256 = "a435454f4ec71b1ba3f612fde03b120438a7721a9a04e36f5aa2230e89ea273b"
FRAME_SHA256 = "336d8a8d055febd742dbf31ce7a613bd2e47c2cd8fbc7a8d956fc8967ba47b1c"
MARKET_COUNTS = {2018: 1271, 2019: 1082, 2020: 868, 2021: 1312, 2022: 339}
FRAME_COUNTS = {2018: 1271, 2019: 1082, 2020: 868, 2021: 1312, 2022: 343}
FRAME_TOTAL = 4876
MARKET_TOTAL = 4872
CUTOFF = "2022-11-27"

SBR_TEAM_CODES = {
    "Anaheim": ("ANA",), "Arizona": ("ARI", "PHX"), "Arizonas": ("ARI", "PHX"),
    "Boston": ("BOS",), "Buffalo": ("BUF",), "Calgary": ("CGY",),
    "Carolina": ("CAR",), "Chicago": ("CHI",), "Colorado": ("COL",),
    "Columbus": ("CBJ",), "Dallas": ("DAL",), "Detroit": ("DET",),
    "Edmonton": ("EDM",), "Florida": ("FLA",), "Los Angeles": ("LAK",),
    "LosAngeles": ("LAK",), "Minnesota": ("MIN",), "Montreal": ("MTL",),
    "NY Islanders": ("NYI",), "NYIslanders": ("NYI",),
    "NY Rangers": ("NYR",), "NYRangers": ("NYR",), "Nashville": ("NSH",),
    "New Jersey": ("NJD",), "NewJersey": ("NJD",), "Ottawa": ("OTT",),
    "Philadelphia": ("PHI",), "Pittsburgh": ("PIT",), "San Jose": ("SJS",),
    "SanJose": ("SJS",), "Seattle": ("SEA",), "Seattle Kraken": ("SEA",),
    "SeattleKraken": ("SEA",), "St. Louis": ("STL",), "St.Louis": ("STL",),
    "Tampa Bay": ("TBL",), "TampaBay": ("TBL",), "Toronto": ("TOR",),
    "Vancouver": ("VAN",), "Vegas": ("VGK",), "Washington": ("WSH",),
    "Winnipeg": ("WPG",),
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sbr_date(season_label: str, mmdd: Any) -> str:
    pieces = season_label.split("-")
    if len(pieces) != 2:
        raise ValueError(f"unexpected SBR season label: {season_label!r}")
    start_year = int(pieces[0])
    month, day = divmod(int(mmdd), 100)
    year = start_year if month >= 10 else start_year + 1
    return dt.date(year, month, day).isoformat()


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def prepare(canonical_source: Path, sbr_source: Path, output_dir: Path) -> None:
    for source, expected, label in (
        (canonical_source, CANONICAL_SOURCE_SHA256, "canonical source"),
        (sbr_source, SBR_SOURCE_SHA256, "SBR source"),
    ):
        if not source.is_file():
            raise FileNotFoundError(f"{label} missing: {source}")
        actual = file_sha256(source)
        if actual != expected:
            raise ValueError(f"{label} SHA256 changed: {actual} != {expected}")

    canonical_by_id: dict[int, dict[str, str]] = {}
    by_date_pair: dict[tuple[str, tuple[str, str]], list[dict[str, str]]] = defaultdict(list)
    with canonical_source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {
            "game_id", "season", "game_type", "game_date", "home_team", "away_team",
            "official_home_score", "official_away_score", "official_home_winner",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"canonical source missing columns: {sorted(required - set(reader.fieldnames or []))}")
        for row in reader:
            game_id = int(row["game_id"])
            if game_id in canonical_by_id:
                raise ValueError(f"duplicate canonical game_id={game_id}")
            canonical_by_id[game_id] = row
            key = (row["game_date"], tuple(sorted((row["home_team"], row["away_team"]))))
            by_date_pair[key].append(row)

    sbr_by_game: dict[int, dict[str, Any]] = {}
    sbr_rows = 0
    venue_order_mismatches = []
    with gzip.open(sbr_source, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"SBR line {line_number} is not an object")
            home_name, away_name = row["home"]["team"], row["away"]["team"]
            if home_name not in SBR_TEAM_CODES or away_name not in SBR_TEAM_CODES:
                raise ValueError(f"unmapped SBR teams at line {line_number}: {home_name}/{away_name}")
            date = parse_sbr_date(row["season"], row["date"])
            candidates: dict[int, dict[str, str]] = {}
            for home_code, away_code in product(SBR_TEAM_CODES[home_name], SBR_TEAM_CODES[away_name]):
                pair = tuple(sorted((home_code, away_code)))
                for candidate in by_date_pair.get((date, pair), []):
                    candidates[int(candidate["game_id"])] = candidate
            if len(candidates) != 1:
                raise ValueError(
                    f"SBR line {line_number} resolves to {len(candidates)} canonical games"
                )
            game_id, canonical = next(iter(candidates.items()))
            if game_id in sbr_by_game:
                raise ValueError(f"duplicate SBR canonical game_id={game_id}")
            sbr_by_game[game_id] = {
                "season_label": row["season"], "date": date,
                "home": home_name, "away": away_name,
                "home_code_options": SBR_TEAM_CODES[home_name],
                "away_code_options": SBR_TEAM_CODES[away_name],
            }
            sbr_rows += 1
            if (
                canonical["home_team"] not in SBR_TEAM_CODES[home_name]
                or canonical["away_team"] not in SBR_TEAM_CODES[away_name]
            ):
                venue_order_mismatches.append(game_id)

    if sbr_rows != 5132 or len(sbr_by_game) != 5132:
        raise ValueError(f"SBR crosswalk rows={sbr_rows}, unique games={len(sbr_by_game)}; expected 5132")
    if len(venue_order_mismatches) != 1:
        raise ValueError(f"venue-order mismatch count changed: {venue_order_mismatches}")

    market_regular = {
        game_id for game_id in sbr_by_game
        if int(canonical_by_id[game_id]["game_type"]) == 2
    }
    market_counts = Counter(int(canonical_by_id[gid]["season"]) for gid in market_regular)
    if len(market_regular) != MARKET_TOTAL or dict(market_counts) != MARKET_COUNTS:
        raise ValueError(f"SBR regular-season population changed: {len(market_regular)} {dict(market_counts)}")

    frame = []
    for game_id, row in canonical_by_id.items():
        season, game_date = int(row["season"]), row["game_date"]
        if not (2018 <= season <= 2022) or int(row["game_type"]) != 2 or game_date > CUTOFF:
            continue
        frame.append({
            "game_id": game_id,
            "season": season,
            "game_date": game_date,
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "canonical_home_score": row["official_home_score"],
            "canonical_away_score": row["official_away_score"],
            "canonical_home_winner": row["official_home_winner"],
            "in_sbr_market_archive": int(game_id in market_regular),
            "sbr_season_label": sbr_by_game.get(game_id, {}).get("season_label", ""),
            "sbr_home_team_name": sbr_by_game.get(game_id, {}).get("home", ""),
            "sbr_away_team_name": sbr_by_game.get(game_id, {}).get("away", ""),
            "sbr_venue_order_matches_canonical": (
                "" if game_id not in sbr_by_game else int(game_id not in venue_order_mismatches)
            ),
        })
    frame.sort(key=lambda row: (row["season"], row["game_id"]))
    counts = Counter(row["season"] for row in frame)
    if len(frame) != FRAME_TOTAL or dict(counts) != FRAME_COUNTS:
        raise ValueError(f"canonical frame changed: {len(frame)} {dict(counts)}")
    frame_bytes = "".join(
        f"{r['season']},{r['game_id']},{r['game_date']},{r['home_team']},{r['away_team']}\n"
        for r in frame
    ).encode()
    frame_hash = hashlib.sha256(frame_bytes).hexdigest()
    if frame_hash != FRAME_SHA256:
        raise ValueError(f"canonical frame hash changed: {frame_hash} != {FRAME_SHA256}")

    extra_ids = [row["game_id"] for row in frame if not row["in_sbr_market_archive"]]
    if len(extra_ids) != 4 or any(row["season"] != 2022 for row in frame if row["game_id"] in extra_ids):
        raise ValueError(f"canonical/SBR population difference changed: {extra_ids}")

    fields = list(frame[0])
    write_csv(output_dir / "canonical_frame.csv", fields, frame)
    if canonical_source.parent.resolve() != output_dir.resolve():
        write_csv(canonical_source.parent / "canonical_frame.csv", fields, frame)
    canonical_date_ranges = {}
    sbr_date_ranges = {}
    for season in sorted(counts):
        season_rows = [row for row in frame if row["season"] == season]
        market_rows = [row for row in season_rows if row["in_sbr_market_archive"]]
        canonical_date_ranges[str(season)] = [min(row["game_date"] for row in season_rows), max(row["game_date"] for row in season_rows)]
        if market_rows:
            sbr_date_ranges[str(season)] = [min(row["game_date"] for row in market_rows), max(row["game_date"] for row in market_rows)]
    metadata = {
        "canonical_source_sha256": CANONICAL_SOURCE_SHA256,
        "sbr_source_sha256": SBR_SOURCE_SHA256,
        "canonical_frame_sha256": frame_hash,
        "canonical_frame_games": len(frame),
        "canonical_frame_season_counts": {str(k): counts[k] for k in sorted(counts)},
        "canonical_frame_season_date_ranges": canonical_date_ranges,
        "sbr_regular_market_games": len(market_regular),
        "sbr_regular_season_counts": {str(k): market_counts[k] for k in sorted(market_counts)},
        "sbr_regular_market_season_date_ranges": sbr_date_ranges,
        "sbr_crosswalk_rows": sbr_rows,
        "sbr_venue_order_mismatch_game_ids": sorted(venue_order_mismatches),
        "canonical_only_game_ids": sorted(extra_ids),
        "canonical_cutoff": CUTOFF,
        "join_contract": "date + unordered canonical team pair; official outcomes use canonical numeric game_id",
    }
    metadata_text = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    (output_dir / "frame_sources.json").write_text(metadata_text, encoding="utf-8")
    if canonical_source.parent.resolve() != output_dir.resolve():
        (canonical_source.parent / "frame_sources.json").write_text(metadata_text, encoding="utf-8")
    print(
        f"FRAME_PASS canonical={len(frame)} seasons={dict(counts)} "
        f"SBR_market={len(market_regular)} SBR_all={sbr_rows} "
        f"canonical_only={extra_ids} venue_order_mismatch={venue_order_mismatches} "
        f"frame_sha256={frame_hash}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-source", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--sbr-source", type=Path, default=DEFAULT_SBR)
    parser.add_argument("--output-dir", type=Path, default=HERE)
    args = parser.parse_args()
    prepare(args.canonical_source, args.sbr_source, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
