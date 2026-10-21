#!/usr/bin/env python3
"""Frame-level game/player ID reconciliation against the official-label foundation.

Full frame, no sample: all 4,876 regular-season games in the pinned
`canonical_frame.csv`. For every game this reads the already-imported official
boxscore body, extracts the player IDs the boxscore itself carries, and compares
them with the IDs the label tables published for that game.

The question is narrow and mechanical: **does an ID in one place exist in the
other?** A player who appears in the boxscore but not the label table is a
reconciliation failure, not a modelling detail — any event feed joined later
would either drop him or attach his events to the wrong person.

Read-only. Fits nothing.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = HERE.parent / "official-outcome-backfill-2026-10-20"
RAW = Path("/root/lp-data/nhl-official-outcome-backfill-2026-10-20/raw")


def label_ids() -> tuple[dict, dict, dict]:
    skaters: dict[str, set] = defaultdict(set)
    goalies: dict[str, set] = defaultdict(set)
    seasons: dict[str, int] = {}
    with (LABELS / "official_skater_outcomes.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                skaters[r["game_id"]].add(int(r["player_id"]))
            except ValueError:
                continue
            seasons[r["game_id"]] = int(r["season"])
    with (LABELS / "official_goalie_outcomes.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                goalies[r["game_id"]].add(int(r["player_id"]))
            except ValueError:
                continue
            seasons.setdefault(r["game_id"], int(r["season"]))
    return skaters, goalies, seasons


def box_ids(gid: str) -> tuple[set, set] | None:
    p = RAW / f"{gid}.json.gz"
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        box = json.load(fh)
    # playerByGameStats is top-level: {homeTeam|awayTeam: {forwards, defense, goalies}}
    stats = box.get("playerByGameStats") or {}
    out = []
    for side in ("homeTeam", "awayTeam"):
        ids = set()
        for group in (stats.get(side) or {}).values():
            for row in group or []:
                pid = row.get("playerId")
                if pid is not None:
                    ids.add(int(pid))
        out.append(ids)
    return out[0], out[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE))
    args = ap.parse_args()

    skaters, goalies, seasons = label_ids()
    with (LABELS / "canonical_frame.csv").open(newline="", encoding="utf-8") as fh:
        frame = list(csv.DictReader(fh))

    rows, issues = [], []
    for g in frame:
        gid = g["game_id"]
        season = int(g["season"])
        box = box_ids(gid)
        label = skaters.get(gid, set()) | goalies.get(gid, set())
        if box is None:
            issues.append({"game_id": gid, "season": season, "issue": "BOXSCORE_MISSING",
                           "detail": "no imported boxscore body"})
            rows.append({"game_id": gid, "season": season, "box_ids": 0, "label_ids": len(label),
                         "only_in_box": 0, "only_in_label": 0, "agree": 0})
            continue
        boxed = box[0] | box[1]
        only_box = boxed - label
        only_label = label - boxed
        if only_box:
            issues.append({"game_id": gid, "season": season, "issue": "PLAYER_ID_ONLY_IN_BOXSCORE",
                           "detail": ";".join(str(x) for x in sorted(only_box)[:10])})
        if only_label:
            issues.append({"game_id": gid, "season": season, "issue": "PLAYER_ID_ONLY_IN_LABELS",
                           "detail": ";".join(str(x) for x in sorted(only_label)[:10])})
        if not label:
            issues.append({"game_id": gid, "season": season, "issue": "NO_LABEL_ROWS",
                           "detail": "game has a boxscore but no label rows"})
        rows.append({"game_id": gid, "season": season, "box_ids": len(boxed), "label_ids": len(label),
                     "only_in_box": len(only_box), "only_in_label": len(only_label),
                     "agree": len(boxed & label)})

    out = Path(args.out)
    with (out / "frame_id_reconciliation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with (out / "frame_id_issues.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["game_id", "season", "issue", "detail"])
        w.writeheader()
        w.writerows(issues)

    by_season = {}
    for r in rows:
        s = by_season.setdefault(r["season"], {"games": 0, "players": 0, "only_box": 0, "only_label": 0,
                                               "games_disagreeing": 0})
        s["games"] += 1
        s["players"] += r["label_ids"]
        s["only_box"] += r["only_in_box"]
        s["only_label"] += r["only_in_label"]
        s["games_disagreeing"] += 1 if (r["only_in_box"] or r["only_in_label"] or not r["label_ids"]) else 0

    with (out / "frame_id_by_season.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["season", "games", "player_slots", "only_in_box",
                                           "only_in_label", "games_disagreeing"])
        w.writeheader()
        for season in sorted(by_season):
            s = by_season[season]
            w.writerow({"season": season, "games": s["games"], "player_slots": s["players"],
                        "only_in_box": s["only_box"], "only_in_label": s["only_label"],
                        "games_disagreeing": s["games_disagreeing"]})

    print(f"games: {len(rows)}  issues: {len(issues)}")
    print("issue counts:", dict(Counter(i["issue"] for i in issues)))
    for season in sorted(by_season):
        s = by_season[season]
        print(f"  {season}: {s['games']} games, {s['players']} label player-slots, "
              f"only-in-box {s['only_box']}, only-in-label {s['only_label']}, "
              f"disagreeing games {s['games_disagreeing']}")


if __name__ == "__main__":
    main()
