#!/usr/bin/env python3
"""Static 2026 RB entry-weight audit using frozen walk-forward assets.

This is NOT a simulation or player-prop backtest. For the first offensive snap
conditional on 11 personnel, compare the eligible RB/FB entry draw against
the target game's *observed relative RB/HB/FB snap distribution*.

The outcome is intentionally never used as a pregame feature. The nine prior
snap-count cuts were reconstructed from the 2026-11-10 source capture;
their historical publication integrity is NOT established.

Usage:
    python3 scripts/nfl_sequence/audit_rb_entry_2026.py
    python3 scripts/nfl_sequence/audit_rb_entry_2026.py --out /tmp/rb-entry-audit.json
"""
import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs/research/walkforward-2026"
FIELD = ROOT / "docs/research/participation-model-2026-11-02/outputs/field_v4_2022_2025.json"
GROUP = "11"
PRIOR_PLAYS = 20.0
MIX_LEAGUE_PLAYS = 50.0
WEIGHT_MIN, WEIGHT_MAX = 0.02, 50.0
GROUP_PATTERN = re.compile(r"^\d\d(?:-(?:OL|QB)\d+)*$")
PLAYER_N0 = 1.0
SKILL = {"RB", "FB"}
OBSERVED_SKILL = {"RB", "HB", "FB"}


def norm_team(team):
    return {"LAR": "LA", "WSH": "WAS"}.get(team, team)


def load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class Historical:
    def __init__(self, data):
        self.apps = {(pid, team, group): float(n) for pid, team, group, n in data["appearances"]}
        self.plays = {(team, group): float(n) for team, group, n in data["team_plays"]}
        self.prior = {(pos, group): float(n) for pos, group, n in data["position_prior"]}
        league = Counter()
        for (team, group), count in self.plays.items():
            if GROUP_PATTERN.fullmatch(group):
                league[group] += count
        denom = sum(league.values())
        assert denom > 0
        self.mix = {}
        for team, _ in self.plays:
            if team in self.mix:
                continue
            groups = {
                group: self.plays.get((team, group), 0) + MIX_LEAGUE_PLAYS * count / denom
                for group, count in league.items()
            }
            self.mix[team] = (groups, sum(groups.values()))

    def rate(self, pid, team, group, position):
        return ((self.apps.get((pid, team, group), 0)
                 + PRIOR_PLAYS * self.prior.get((position, group), 0))
                / (self.plays.get((team, group), 0) + PRIOR_PLAYS))

    def table_rate(self, pid, team, position):
        """Equivalent to snap_update.table_rate() with no player weight."""
        mix, total = self.mix[team]
        return sum(weight * self.rate(pid, team, group, position)
                   for group, weight in mix.items()) / total


class Counts:
    def __init__(self, data):
        self.week = int(data["through_week"])
        self.team_snaps = {(norm_team(t), int(w)): float(n)
                           for t, w, n in data["team_snaps"]}
        self.player = defaultdict(dict)
        self.actual_rb = defaultdict(dict)
        self.active = {(norm_team(t), int(w)): set(ids)
                       for t, w, ids in data["active"]}
        for t, w, pid, pos, n in data["player_snaps"]:
            team, week = norm_team(t), int(w)
            self.player[team, week][pid] = float(n)
            if pos in OBSERVED_SKILL:
                self.actual_rb[team, week][pid] = (
                    self.actual_rb[team, week].get(pid, 0) + float(n))

    def player_share_before(self, team, week, pid):
        active_games = 0
        team_snaps = player_snaps = 0.0
        for w in range(1, week):
            snaps = self.team_snaps.get((team, w))
            if snaps is None:
                continue
            played = self.player.get((team, w), {})
            if pid in played or pid in self.active.get((team, w), ()):
                active_games += 1
                team_snaps += snaps
                player_snaps += played.get(pid, 0)
        return active_games, player_snaps / team_snaps if team_snaps else 0.0


def entry_probabilities(roster, week, hist, prior):
    """Same conditional group-11 first-entry weighting as Field._weighted.

    HS = snap_update PLAYER_N0=1 update with historical table-average denominator.
    HE = unblended current-season entry weights (for players with prior active games).
    Rotation and grouping frequencies are deliberately not modelled here.
    """
    team = norm_team(roster["team"])
    injury = {p["gsis_id"]: p["report_status"]
              for p in (roster.get("injury_report") or {}).get("players", [])}
    candidates = {}
    for p in roster["players"]:
        if p["pos_abb"] not in SKILL or p.get("roster_eligible") is False:
            continue
        if injury.get(p["gsis_id"]) in ("Out", "Doubtful"):
            continue
        old = candidates.get(p["gsis_id"])
        if old is None or p["pos_rank"] < old["pos_rank"]:
            candidates[p["gsis_id"]] = p
    values = {}
    for pid, p in candidates.items():
        historical = hist.rate(pid, team, GROUP, "RB")
        earlier_games, share = prior.player_share_before(team, week, pid)
        base = hist.table_rate(pid, team, p["pos_abb"])
        if earlier_games:
            weight = ((PLAYER_N0 * base + earlier_games * share)
                      / (PLAYER_N0 + earlier_games)) / base if base > 0 else WEIGHT_MAX
            weight = min(WEIGHT_MAX, max(WEIGHT_MIN, weight))
        else:
            weight = 1.0
        values[pid] = {
            "name": p["player_name"], "position": p["pos_abb"],
            "rank": p["pos_rank"], "history_11_appearances":
                hist.apps.get((pid, team, GROUP), 0),
            "prior_active_games": earlier_games,
            "prior_snap_share": share,
            "historical": max(historical, 1e-9),
            "hs": max(historical * weight, 1e-9),
            "he": max(share if earlier_games else historical, 1e-9),
        }
    for arm in ("historical", "hs", "he"):
        total = sum(v[arm] for v in values.values())
        for v in values.values():
            v[arm] = v[arm] / total if total else 0.0
    return values, injury


def score(probs, actual):
    total = sum(actual.values())
    if total <= 0:
        return None
    targets = {pid: n / total for pid, n in actual.items()}
    out = {"observed_rb_snaps": total}
    leader = max(targets, key=targets.get)
    out["observed_leader_id"] = leader
    out["roster_coverage_fraction"] = sum(
        share for pid, share in targets.items() if pid in probs)
    for arm in ("historical", "hs", "he"):
        out[arm + "_tv"] = sum(
            abs(probs.get(pid, {}).get(arm, 0) - targets.get(pid, 0))
            for pid in probs.keys() | targets.keys()) / 2
        out[arm + "_top_correct"] = (
            bool(probs) and max(probs, key=lambda pid: probs[pid][arm]) == leader)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    hist = Historical(load_json(FIELD))
    outcome = Counts(load_json(ASSETS / "snap-counts/through_week09.json"))
    snapshots = sorted((ASSETS / "snapshots").glob("w??/2026_*.json"))
    if len(snapshots) != 150:
        raise ValueError(f"expected 150 walk-forward snapshots; got {len(snapshots)}")
    prior_files = {
        week: Counts(load_json(ASSETS / f"snap-counts/through_week{week-1:02d}.json"))
        for week in range(2, 11)
    }
    rows = []
    for path in snapshots:
        game = load_json(path)
        week = int(game["schedule"]["week"])
        prior = prior_files.get(week)
        for side in ("away", "home"):
            roster = game["rosters"][side]
            team = norm_team(roster["team"])
            if week > 1 and prior.week != week - 1:
                raise ValueError(f"wrong prior cut: {week=}, {prior.week=}")
            probabilities, injury = entry_probabilities(
                roster, week, hist, prior if prior else Counts({
                    "through_week": 0, "team_snaps": [], "player_snaps": [], "active": []}))
            rb1 = next((p for p in roster["players"]
                        if p["pos_abb"] == "RB" and p["pos_rank"] == 1), None)
            measured = score(probabilities, outcome.actual_rb.get((team, week), {})) if week <= 9 else None
            row = {
                "week": week, "game_id": game["schedule"]["game_id"],
                "team": roster["team"], "as_of": game["as_of"],
                "snapshot_verified": game["evaluation"]["verified"],
                "rb_candidates": len(probabilities),
                "rb1": rb1["player_name"] if rb1 else None,
                "rb1_status": injury.get(rb1["gsis_id"], "unlisted") if rb1 else None,
                "rb1_probabilities": {
                    arm: probabilities.get(rb1["gsis_id"], {}).get(arm)
                    for arm in ("historical", "hs", "he")
                } if rb1 else None,
                "rb1_2022_25_team_group11_appearances": (
                    hist.apps.get((rb1["gsis_id"], team, GROUP), 0) if rb1 else None),
                "rb1_prior_active_games": (
                    probabilities.get(rb1["gsis_id"], {}).get("prior_active_games") if rb1 else None),
                "observed": measured,
            }
            rows.append(row)
    by_week = {}
    for week in range(1, 11):
        week_rows = [r for r in rows if r["week"] == week]
        graded = [r["observed"] for r in week_rows if r["observed"] is not None]
        by_week[week] = {
            "games": len(week_rows) // 2,
            "team_games": len(week_rows),
            "evaluable_team_games": len(graded),
            "mean_tv": {
                arm: sum(row[arm + "_tv"] for row in graded) / len(graded)
                for arm in ("historical", "hs", "he")
            } if graded else None,
            "missing_observed_rb_snaps_teams": [
                row["team"] for row in week_rows if row["observed"] is None
            ] if week <= 9 else [],
        }
    report = {
        "scope": "Static first RB-slot draw conditional on 11 personnel; not full simulation",
        "field_source": str(FIELD.relative_to(ROOT)),
        "snapshot_count": len(snapshots), "team_game_rows": len(rows),
        "outcome_source": "2026 through_week09 reconstructed 2026-11-10 source copy",
        "historical_capture_integrity_verified": False,
        "week_summary": by_week, "rows": rows,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"Wrote {args.out}")
    print(json.dumps({"snapshot_count": len(snapshots),
                      "team_game_rows": len(rows), "week_summary": by_week}, indent=2))


if __name__ == "__main__":
    main()
