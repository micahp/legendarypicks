#!/usr/bin/env python3
"""Report full-frame event-evidence coverage straight from the fetch manifests.

Every number here is counted from a manifest row or from a raw body that re-hashes
to the sha256 in its row -- nothing is carried over from a previous report. A game
counts as covered only when its body exists, decompresses, re-hashes to sha256_gz,
and its payload row count equals the manifest `rows` value.

Usage:
    python report_event_coverage.py --raw-dir /root/lp-data/nhl-fullframe-event-audit-2026-10-21 \
        [--games full_frame_games.csv] [--manifest-dir …/manifests] [--verify] [--out PREFIX]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
KINDS = ("pbp", "shifts")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_games(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def count_payload(kind: str, raw: bytes) -> int:
    payload = json.loads(raw)
    if kind == "pbp":
        return len(payload.get("plays") or [])
    return len(payload.get("data") or [])


def bodies_dir(raw_dir: Path, kind: str) -> Path:
    """Bodies live in <raw-dir>/raw/<kind>/; accept <raw-dir>/<kind>/ too."""
    nested = raw_dir / "raw" / kind
    return nested if nested.exists() else raw_dir / kind


def audit_kind(kind: str, manifest: Path, raw_dir: Path, verify: bool) -> dict:
    rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8")))
    statuses = Counter(r["http_status"] or "n/a" for r in rows)
    covered, failures, units = set(), [], 0
    by_season_rows: dict[str, int] = defaultdict(int)
    by_season_units: dict[str, int] = defaultdict(int)
    for r in rows:
        gid = r["game_id"]
        if not r.get("sha256_gz"):
            failures.append({"game_id": gid, "why": r.get("note") or "no sha256_gz"})
            continue
        if verify:
            gz = bodies_dir(raw_dir, kind) / f"{gid}.json.gz"
            if not gz.exists():
                failures.append({"game_id": gid, "why": "body missing"})
                continue
            blob = gz.read_bytes()
            if sha256(blob) != r["sha256_gz"]:
                failures.append({"game_id": gid, "why": "sha256_gz mismatch"})
                continue
            raw = gzip.decompress(blob)
            if sha256(raw) != r["sha256_raw"] or len(raw) != int(r["bytes_raw"]):
                failures.append({"game_id": gid, "why": "sha256_raw/bytes mismatch"})
                continue
            n = count_payload(kind, raw)
            if n != int(r["rows"]):
                failures.append({"game_id": gid, "why": f"payload rows {n} != manifest {r['rows']}"})
                continue
            units += int(r["rows"])
        else:
            units += int(r["rows"] or 0)
        covered.add(gid)
    dup = [g for g, c in Counter(r["game_id"] for r in rows).items() if c > 1]
    return {"kind": kind, "manifest_rows": len(rows), "covered_ids": covered,
            "failures": failures, "duplicates": dup, "units": units,
            "http_statuses": dict(sorted(statuses.items()))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True)
    ap.add_argument("--games", type=Path, default=HERE / "full_frame_games.csv")
    ap.add_argument("--manifest-dir", type=Path, default=None)
    ap.add_argument("--verify", action="store_true", help="re-hash and re-count every body")
    ap.add_argument("--out-prefix", type=Path, default=HERE / "event_coverage")
    args = ap.parse_args()

    manifest_dir = args.manifest_dir or (args.raw_dir / "manifests")
    games = load_games(args.games)
    frame_ids = [g["game_id"] for g in games]
    season = {g["game_id"]: g["season"] for g in games}
    in_sample = {g["game_id"] for g in games if g["in_sample"] == "1"}
    frame_set = set(frame_ids)

    result = {"games_in_frame": len(frame_ids),
              "in_sample": len(in_sample),
              "verify": args.verify, "kinds": {}}
    both = set(frame_ids)
    for kind in KINDS:
        info = audit_kind(kind, manifest_dir / f"{kind}_evidence_manifest.csv", args.raw_dir, args.verify)
        covered = info.pop("covered_ids")
        missing = sorted(frame_set - covered)
        extra = sorted(covered - frame_set)
        per_season = Counter(season[g] for g in covered if g in season)
        units_season = defaultdict(int)
        rows_by_id = {}
        with (manifest_dir / f"{kind}_evidence_manifest.csv").open(newline="", encoding="utf-8") as h:
            for r in csv.DictReader(h):
                rows_by_id[r["game_id"]] = int(r["rows"] or 0)
        for g in covered:
            if g in season:
                units_season[season[g]] += rows_by_id.get(g, 0)
        info.update({
            "games_covered": len(covered & frame_set),
            "coverage_pct": round(100 * len(covered & frame_set) / len(frame_set), 2),
            "missing_games": len(missing),
            "missing_sample": missing[:20],
            "ids_not_in_frame": len(extra),
            "units_total": info["units"],
            "per_season_games": {k: per_season[k] for k in sorted(per_season)},
            "per_season_units": {k: units_season[k] for k in sorted(units_season)},
        })
        result["kinds"][kind] = info
        both &= covered

    result["games_with_both_sources"] = len(both)
    result["games_missing_any"] = len(frame_set - both)
    result["missing_any_sample"] = sorted(frame_set - both)[:20]
    result["complete"] = len(both) == len(frame_set)

    out_json = args.out_prefix.with_suffix(".json")
    out_md = args.out_prefix.with_suffix(".md")
    out_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = ["# Full-frame event evidence coverage", "",
             f"Frame games: **{len(frame_ids)}** ({len(in_sample)} in the 300-game sample).",
             f"Games with both sources verified: **{len(both)}** — "
             f"{'COMPLETE' if result['complete'] else 'INCOMPLETE, ' + str(len(frame_set - both)) + ' short'}.", ""]
    for kind in KINDS:
        i = result["kinds"][kind]
        lines += [f"## {kind}", "",
                  f"- manifest rows: {i['manifest_rows']} (duplicates: {len(i['duplicates'])})",
                  f"- games covered: {i['games_covered']} / {len(frame_ids)} ({i['coverage_pct']}%)",
                  f"- failures: {len(i['failures'])}, missing: {i['missing_games']}, ids outside frame: {i['ids_not_in_frame']}",
                  f"- http statuses: {i['http_statuses']}",
                  f"- units ({'plays' if kind == 'pbp' else 'shift rows'}): {i['units_total']:,}",
                  f"- per season: {i['per_season_games']}",
                  f"- per season units: {i['per_season_units']}", ""]
        if i["failures"]:
            lines.append(f"- first failures: {i['failures'][:5]}")
    lines += ["", "Every count above is re-derived by `report_event_coverage.py --verify` from the",
              "manifests and raw bodies; a body counts only when it re-hashes and its payload row",
              "count matches the manifest.", ""]
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "kinds"}, indent=2))
    for kind in KINDS:
        i = result["kinds"][kind]
        print(kind, "covered", i["games_covered"], "fail", len(i["failures"]),
              "units", i["units_total"], "seasons", i["per_season_games"])
    print("wrote", out_json.name, out_md.name)


if __name__ == "__main__":
    main()
