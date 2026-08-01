#!/usr/bin/env python3
"""ppr_scoring.py — Legendary Picks PPR projection formula.

Computes fantasy PPR points from ESPN's PUBLISHED projected stat line.
This is NOT "ESPN projected points": we copy ESPN's published stats, then apply
our own explicit PPR scoring formula (the one the draft room states on the
surface). Never call the result "ESPN projected points".

Stat IDs are pinned empirically from the 2026-07-31 ESPN snapshot
(backend/data/espn_2026_snapshot_page1.json) and cross-checked against the
community-documented ESPN stat map (cwendt94/espn-api constant.py) and live
2025 payloads. See docs/GOAL-v0.6.13.md gate REG-projection-formula.

Scoring contract (PPR):
  QB    : pass_yds/25 + pass_td*4 + rush_yds/10 + rush_td*6 - int*2 - fum_lost*2
  RB/WR/TE: rec*1 + rec_yds/10 + rec_td*6 + rush_yds/10 + rush_td*6 - fum_lost*2
  K     : FGM(0-39)*3 + FGM(40-49)*4 + FGM(50+)*5 + XPM*1 - FGMiss*1
  D/ST  : sack*1 + int*2 + fum_rec*2 + def_td*6 + PA-tier (standard ESPN table)
"""
from __future__ import annotations

# ESPN kona stat IDs (measured + cross-checked, see module docstring)
STAT_IDS = {
    "games": 210,
    "pass_att": 0,
    "pass_cmp": 1,
    "pass_yds": 3,
    "pass_td": 4,
    "interceptions": 20,
    "rush_att": 23,
    "rush_yds": 24,
    "rush_td": 25,
    "receptions": 53,
    "targets": 58,
    "rec_yds": 42,
    "rec_td": 43,
    "fumbles": 68,
    "fumbles_lost": 72,
    # K (distance buckets)
    "fgm_0_39": 80,
    "fgm_40_49": 77,
    "fgm_50_plus": 74,
    "fg_made": 83,
    "fg_att": 84,
    "fg_missed": 85,
    "xp_made": 86,
    "xp_att": 87,
    # D/ST
    "def_sack": 99,
    "def_int": 95,
    "def_fumble_rec": 96,
    "def_td": 94,
    "def_safety": 98,
    "def_points_allowed": 120,
    "def_yds_allowed": 127,
}

# Standard ESPN D/ST points-allowed tier (the draft room labels PPR; D/ST uses
# the classic tier table — documented on the surface).
_PA_TIERS = [
    (0, 0, 10.0),
    (1, 6, 7.0),
    (7, 13, 4.0),
    (14, 20, 1.0),
    (21, 27, 0.0),
    (28, 34, -1.0),
    (35, 10_000, -4.0),
]


def pa_tier(points_allowed: float) -> float:
    if points_allowed is None:
        return 0.0
    for lo, hi, pts in _PA_TIERS:
        if lo <= points_allowed <= hi:
            return pts
    return 0.0


def qb_ppr(pass_yds, pass_td, rush_yds, rush_td, interceptions, fumbles_lost) -> float | None:
    inputs = (pass_yds, pass_td, rush_yds, rush_td, interceptions, fumbles_lost)
    if all(x is None for x in inputs):
        return None  # no scoreable stat present (e.g. return-specialist map) — honest null
    return (
        (pass_yds or 0) / 25
        + (pass_td or 0) * 4
        + (rush_yds or 0) / 10
        + (rush_td or 0) * 6
        - (interceptions or 0) * 2
        - (fumbles_lost or 0) * 2
    )


def skill_ppr(receptions, rec_yds, rec_td, rush_yds, rush_td, fumbles_lost) -> float | None:
    inputs = (receptions, rec_yds, rec_td, rush_yds, rush_td, fumbles_lost)
    if all(x is None for x in inputs):
        return None  # no scoreable stat present — honest null
    return (
        (receptions or 0) * 1
        + (rec_yds or 0) / 10
        + (rec_td or 0) * 6
        + (rush_yds or 0) / 10
        + (rush_td or 0) * 6
        - (fumbles_lost or 0) * 2
    )


def kicker_ppr(fgm_0_39, fgm_40_49, fgm_50_plus, xp_made, fg_missed) -> float | None:
    inputs = (fgm_0_39, fgm_40_49, fgm_50_plus, xp_made, fg_missed)
    if all(x is None for x in inputs):
        return None  # no scoreable stat present — honest null
    return (
        (fgm_0_39 or 0) * 3
        + (fgm_40_49 or 0) * 4
        + (fgm_50_plus or 0) * 5
        + (xp_made or 0) * 1
        - (fg_missed or 0) * 1
    )


def dst_ppr(sacks, ints, fumble_rec, def_td, points_allowed) -> float | None:
    inputs = (sacks, ints, fumble_rec, def_td, points_allowed)
    if all(x is None for x in inputs):
        return None  # no scoreable stat present — honest null
    return (
        (sacks or 0) * 1
        + (ints or 0) * 2
        + (fumble_rec or 0) * 2
        + (def_td or 0) * 6
        + pa_tier(points_allowed)
    )


def normalize_stats(stats: dict | None) -> dict:
    """ESPN stat maps arrive via JSON with STRING keys ("42"). Normalize to
    int keys so lookups work regardless of the source's key type."""
    out: dict = {}
    for k, v in (stats or {}).items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            continue
    return out


def project_ppr(position: str, stats: dict) -> float | None:
    """Compute LP PPR projected points from an ESPN stat map.

    Returns None when the player has no usable stat map (honest null — the
    caller stores NULL, never 0).
    """
    stats = normalize_stats(stats)
    if not stats:
        return None
    pos = (position or "").upper()
    if pos == "QB":
        return qb_ppr(
            stats.get(STAT_IDS["pass_yds"]),
            stats.get(STAT_IDS["pass_td"]),
            stats.get(STAT_IDS["rush_yds"]),
            stats.get(STAT_IDS["rush_td"]),
            stats.get(STAT_IDS["interceptions"]),
            stats.get(STAT_IDS["fumbles_lost"]),
        )
    if pos in ("RB", "WR", "TE"):
        return skill_ppr(
            stats.get(STAT_IDS["receptions"]),
            stats.get(STAT_IDS["rec_yds"]),
            stats.get(STAT_IDS["rec_td"]),
            stats.get(STAT_IDS["rush_yds"]),
            stats.get(STAT_IDS["rush_td"]),
            stats.get(STAT_IDS["fumbles_lost"]),
        )
    if pos == "PK":
        return kicker_ppr(
            stats.get(STAT_IDS["fgm_0_39"]),
            stats.get(STAT_IDS["fgm_40_49"]),
            stats.get(STAT_IDS["fgm_50_plus"]),
            stats.get(STAT_IDS["xp_made"]),
            stats.get(STAT_IDS["fg_missed"]),
        )
    if pos == "DEF":
        return dst_ppr(
            stats.get(STAT_IDS["def_sack"]),
            stats.get(STAT_IDS["def_int"]),
            stats.get(STAT_IDS["def_fumble_rec"]),
            stats.get(STAT_IDS["def_td"]),
            stats.get(STAT_IDS["def_points_allowed"]),
        )
    return None
