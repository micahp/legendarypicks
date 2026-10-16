#!/usr/bin/env python3
"""Walk-forward diagnostics for the four canonical tennis point-event archives.

Reads the archives and picks.dev.db read-only. Match identities are crosswalked on tour,
season, normalized tournament, and both players. Only complete point histories whose point
count equals the result database's service-point total enter the historical model analysis.
The 2021 window calibrates match-level logistic models; 2022-24 is held out by year.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sqlite3
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
import tennis_match_sim as sim  # noqa: E402
import tennis_point_model as tpm  # noqa: E402

ARCHIVE_DIR = ROOT / "backend/data/tennis_point_archives"
ARCHIVES = [
    ("grand_slam_archive", ARCHIVE_DIR / "grand_slam_archive.db", 0),
    ("usopen", ARCHIVE_DIR / "usopen.db", 1),
    ("match_charting_project", ARCHIVE_DIR / "match_charting_project.db", 2),
    ("kalshi", ARCHIVE_DIR / "kalshi.db", 3),
]
MAIN_DB = ROOT / "backend/data/picks.dev.db"
K = 250.0
PLAYER_HALF_LIFE_YEARS = 2.0
VALIDATION_YEAR = 2021
TEST_YEARS = range(2022, 2025)
EPS = 1e-9
INCOMPLETE = ("RET", "W/O", "DEF", "ABD")


def norm(text: str | None) -> str:
    value = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    value = re.sub(r"\b(tennis|atp|wta|men|women|singles|qualifying|qualifiers|mens|womens)\b", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def tournament_norm(text: str | None) -> str:
    value = norm(text)
    return {
        "roland garros": "french open",
        "australia open": "australian open",
        "aus open": "australian open",
        "the championships wimbledon": "wimbledon",
        "u s open": "us open",
    }.get(value, value)


def is_complete(score: str | None) -> bool:
    return bool(score) and not any(token in score.upper() for token in INCOMPLETE)


def score_sets(score: str | None) -> list[tuple[int, int]]:
    if not is_complete(score) or "[" in (score or ""):
        return []
    return [(int(a), int(b)) for a, b in re.findall(r"(\d+)-(\d+)", score or "")]


def main_key(row: dict[str, Any]) -> str:
    return f"{row['tour']}|{row['tourney_id']}|{row['match_num']}|{row['winner_id']}|{row['loser_id']}"


def read_main(db: Path) -> tuple[list[dict[str, Any]], dict[tuple, list[dict[str, Any]]]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows: list[dict[str, Any]] = []
    by_identity: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    fields = (
        "tourney_id,tourney_name,surface,tourney_date,match_num,winner_id,loser_id,winner_name,loser_name,"
        "best_of,score,w_svpt,l_svpt,w_1stWon,w_2ndWon,l_1stWon,l_2ndWon,w_SvGms,l_SvGms"
    )
    try:
        for tour in ("atp", "wta"):
            sql = (f"SELECT {fields} FROM tennis_{tour}_matches WHERE {tpm.TOUR_FILTER[tour]} "
                   "AND tourney_date BETWEEN 20000101 AND 20261231 "
                   "AND surface IS NOT NULL AND winner_id IS NOT NULL AND loser_id IS NOT NULL ORDER BY tourney_date")
            for values in conn.execute(sql):
                row = dict(zip(("tourney_id", "tourney_name", "surface", "tourney_date", "match_num",
                                "winner_id", "loser_id", "winner_name", "loser_name", "best_of", "score",
                                "w_svpt", "l_svpt", "w_1stWon", "w_2ndWon", "l_1stWon", "l_2ndWon",
                                "w_SvGms", "l_SvGms"), values))
                row["tour"] = tour
                row["year"] = int(row["tourney_date"]) // 10000
                row["key"] = main_key(row)
                rows.append(row)
                if row["winner_name"] and row["loser_name"]:
                    ident = (tour, row["year"], tournament_norm(row["tourney_name"]),
                             tuple(sorted((norm(row["winner_name"]), norm(row["loser_name"])))) )
                    by_identity[ident].append(row)
    finally:
        conn.close()
    return rows, by_identity


def event_counts(conn: sqlite3.Connection, source: str, dataset: str) -> dict[str, dict[str, int]]:
    sql = ("SELECT source_match_id,COUNT(*),SUM(point_server IS NOT NULL),SUM(point_winner IS NOT NULL),"
           "SUM(point_server IS NOT NULL AND point_winner IS NOT NULL),COUNT(point_no),"
           "COUNT(DISTINCT point_no),MIN(point_no),MAX(point_no),SUM(is_ace IS NOT NULL),"
           "SUM(is_double_fault IS NOT NULL),SUM(is_ace=1),SUM(is_double_fault=1),"
           "SUM(is_ace=1 AND point_server=point_winner),"
           "SUM(is_double_fault=1 AND point_server!=point_winner) "
           "FROM tennis_point_events WHERE source=? AND source_dataset=? AND is_point=1 GROUP BY source_match_id")
    result: dict[str, dict[str, int]] = {}
    for row in conn.execute(sql, (source, dataset)):
        result[row[0]] = dict(zip(("points", "server_known", "winner_known", "both_known", "pointno_count",
                                   "pointno_distinct", "pointno_min", "pointno_max", "ace_flag_known",
                                   "double_fault_flag_known", "aces", "double_faults", "ace_consistent",
                                   "double_fault_consistent"), row[1:]))
    return result


def singles(meta: dict[str, Any]) -> bool:
    category = (meta.get("event_category") or "").lower()
    return "singles" in category or "charted match" in category


def archive_records(main_index: dict[tuple, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    for source, path, priority in ARCHIVES:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            src = conn.execute("SELECT source,source_dataset,source_match_rows,source_event_rows,played_point_rows "
                               "FROM tennis_point_sources LIMIT 1").fetchone()
            source_code, dataset = src["source"], src["source_dataset"]
            print(f"Scanning {source}: {src['played_point_rows']:,} point rows; aggregating match counts…", flush=True)
            counts = event_counts(conn, source_code, dataset)
            metadata = conn.execute("SELECT * FROM tennis_point_matches").fetchall()
            src_cov = {"database_match_rows": src["source_match_rows"], "event_rows": src["source_event_rows"],
                       "point_rows": sum(x["points"] for x in counts.values()),
                       "matches_with_points": len(counts),
                       "server_known_point_rows": sum(x["server_known"] for x in counts.values()),
                       "winner_known_point_rows": sum(x["winner_known"] for x in counts.values()),
                       "both_known_point_rows": sum(x["both_known"] for x in counts.values()),
                       "ace_flag_known_point_rows": sum(x["ace_flag_known"] or 0 for x in counts.values()),
                       "double_fault_flag_known_point_rows": sum(x["double_fault_flag_known"] or 0 for x in counts.values()),
                       "ace_point_rows": sum(x["aces"] or 0 for x in counts.values()),
                       "double_fault_point_rows": sum(x["double_faults"] or 0 for x in counts.values()),
                       "ace_server_winner_consistent_rows": sum(x["ace_consistent"] or 0 for x in counts.values()),
                       "double_fault_receiver_winner_consistent_rows": sum(x["double_fault_consistent"] or 0 for x in counts.values()),
                       "named_singles": 0, "crosswalk": 0,
                       "unambiguous": 0, "complete_match_stats": 0, "exact_point_totals": 0,
                       "verified_full_histories": 0}
            for raw in metadata:
                meta = dict(raw)
                meta["source"] = source
                meta["source_code"] = source_code
                meta["source_dataset"] = dataset
                meta["priority"] = priority
                meta["events"] = counts.get(meta["source_match_id"], {})
                year = int(meta["match_year"] or 0)
                if year < 2000 or year > 2026 or meta["tour"] not in ("atp", "wta") or not singles(meta):
                    continue
                p1, p2 = meta.get("player1_name"), meta.get("player2_name")
                if not p1 or not p2:
                    continue
                src_cov["named_singles"] += 1
                ident = (meta["tour"], year, tournament_norm(meta.get("tournament_name")),
                         tuple(sorted((norm(p1), norm(p2)))))
                hits = main_index.get(ident, [])
                if not hits:
                    continue
                src_cov["crosswalk"] += 1
                if len(hits) != 1:
                    continue
                src_cov["unambiguous"] += 1
                target = hits[0]
                if norm(p1) == norm(target["winner_name"]):
                    p1id, p2id = target["winner_id"], target["loser_id"]
                elif norm(p1) == norm(target["loser_name"]):
                    p1id, p2id = target["loser_id"], target["winner_id"]
                else:
                    continue
                ev = meta["events"]
                total_stats = None if target["w_svpt"] is None or target["l_svpt"] is None else target["w_svpt"] + target["l_svpt"]
                complete_stats = total_stats is not None and all(target[x] is not None for x in
                                  ("w_1stWon", "w_2ndWon", "l_1stWon", "l_2ndWon", "w_SvGms", "l_SvGms"))
                if complete_stats:
                    src_cov["complete_match_stats"] += 1
                exact_points = total_stats is not None and ev.get("points", 0) == total_stats
                if exact_points:
                    src_cov["exact_point_totals"] += 1
                point_order_ok = True
                if source == "match_charting_project":
                    n = ev.get("points", 0)
                    point_order_ok = (ev.get("pointno_count", 0) == n and ev.get("pointno_distinct", 0) == n
                                      and ev.get("pointno_min") == 1 and ev.get("pointno_max") == n)
                full = (exact_points and ev.get("both_known", 0) == ev.get("points", -1)
                        and is_complete(target["score"]) and target["surface"] is not None
                        and complete_stats and point_order_ok)
                if full:
                    src_cov["verified_full_histories"] += 1
                record = {**meta, "target": target, "key": target["key"], "p1_id": p1id, "p2_id": p2id,
                          "p1_is_winner": int(p1id == target["winner_id"]), "surface": target["surface"],
                          "tourney_date": target["tourney_date"], "tourney_id": target["tourney_id"],
                          "year": year, "point_order_ok": point_order_ok, "full": full,
                          "exact_points": exact_points, "complete_stats": complete_stats}
                records.append(record)
            coverage[source] = src_cov
        finally:
            conn.close()
    return records, coverage


def deduplicate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        if rec["full"]:
            by_key[rec["key"]].append(rec)
    selected: list[dict[str, Any]] = []
    source_counts: Counter = Counter()
    overlaps = 0
    for matches in by_key.values():
        matches.sort(key=lambda item: item["priority"])
        overlaps += len(matches) - 1
        selected.append(matches[0])
        source_counts[matches[0]["source"]] += 1
    selected.sort(key=lambda item: (item["tourney_date"], item["tour"], item["key"]))
    return selected, {"overlapping_verified_source_rows_removed": overlaps, **dict(source_counts)}


def match_point_counts(matches: list[dict[str, Any]]) -> dict[str, dict[tuple[str, str], int]]:
    """Aggregate server/winner counts per selected match without reading raw JSON payloads."""
    per_source: dict[str, dict[tuple[str, str], int]] = {}
    for source, path, _ in ARCHIVES:
        chosen = [m for m in matches if m["source"] == source]
        if not chosen:
            continue
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            source_code, dataset = conn.execute(
                "SELECT source,source_dataset FROM tennis_point_sources LIMIT 1").fetchone()
            conn.execute("CREATE TEMP TABLE selected(source_match_id TEXT PRIMARY KEY,match_key TEXT NOT NULL)")
            conn.executemany("INSERT INTO selected VALUES(?,?)", [(m["source_match_id"], m["key"]) for m in chosen])
            grouped: dict[str, Counter] = defaultdict(Counter)
            sql = ("SELECT s.match_key,e.point_server,e.point_winner,COUNT(*) FROM selected s "
                   "CROSS JOIN tennis_point_events AS e INDEXED BY ix_tennis_point_events_match_point "
                   "WHERE e.source=? AND e.source_dataset=? AND e.source_match_id=s.source_match_id AND e.is_point=1 "
                   "GROUP BY s.match_key,e.point_server,e.point_winner")
            for key, server, winner, count in conn.execute(sql, (source_code, dataset)):
                if server in ("1", "2") and winner in ("1", "2"):
                    grouped[key][(server, winner)] += count
            per_source[source] = grouped
        finally:
            conn.close()
    return per_source


class PointStats:
    """Surface baseline plus lazily decayed player serve/return counts."""
    def __init__(self) -> None:
        self.surface: dict[tuple[str, str], list[float]] = {}
        self.player: dict[tuple[str, str, int], list[float]] = {}

    @staticmethod
    def decay(entry: list[float], when: int) -> tuple[float, ...]:
        current = date(when // 10000, (when // 100) % 100, when % 100).toordinal()
        previous = int(entry[-1])
        factor = 0.5 ** (max(0, current - previous) / (PLAYER_HALF_LIFE_YEARS * 365.25))
        return tuple(value * factor for value in entry[:-1])

    def baseline(self, tour: str, surface: str) -> float:
        entry = self.surface.get((tour, surface))
        return entry[0] / entry[1] if entry and entry[1] else tpm.COLD_START_BASELINE

    def player_counts(self, tour: str, surface: str, player: int, when: int) -> tuple[float, ...]:
        entry = self.player.get((tour, surface, player))
        return self.decay(entry, when) if entry else (0.0, 0.0, 0.0, 0.0)

    def serve(self, tour: str, surface: str, player: int, when: int, baseline: float) -> float:
        won, points, _, _ = self.player_counts(tour, surface, player, when)
        return (won + K * baseline) / (points + K)

    def returns(self, tour: str, surface: str, player: int, when: int, baseline: float) -> float:
        _, _, won, points = self.player_counts(tour, surface, player, when)
        return (won + K * (1.0 - baseline)) / (points + K)

    def add(self, match: dict[str, Any], counts: Counter) -> None:
        when, tour, surface = match["tourney_date"], match["tour"], match["surface"]
        ordinal = date(when // 10000, (when // 100) % 100, when % 100).toordinal()
        player_deltas: dict[int, list[float]] = {match["p1_id"]: [0, 0, 0, 0], match["p2_id"]: [0, 0, 0, 0]}
        surface_won = surface_points = 0
        for (server, winner), n in counts.items():
            server_id = match["p1_id"] if server == "1" else match["p2_id"]
            receiver_id = match["p2_id"] if server == "1" else match["p1_id"]
            server_won = winner == server
            player_deltas[server_id][0] += n * server_won
            player_deltas[server_id][1] += n
            player_deltas[receiver_id][2] += n * (not server_won)
            player_deltas[receiver_id][3] += n
            surface_won += n * server_won
            surface_points += n
        base_entry = self.surface.setdefault((tour, surface), [0.0, 0.0])
        base_entry[0] += surface_won
        base_entry[1] += surface_points
        for player, delta in player_deltas.items():
            key = (tour, surface, player)
            entry = self.player.get(key)
            if entry:
                decayed = self.decay(entry, when)
                entry[:4] = decayed
            else:
                entry = [0.0, 0.0, 0.0, 0.0, ordinal]
                self.player[key] = entry
            for i, value in enumerate(delta):
                entry[i] += value
            entry[4] = ordinal


def features(stats: PointStats, match: dict[str, Any], include_simulator: bool = False) -> dict[str, float]:
    tour, surface, when = match["tour"], match["surface"], match["tourney_date"]
    baseline = stats.baseline(tour, surface)
    serve_a = stats.serve(tour, surface, match["p1_id"], when, baseline)
    serve_b = stats.serve(tour, surface, match["p2_id"], when, baseline)
    return_a = stats.returns(tour, surface, match["p1_id"], when, baseline)
    return_b = stats.returns(tour, surface, match["p2_id"], when, baseline)
    p_a = tpm.point_prob(serve_a, return_b, baseline)
    p_b = tpm.point_prob(serve_b, return_a, baseline)
    x = math.log(p_a / (1 - p_a)) - math.log(p_b / (1 - p_b))
    result = {"p_a": p_a, "p_b": p_b, "x": x, "baseline": baseline}
    if include_simulator:
        result["p_sim"] = sim.match_distribution(p_a, p_b, {"bestOf": 3}, None)["p_a"]
    return result


def solve2(a00: float, a01: float, a11: float, b0: float, b1: float) -> tuple[float, float]:
    det = a00 * a11 - a01 * a01
    if abs(det) < 1e-14:
        return 0.0, 0.0
    return ((b0 * a11 - b1 * a01) / det, (b1 * a00 - b0 * a01) / det)


def fit_logistic(rows: list[dict[str, Any]], feature: str) -> tuple[float, float]:
    a = b = 0.0
    for _ in range(100):
        g0 = g1 = i00 = i01 = i11 = 0.0
        for row in rows:
            x, y = row[feature], row["y"]
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, a + b * x))))
            w = p * (1 - p)
            g0 += y - p
            g1 += (y - p) * x
            i00 += w
            i01 += w * x
            i11 += w * x * x
        d0, d1 = solve2(i00 + 1e-8, i01, i11 + 1e-8, g0, g1)
        a += d0
        b += d1
        if max(abs(d0), abs(d1)) < 1e-8:
            break
    return a, b


def fit_symmetric_logistic(rows: list[dict[str, Any]], feature: str) -> tuple[float, float]:
    """Fit only a slope: swapping players must swap P(win) to 1-P(win)."""
    b = 0.0
    for _ in range(100):
        gradient = information = 0.0
        for row in rows:
            x, y = row[feature], row["y"]
            p = sigmoid(b * x)
            weight = p * (1 - p)
            gradient += (y - p) * x
            information += weight * x * x
        step = gradient / (information + 1e-8)
        b += step
        if abs(step) < 1e-8:
            break
    return 0.0, b


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def logit(value: float) -> float:
    value = min(1 - EPS, max(EPS, value))
    return math.log(value / (1 - value))


def loss_summary(rows: list[dict[str, Any]], model: str) -> dict[str, float]:
    if not rows:
        return {"n": 0}
    ps = [min(1 - EPS, max(EPS, r[model])) for r in rows]
    ys = [r["y"] for r in rows]
    return {"n": len(rows), "brier": statistics.mean((p - y) ** 2 for p, y in zip(ps, ys)),
            "log_loss": statistics.mean(-(y * math.log(p) + (1-y) * math.log(1-p))
                                         for p, y in zip(ps, ys))}


def cluster_interval(rows: list[dict[str, Any]], model_a: str, model_b: str,
                     n_boot: int = 2000, seed: int = 20261016) -> dict[str, float]:
    clusters: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        clusters[f"{r['tour']}:{r['tourney_id']}"] .append((r[model_a] - r["y"]) ** 2 - (r[model_b] - r["y"]) ** 2)
    keys = sorted(clusters)
    diffs = [x for values in clusters.values() for x in values]
    mean = statistics.mean(diffs) if diffs else math.nan
    # Cluster bootstrap: resample tournament blocks, retaining match-level weights inside each block.
    import random
    rng = random.Random(seed)
    samples = []
    for _ in range(n_boot):
        chosen = [keys[rng.randrange(len(keys))] for _ in keys]
        vals = [v for key in chosen for v in clusters[key]]
        samples.append(statistics.mean(vals))
    samples.sort()
    return {"mean_brier_difference": mean, "ci95_low": samples[int(.025*n_boot)],
            "ci95_high": samples[int(.975*n_boot)-1], "tournament_clusters": len(keys)}


def clustered_difference(rows: list[dict[str, Any]], left: str, right: str,
                         n_boot: int = 2000, seed: int = 20261016) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[f"{row['tour']}:{row['tourney_id']}"].append(row[left] - row[right])
    keys = sorted(grouped)
    vals = [x for block in grouped.values() for x in block]
    import random
    rng = random.Random(seed)
    boot = [statistics.mean(x for key in (keys[rng.randrange(len(keys))] for _ in keys) for x in grouped[key])
            for _ in range(n_boot)]
    boot.sort()
    return {"mean_difference": statistics.mean(vals), "ci95_low": boot[int(.025*n_boot)],
            "ci95_high": boot[int(.975*n_boot)-1], "tournament_clusters": len(keys)}


def score_value(value: Any) -> int | None:
    token = str(value or "").strip().upper()
    if token in ("0", "LOVE"):
        return 0
    if token == "15":
        return 1
    if token == "30":
        return 2
    if token == "40":
        return 3
    if token in ("AD", "A"):
        return 4
    return None


def score_context(before_json: str | None, server: str) -> str:
    try:
        obj = json.loads(before_json or "{}")
        a, b = score_value(obj.get("player1")), score_value(obj.get("player2"))
    except (TypeError, ValueError):
        return "unknown"
    if a is None or b is None or server not in ("1", "2"):
        return "unknown"
    sv, ret = (a, b) if server == "1" else (b, a)
    if sv == 0 and ret == 0:
        return "love_all"
    if sv == 3 and ret == 3:
        return "deuce"
    if sv == 4:
        return "server_game_point"
    if ret == 4 or (ret == 3 and sv < 3):
        return "break_point"
    return "server_leads" if sv > ret else "receiver_leads" if ret > sv else "other"


def late_capture_context() -> dict[str, Any]:
    """Descriptive score-state and serve-number checks for the 2026 US Open and Kalshi captures."""
    result: dict[str, Any] = {}
    for source, path, _ in ARCHIVES:
        if source not in ("usopen", "kalshi"):
            continue
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            src = conn.execute("SELECT source,source_dataset FROM tennis_point_sources LIMIT 1").fetchone()
            source_code, dataset = src["source"], src["source_dataset"]
            metas = [dict(row) for row in conn.execute(
                "SELECT source_match_id,tour,event_category,player1_name,player2_name FROM tennis_point_matches "
                "WHERE match_year>=2025")]
            chosen = [m for m in metas if m["tour"] in ("atp", "wta") and singles(m)
                      and m["player1_name"] and m["player2_name"]]
            conn.execute("CREATE TEMP TABLE selected(source_match_id TEXT PRIMARY KEY)")
            conn.executemany("INSERT INTO selected VALUES(?)", [(m["source_match_id"],) for m in chosen])
            contexts: dict[str, Counter] = defaultdict(Counter)
            serve_number: dict[str, Counter] = defaultdict(Counter)
            total = known_server = known_winner = known_both = aces = dfs = 0
            sql = ("SELECT e.score_before_json,e.point_server,e.point_winner,e.serve_number,e.is_ace,e.is_double_fault "
                   "FROM selected s CROSS JOIN tennis_point_events AS e INDEXED BY ix_tennis_point_events_match_point "
                   "WHERE e.source=? AND e.source_dataset=? AND e.source_match_id=s.source_match_id AND e.is_point=1")
            for before, server, winner, serve_no, ace, df in conn.execute(sql, (source_code, dataset)):
                total += 1
                known_server += server is not None
                known_winner += winner is not None
                known_both += server is not None and winner is not None
                aces += ace == 1
                dfs += df == 1
                if server not in ("1", "2") or winner not in ("1", "2"):
                    continue
                outcome = int(server == winner)
                context = score_context(before, server)
                contexts[context]["n"] += 1
                contexts[context]["server_won"] += outcome
                if serve_no in ("1", "2", 1, 2):
                    serve_number[str(serve_no)]["n"] += 1
                    serve_number[str(serve_no)]["server_won"] += outcome
            result[source] = {"explicit_named_singles_matches": len(chosen), "point_rows": total,
                              "server_label_coverage": known_server / total if total else None,
                              "winner_label_coverage": known_winner / total if total else None,
                              "both_labels_coverage": known_both / total if total else None,
                              "ace_rows": aces, "double_fault_rows": dfs,
                              "ace_rate_per_point_row": aces / total if total else None,
                              "double_fault_rate_per_point_row": dfs / total if total else None,
                              "score_state_server_win_rate": {
                                  k: {"n": v["n"], "rate": v["server_won"] / v["n"]} for k, v in contexts.items()},
                              "serve_number_server_win_rate": {
                                  k: {"n": v["n"], "rate": v["server_won"] / v["n"]} for k, v in serve_number.items()}}
        finally:
            conn.close()
    return result


def eval_events(matches: list[dict[str, Any]], feat: dict[str, dict[str, float]],
                count_by_key: dict[str, Counter]) -> dict[str, Any]:
    """Read test points once, keeping match and tournament as the evaluation units."""
    test = [m for m in matches if m["year"] in TEST_YEARS and m["key"] in feat]
    selected_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_by_key = {m["key"]: m for m in test}
    for m in test:
        selected_by_source[m["source"]].append(m)
    match_scores: dict[str, dict[str, Any]] = {}
    conditional: dict[str, Counter] = defaultdict(Counter)
    by_source_points: Counter = Counter()
    for source, path, _ in ARCHIVES:
        chosen = selected_by_source.get(source, [])
        if not chosen:
            continue
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            source_code, dataset = conn.execute(
                "SELECT source,source_dataset FROM tennis_point_sources LIMIT 1").fetchone()
            conn.execute("CREATE TEMP TABLE selected(source_match_id TEXT PRIMARY KEY,match_key TEXT NOT NULL)")
            conn.executemany("INSERT INTO selected VALUES(?,?)", [(m["source_match_id"], m["key"]) for m in chosen])
            sql = ("SELECT s.match_key,e.sequence_no,e.set_no,e.game_no,e.score_before_json,e.point_server,"
                   "e.point_winner,e.serve_number,e.is_ace,e.is_double_fault FROM selected s "
                   "CROSS JOIN tennis_point_events AS e INDEXED BY ix_tennis_point_events_match_point "
                   "WHERE e.source=? AND e.source_dataset=? AND e.source_match_id=s.source_match_id AND e.is_point=1 "
                   "ORDER BY s.match_key,e.sequence_no")
            current_key = None
            current: dict[str, Any] | None = None
            game: dict[str, Any] | None = None

            def finish_game(bucket: dict[str, Any] | None, row: dict[str, Any] | None) -> None:
                if not bucket or not row or len(bucket["servers"]) != 1 or bucket["n"] < 4:
                    return
                srv = next(iter(bucket["servers"]))
                winner = bucket["last_winner"]
                if srv not in ("1", "2") or winner not in ("1", "2"):
                    return
                p_srv = row["features"]["p_a"] if srv == "1" else row["features"]["p_b"]
                observed = int(srv == winner)
                row["games"].append({"p": sim.game_win_prob(p_srv), "y": observed, "server": srv})
                row["server_games_played"][srv] += 1
                row["server_game_wins"][srv] += observed

            def finish_match(key: str | None, row: dict[str, Any] | None) -> None:
                if key is None or row is None:
                    return
                finish_game(game, row)
                match_scores[key] = row

            for values in conn.execute(sql, (source_code, dataset)):
                key, seq, set_no, game_no, before, server, winner, serve_no, ace, df = values
                if key != current_key:
                    finish_match(current_key, current)
                    current_key = key
                    match = all_by_key[key]
                    f = feat[key]
                    current = {"match": match, "features": f, "point_brier": [], "baseline_brier": [],
                               "games": [], "server_games_played": Counter(),
                               "server_game_wins": Counter(), "point_count": 0}
                    game = None
                if set_no != (game or {}).get("set_no") or game_no != (game or {}).get("game_no"):
                    finish_game(game, current)
                    game = {"set_no": set_no, "game_no": game_no, "servers": set(), "last_winner": None, "n": 0}
                if server not in ("1", "2") or winner not in ("1", "2"):
                    continue
                predicted = current["features"]["p_a"] if server == "1" else current["features"]["p_b"]
                y_point = int(server == winner)
                current["point_brier"].append((predicted - y_point) ** 2)
                baseline = current["features"]["baseline"]
                current["baseline_brier"].append((baseline - y_point) ** 2)
                current["point_count"] += 1
                current["context_counts"] = current.get("context_counts", Counter())
                context = score_context(before, server)
                conditional[(source, context)]["points"] += 1
                conditional[(source, context)]["server_won"] += y_point
                conditional[(source, context)]["predicted_probability_sum"] += predicted
                conditional[(source, context)]["brier_sum"] += (predicted - y_point) ** 2
                if serve_no in ("1", "2", 1, 2):
                    serve_bucket = conditional[(source, f"serve_{serve_no}")]
                    serve_bucket["points"] += 1
                    serve_bucket["server_won"] += y_point
                    serve_bucket["predicted_probability_sum"] += predicted
                    serve_bucket["brier_sum"] += (predicted - y_point) ** 2
                by_source_points[source] += 1
                if game_no is not None and set_no is not None:
                    game["servers"].add(server)
                    game["last_winner"] = winner
                    game["n"] += 1
                if ace == 1:
                    conditional[(source, "ace")]["points"] += 1
                if df == 1:
                    conditional[(source, "double_fault")]["points"] += 1
            finish_match(current_key, current)
        finally:
            conn.close()

    # Equal-weight matches first; uncertainty and comparison are clustered by tournament.
    point_rows = []
    game_rows = []
    game_stat_checks = Counter()
    for key, row in match_scores.items():
        match = row["match"]
        target = match["target"]
        service_games_match_official = False
        winner_service_games = row["server_games_played"]["1"] if match["p1_is_winner"] else row["server_games_played"]["2"]
        loser_service_games = row["server_games_played"]["2"] if match["p1_is_winner"] else row["server_games_played"]["1"]
        if target["w_SvGms"] is not None and target["l_SvGms"] is not None:
            game_stat_checks["matches_with_official_service_game_counts"] += 1
            if winner_service_games == target["w_SvGms"] and loser_service_games == target["l_SvGms"]:
                game_stat_checks["matches_matching_official_service_game_counts"] += 1
                service_games_match_official = True
            else:
                game_stat_checks["matches_not_matching_official_service_game_counts"] += 1
        cluster = f"{match['tour']}:{match['tourney_id']}"
        if row["point_brier"]:
            point_rows.append({"key": key, "tour": match["tour"], "tourney_id": match["tourney_id"],
                               "brier": statistics.mean(row["point_brier"]),
                               "baseline_brier": statistics.mean(row["baseline_brier"]),
                               "cluster": cluster})
        if row["games"] and service_games_match_official:
            observed_hold = statistics.mean(g["y"] for g in row["games"])
            predicted_hold = statistics.mean(g["p"] for g in row["games"])
            game_rows.append({"key": key, "tour": match["tour"], "tourney_id": match["tourney_id"],
                              "n": len(row["games"]),
                              "observed_hold": observed_hold,
                              "predicted_hold": predicted_hold,
                              "observed_break": 1.0 - observed_hold,
                              "predicted_break": 1.0 - predicted_hold,
                              "brier": statistics.mean((g["p"] - g["y"])**2 for g in row["games"]),
                              "cluster": cluster})
    point_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    game_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in point_rows:
        point_cluster[r["cluster"]].append(r)
    for r in game_rows:
        game_cluster[r["cluster"]].append(r)
    return {"match_rows": match_scores, "point_match_rows": point_rows, "game_match_rows": game_rows,
            "point_clusters": point_cluster, "game_clusters": game_cluster,
            "service_game_reconstruction_vs_official_stats": dict(game_stat_checks),
            "points_by_source": dict(by_source_points),
            "conditional": {f"{s}/{c}": {
                                "n": v["points"],
                                "server_win_rate": v["server_won"] / v["points"] if v["points"] else None,
                                "mean_predicted_server_win_probability":
                                    v["predicted_probability_sum"] / v["points"] if v["points"] else None,
                                "observed_minus_predicted_server_win_rate":
                                    v["server_won"] / v["points"] - v["predicted_probability_sum"] / v["points"]
                                    if v["points"] else None,
                                "point_brier": v["brier_sum"] / v["points"] if v["points"] else None,
                            }
                            for (s, c), v in conditional.items() if c != "ace" and c != "double_fault"}}


def summarize(rows: list[dict[str, Any]], model: str) -> dict[str, float]:
    return loss_summary(rows, model)


def run(out: Path) -> None:
    print("Loading main-tour match identities…", flush=True)
    main_rows, main_index = read_main(MAIN_DB)
    print(f"Loaded {len(main_rows):,} main-tour results; crosswalking archive matches…", flush=True)
    source_rows, source_coverage = archive_records(main_index)
    candidates = [r for r in source_rows if r["full"]]
    verified, dedup = deduplicate(candidates)
    print(f"Selected {len(verified):,} unique verified histories; aggregating point outcomes…", flush=True)
    grouped = match_point_counts(verified)
    counts: dict[str, Counter] = {}
    for m in verified:
        counts[m["key"]] = grouped.get(m["source"], {}).get(m["key"], Counter())

    # Build walk-forward point and Elo predictions. All same-day matches are predicted before updates.
    by_date: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in main_rows:
        by_date[(r["tour"], r["tourney_date"])].append(r)
    verified_by_key = {m["key"]: m for m in verified}
    stats = PointStats()
    elo: dict[tuple[str, int], float] = defaultdict(lambda: 1500.0)
    features_by_key: dict[str, dict[str, float]] = {}
    elo_by_key: dict[str, float] = {}
    evaluated: list[dict[str, Any]] = []
    for (tour, when), daily in sorted(by_date.items(), key=lambda x: (x[0][1], x[0][0])):
        # Snapshot before any same-date update.
        for row in daily:
            key = row["key"]
            history = verified_by_key.get(key)
            if history and row["surface"] is not None and VALIDATION_YEAR <= row["year"] <= 2024:
                eligible_match = (row["year"] in (VALIDATION_YEAR, *TEST_YEARS) and row["best_of"] == 3
                                  and is_complete(row["score"]) and "[" not in (row["score"] or "")
                                  and len(score_sets(row["score"])) in (2, 3))
                f = features(stats, history, include_simulator=eligible_match)
                features_by_key[key] = f
                elo_p1 = 1.0 / (1.0 + 10 ** ((elo[(tour, row["loser_id"])] - elo[(tour, row["winner_id"])]) / 400.0))
                p_elo = elo_p1 if history["p1_is_winner"] else 1.0 - elo_p1
                elo_by_key[key] = p_elo
                y = history["p1_is_winner"]
                score = row["score"]
                if eligible_match:
                    evaluated.append({"key": key, "year": row["year"], "tour": tour,
                                      "tourney_id": row["tourney_id"], "tourney_name": row["tourney_name"],
                                      "surface": row["surface"], "score": score, "y": y,
                                      "x": f["x"], "sim": f["p_sim"], "elo": p_elo,
                                      "features": f, "match": history})
        deltas = []
        for row in daily:
            expected = 1.0 / (1.0 + 10 ** ((elo[(tour, row["loser_id"])] - elo[(tour, row["winner_id"])]) / 400.0))
            deltas.append((row["winner_id"], row["loser_id"], 32.0 * (1.0 - expected)))
        for winner, loser, delta in deltas:
            elo[(tour, winner)] += delta
            elo[(tour, loser)] -= delta
        # Historical point observations enter only after same-day forecasts are fixed.
        for row in daily:
            history = verified_by_key.get(row["key"])
            if history:
                stats.add(history, counts[history["key"]])

    validation = [r for r in evaluated if r["year"] == VALIDATION_YEAR]
    test = [r for r in evaluated if r["year"] in TEST_YEARS]
    if not validation or not test:
        raise RuntimeError(f"Insufficient verified validation/test histories: {len(validation)} / {len(test)}")
    fit_direct = fit_symmetric_logistic(validation, "x")
    for r in evaluated:
        r["sim_logit"] = logit(r["sim"])
        r["elo_logit"] = logit(r["elo"])
    # Refit the two probability-calibration transforms after their features are attached.
    fit_sim = fit_symmetric_logistic(validation, "sim_logit")
    fit_elo = fit_symmetric_logistic(validation, "elo_logit")
    for r in evaluated:
        r["direct"] = sigmoid(fit_direct[0] + fit_direct[1] * r["x"])
        r["sim_cal"] = sigmoid(fit_sim[0] + fit_sim[1] * r["sim_logit"])
        r["elo_cal"] = sigmoid(fit_elo[0] + fit_elo[1] * r["elo_logit"])
    test = [r for r in evaluated if r["year"] in TEST_YEARS]
    point_eval = eval_events(verified, features_by_key, counts)
    point_rows = point_eval["point_match_rows"]
    game_rows = point_eval["game_match_rows"]
    late_context = late_capture_context()

    model_columns = {"Elo raw": "elo", "point simulator raw": "sim", "direct point logistic": "direct",
                     "simulator calibrated": "sim_cal", "Elo calibrated": "elo_cal"}
    overall = {name: loss_summary(test, col) for name, col in model_columns.items()}
    paired = {
        "direct_minus_elo": cluster_interval(test, "direct", "elo"),
        "direct_minus_elo_calibrated": cluster_interval(test, "direct", "elo_cal"),
        "direct_minus_simulator": cluster_interval(test, "direct", "sim"),
        "direct_minus_simulator_calibrated": cluster_interval(test, "direct", "sim_cal"),
        "simulator_minus_elo": cluster_interval(test, "sim", "elo"),
    }
    by_year_tour = {}
    for year in TEST_YEARS:
        for tour in ("atp", "wta"):
            subset = [r for r in test if r["year"] == year and r["tour"] == tour]
            if subset:
                by_year_tour[f"{year}-{tour}"] = {name: loss_summary(subset, col) for name, col in model_columns.items()}
    by_tournament: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in test:
        by_tournament[(row["tour"], row["year"], row["tourney_id"], row["tourney_name"])].append(row)
    tournament_scores = []
    for (tour, year, tourney_id, tourney_name), subset in sorted(by_tournament.items()):
        tournament_scores.append({"tour": tour, "year": year, "tourney_id": tourney_id,
                                  "tournament": tourney_name, "matches": len(subset),
                                  **{f"brier_{name.lower().replace(' ', '_')}": loss_summary(subset, col)["brier"]
                                     for name, col in model_columns.items()}})

    # Match score outcomes compared with the simulator's expected match length/set distribution.
    structural_rows = []
    for r in test:
        sets = score_sets(r["score"])
        if not sets:
            continue
        dist = sim.match_distribution(r["features"]["p_a"], r["features"]["p_b"], {"bestOf": 3}, None)
        observed_games = sum(a + b for a, b in sets)
        observed_sets = len(sets)
        observed_set_lengths = [a + b for a, b in sets]
        predicted_set_count = sum(n * p for n, p in dist["sets_played"].items())
        predicted_set_length_counts: dict[int, float] = defaultdict(float)
        for (_set_no, _winner, winner_games, loser_games), probability in dist["set_scores"].items():
            predicted_set_length_counts[winner_games + loser_games] += probability
        predicted_set_length = (
            sum(length * count for length, count in predicted_set_length_counts.items()) / predicted_set_count
            if predicted_set_count else math.nan
        )
        observed_tb = any((a, b) in ((7, 6), (6, 7)) for a, b in sets)
        structural_rows.append({"tour": r["tour"], "tourney_id": r["tourney_id"], "year": r["year"],
                                "observed_games": observed_games, "predicted_games": dist["expected_games"],
                                "observed_sets": observed_sets,
                                "predicted_sets": sum(n * p for n, p in dist["sets_played"].items()),
                                "observed_set_length": statistics.mean(observed_set_lengths),
                                "predicted_set_length": predicted_set_length,
                                "observed_set_lengths": observed_set_lengths,
                                "predicted_set_length_counts": dict(predicted_set_length_counts),
                                "observed_decider": int(observed_sets == 3),
                                "predicted_decider": dist["sets_played"].get(3, 0.0),
                                "observed_tiebreak": int(observed_tb), "predicted_tiebreak": dist["p_tiebreak_any"]})

    observed_set_length_counts: Counter = Counter()
    predicted_set_length_counts: Counter = Counter()
    for row in structural_rows:
        observed_set_length_counts.update(row["observed_set_lengths"])
        for length, count in row["predicted_set_length_counts"].items():
            predicted_set_length_counts[int(length)] += count
    observed_set_total = sum(observed_set_length_counts.values())
    predicted_set_total = sum(predicted_set_length_counts.values())
    set_length_distribution = {
        str(length): {
            "observed_sets": observed_set_length_counts[length],
            "observed_rate": observed_set_length_counts[length] / observed_set_total,
            "predicted_expected_sets": predicted_set_length_counts[length],
            "predicted_rate": predicted_set_length_counts[length] / predicted_set_total,
        }
        for length in sorted(set(observed_set_length_counts) | set(predicted_set_length_counts))
    }

    # Source-level 2026 point label availability; these captures are beyond the result database's history.
    live = {source: {"point_rows": coverage["point_rows"],
                     "server_known_point_rows": coverage["server_known_point_rows"],
                     "winner_known_point_rows": coverage["winner_known_point_rows"],
                     "both_known_point_rows": coverage["both_known_point_rows"],
                     "ace_flag_known_point_rows": coverage["ace_flag_known_point_rows"],
                     "double_fault_flag_known_point_rows": coverage["double_fault_flag_known_point_rows"],
                     "ace_point_rows": coverage["ace_point_rows"],
                     "double_fault_point_rows": coverage["double_fault_point_rows"],
                     "ace_server_winner_consistent_rows": coverage["ace_server_winner_consistent_rows"],
                     "double_fault_receiver_winner_consistent_rows": coverage["double_fault_receiver_winner_consistent_rows"]}
            for source, coverage in source_coverage.items()}

    orientation = {}
    for source in sorted({m["source"] for m in verified}):
        source_matches = [m for m in verified if m["source"] == source]
        orientation[source] = {"n": len(source_matches),
                               "p1_win_rate": statistics.mean(m["p1_is_winner"] for m in source_matches)}
    report = {
        "data": {"source_coverage": source_coverage, "dedup": dedup,
                 "unique_verified_histories": len(verified),
                 "unique_verified_by_year": dict(Counter(str(r["year"]) for r in verified)),
                 "unique_verified_by_source": dict(Counter(r["source"] for r in verified)),
                 "all_source_named_exact_match_rows": len(source_rows),
                 "verified_source_orientation": orientation,
                 "main_results_years": [min(r["year"] for r in main_rows), max(r["year"] for r in main_rows)],
                 "main_results_max_tourney_date_by_tour": {
                     tour: max(r["tourney_date"] for r in main_rows if r["tour"] == tour) for tour in ("atp", "wta")},
                 "training_history_scope": "Main-tour ATP/WTA histories from 2000 through the available 2026-06 result archive; model test ends 2024."},
        "model": {"validation_matches_2021": len(validation), "test_matches_2022_2024": len(test),
                  "fit_direct_point_logistic_alpha_beta": fit_direct,
                  "fit_simulator_calibration_alpha_beta": fit_sim,
                  "fit_elo_calibration_alpha_beta": fit_elo,
                  "test_brier_logloss": overall, "by_year_tour": by_year_tour,
                  "clustered_brier_differences": paired,
                  "symmetry_constraint": "All fitted calibration models have intercept fixed at zero so swapping player order swaps win probability."},
        "point_test": {"matches_with_point_scores": len(point_rows), "point_rows_by_source": point_eval["points_by_source"],
                       "mean_match_point_brier": statistics.mean(r["brier"] for r in point_rows) if point_rows else None,
                       "mean_match_surface_baseline_brier": statistics.mean(r["baseline_brier"] for r in point_rows) if point_rows else None,
                       "point_brier_minus_surface_baseline_clustered": clustered_difference(point_rows, "brier", "baseline_brier"),
                       "mean_match_game_hold_brier": statistics.mean(r["brier"] for r in game_rows) if game_rows else None,
                       "observed_hold_rate_across_matches": statistics.mean(r["observed_hold"] for r in game_rows) if game_rows else None,
                       "predicted_hold_rate_across_matches": statistics.mean(r["predicted_hold"] for r in game_rows) if game_rows else None,
                       "predicted_minus_observed_hold_rate_clustered": clustered_difference(
                           game_rows, "predicted_hold", "observed_hold"),
                       "observed_break_rate_across_matches": statistics.mean(r["observed_break"] for r in game_rows) if game_rows else None,
                       "predicted_break_rate_across_matches": statistics.mean(r["predicted_break"] for r in game_rows) if game_rows else None,
                       "predicted_minus_observed_break_rate_clustered": clustered_difference(
                           game_rows, "predicted_break", "observed_break"),
                       "hold_evaluation_matches_matching_official_service_game_counts": len(game_rows),
                       "service_game_reconstruction_vs_official_stats": point_eval["service_game_reconstruction_vs_official_stats"],
                       "conditional_server_win_rates": point_eval["conditional"]},
        "simulation_structure": {"matches": len(structural_rows),
                                 "observed_mean_total_games": statistics.mean(r["observed_games"] for r in structural_rows),
                                 "predicted_mean_total_games": statistics.mean(r["predicted_games"] for r in structural_rows),
                                 "predicted_minus_observed_total_games_clustered": clustered_difference(
                                     structural_rows, "predicted_games", "observed_games"),
                                 "observed_mean_sets": statistics.mean(r["observed_sets"] for r in structural_rows),
                                 "predicted_mean_sets": statistics.mean(r["predicted_sets"] for r in structural_rows),
                                 "observed_mean_games_per_set": statistics.mean(r["observed_set_length"] for r in structural_rows),
                                 "predicted_mean_games_per_set": statistics.mean(r["predicted_set_length"] for r in structural_rows),
                                 "predicted_minus_observed_games_per_set_clustered": clustered_difference(
                                     structural_rows, "predicted_set_length", "observed_set_length"),
                                 "set_game_length_distribution": set_length_distribution,
                                 "observed_deciding_set_rate": statistics.mean(r["observed_decider"] for r in structural_rows),
                                 "predicted_deciding_set_rate": statistics.mean(r["predicted_decider"] for r in structural_rows),
                                 "predicted_minus_observed_decider_rate_clustered": clustered_difference(
                                     structural_rows, "predicted_decider", "observed_decider"),
                                 "observed_match_with_tiebreak_set_rate": statistics.mean(r["observed_tiebreak"] for r in structural_rows),
                                 "predicted_match_with_tiebreak_set_rate": statistics.mean(r["predicted_tiebreak"] for r in structural_rows),
                                 "predicted_minus_observed_match_with_tiebreak_set_rate_clustered": clustered_difference(
                                     structural_rows, "predicted_tiebreak", "observed_tiebreak")},
        "live_capture_point_totals": live,
        "late_capture_point_context": late_context,
        "protocol": {"training_player_counts": "Verified point histories dated before the target match; 2-year half-life; k=250.",
                     "calendar_boundary": "Same-day matches are forecast before that date's point and result updates.",
                     "validation_test": "Fit probability calibration on verified BO3 matches in 2021; test once on 2022-24.",
                     "uncertainty": "Tournament-block bootstrap for paired match Brier; test point scores are averaged within match.",
                     "eligible_history": "Exact tour/year/tournament/two-player crosswalk; full match score and stats; point rows equal service-point total; known server and winner; MCP point numbers continuous.",
                     "source_year_scope": "Crosswalked point histories span 2000-2026 where main-tour results are available (current result data ends in June 2026); the formal Brier test is only 2022-24.",
                     "excluded_live": "The late-2026 US Open and Kalshi captures postdate the main match-results history, so they contribute point-label/score-state checks but no historical match-winner Brier."}
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tournament_csv = out.with_name("tournament_scores.csv")
    with tournament_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(tournament_scores[0]) if tournament_scores else
                                ["tour", "year", "tourney_id", "tournament", "matches"])
        writer.writeheader()
        writer.writerows(tournament_scores)
    out.write_text("# Four-archive tennis point model and simulator audit\n\n"
                   "Generated by `analyze_archives.py`; database inputs are opened read-only. Tournament-level test scores are in `tournament_scores.csv`.\n\n"
                   "```json\n" + json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n```\n")
    print(f"Wrote {out}", flush=True)
    print(json.dumps({"verified": len(verified), "validation": len(validation), "test": len(test),
                      "brier": overall, "point_test": report["point_test"],
                      "structure": report["simulation_structure"],
                      "late_context": late_context}, indent=2), flush=True)


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("findings.md"))
    args = parser.parse_args()
    run(args.out)


if __name__ == "__main__":
    cli()
