"""Grade all twelve week-10 games across the six arms, per game, per tier.

Each arm is graded from whichever tier has it complete: the frozen 1,000-seed
block when that exists (NE_DET, BUF_NYJ, and the main arms of the games that
finished before the stop), otherwise the 100-seed block in runs100/. The two
tiers are never mixed inside one arm - a 100-seed block reuses seeds
300001-300100, so mixing would double-count.

Writes, per game, the family and prop grading reports from grade_ne_det.py and
grade_ne_det_props.py, plus one aggregate table across all twelve games.
"""
import json, sqlite3, subprocess, sys
from pathlib import Path

BASE = Path("/root/ot-sim-out/week10-family-2026-11-15")
OUT = Path("/root/lp-slc-v2/docs/research/week10-family-2026-11-15/all-games")
ARMS = ("v1", "v1.5", "v1.6", "v1.7", "v1.7-pr43", "v2")
BIG = BASE / "runs"
SMALL = BASE / "runs100"
PROPS_DB = BASE / "props_week10.db"
CAVEAT_MD = """**Read with [../GRADING-CAVEATS.md](../GRADING-CAVEATS.md):** two tiers - 1,000-seed
blocks and 100-seed blocks - never mixed inside one arm. The binding precision limit is Monte
Carlo error, not the 0.01 step: one game's win probability is a single Bernoulli draw, and the
12-game arm spread of ~0.04 is inside one standard error (~0.06). Two seeds are excluded as
simulation errors (HOU_CLE v1.7 seed 300055, JAX_TEN v1.7-pr43 seed 300088;
`sack_fumble_lost` past the goal line - repair in PR #49). The v1.7 arms are PR #42 `6ac6180c`
and PR #43 `984751d5` at `--slc-profile v1_full_stack`, not PR #47 `v1_7_candidate`, so these
numbers do not validate the PR #47 candidate.
"""
SEED_FAILURES = [
    {"game": "2026_10_HOU_CLE", "arm": "v1.7", "seed": 300055, "valid_seeds": 99,
     "status": "simulation_error", "failure_class": "FootballAssertionError/ILLEGAL_STATE",
     "violated_assertion": "sack_fumble_lost loss -9 carries the ball past its own goal line"},
    {"game": "2026_10_JAX_TEN", "arm": "v1.7-pr43", "seed": 300088, "valid_seeds": 99,
     "status": "simulation_error", "failure_class": "FootballAssertionError/ILLEGAL_STATE",
     "violated_assertion": "sack_fumble_lost loss -9 carries the ball past its own goal line"},
]
ESPN = BASE / "inputs"


def big_complete(arm, game):
    files = sorted((BIG / arm).glob("%s-seed-*.json" % game))
    if len(files) != 4:
        return False
    total = 0
    for path in files:
        total += sum((json.loads(path.read_text())["summary"].get("status_counts") or {}).values())
    return total == 1000


def tier(arm, game):
    return "1000-seed" if big_complete(arm, game) else "100-seed"


def main():
    db = sqlite3.connect("file:%s?mode=ro" % PROPS_DB, uri=True)
    games = db.execute("SELECT id, home, away, espn_event_id, start_time FROM games ORDER BY start_time").fetchall()
    db.close()
    OUT.mkdir(parents=True, exist_ok=True)

    rows, failures, pending = [], [], []
    for prop_id, _db_home, _db_away, event, start in games:
        espn = ESPN / ("espn_%s.json" % event)
        if not espn.is_file():
            failures.append({"game": event, "error": "missing espn summary %s" % espn})
            continue
        summary = json.loads(espn.read_text())
        comp = summary["header"]["competitions"][0]
        status = comp["status"]["type"]["name"]
        sides = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        home, away = sides["home"].replace("LAR", "LA"), sides["away"].replace("LAR", "LA")
        gid = "2026_10_%s_%s" % (away, home)
        staging = BASE / ("staging-" + gid)
        staging.mkdir(exist_ok=True)
        tiers = {}
        for arm in ARMS:
            t = tier(arm, gid)
            tiers[arm] = t
            link = staging / arm
            target = BIG / arm if t == "1000-seed" else SMALL / arm
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(target)
        if status != "STATUS_FINAL":
            pending.append({"game": gid, "status": status})
            continue
        cmd = [sys.executable, str(BASE / "grade_ne_det.py"), "--runs", str(staging), "--espn", str(espn),
               "--game", gid, "--home-away", "%s,%s" % (home, away), "--out-dir", str(OUT)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode:
            failures.append({"game": gid, "stage": "family", "error": proc.stderr[-400:]})
            continue
        cmd = [sys.executable, str(BASE / "grade_ne_det_props.py"), "--runs", str(staging), "--espn", str(espn),
               "--game", gid, "--prop-game-id", str(prop_id), "--kickoff", start.replace("+00:00", "Z"),
               "--props-db", str(PROPS_DB), "--out-dir", str(OUT)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        prop_ok = proc.returncode == 0
        if not prop_ok:
            failures.append({"game": gid, "stage": "props", "error": proc.stderr[-400:]})

        fam = json.loads((OUT / ("%s-family-grading.json" % gid)).read_text())
        prop = json.loads((OUT / ("%s-prop-grading.json" % gid)).read_text()) if prop_ok else None
        for arm in ARMS:
            block = fam["game_level"].get(arm) or {}
            rows.append({
                "game": gid, "home": home, "away": away, "arm": arm, "tier": tiers[arm],
                "valid_seeds": block.get("valid_seeds"),
                "p_home": block.get("p_home_win"),
                "home_win_brier": block.get("home_win_brier"),
                "score_error": block.get("combined_score_error"),
                "prop_brier": (prop or {}).get("summary", {}).get(arm, {}).get("brier"),
                "prop_items": (prop or {}).get("summary", {}).get(arm, {}).get("n"),
                "market_prop_brier": (prop or {}).get("summary", {}).get("market", {}).get("brier"),
                "final": fam.get("final_score"),
            })

    (OUT / "all-games-grading.json").write_text(json.dumps(
        {"rows": rows, "failures": failures, "pending_not_final": pending,
         "caveats": {
             "tier_counts": {t: sum(1 for r in rows if r.get("tier") == t)
                             for t in ("1000-seed", "100-seed")},
             "seed_failures": SEED_FAILURES,
             "profile": {"v1.7": "PR #42 6ac6180c, feature/slc-v1.7-penalty-model-2026-11-12",
                         "v1.7-pr43": "PR #43 984751d5, fix/slc-v1.7-fractional-state-precision-2026-11-13",
                         "slc_profile": "v1_full_stack", "playcall_pass_label_mode": "conditional",
                         "note": "not PR #47 v1_7_candidate; these results do not validate PR #47"}}},
        indent=2, sort_keys=True) + "\n")

    lines = ["# Week 10, all twelve games: SLC family grading", "",
             "Per game, per arm. Tier says which batch the numbers come from: `1000-seed` for the",
             "frozen blocks, `100-seed` for the blocks re-run after the stop. Tiers are never mixed",
             "inside one arm.", "", CAVEAT_MD, "",
             "## Game level", "",
             "| Game | Tier | Arm | Seeds | P(home) | Home Brier | Score error |", "|---|---|---|---:|---:|---:|---:|"]
    for r in sorted(rows, key=lambda r: (r["game"], r["arm"])):
        if r["valid_seeds"] is None:
            continue
        lines.append("| %s | %s | %s | %d | %.1f%% | %.3f | %.2f |" % (
            r["game"].replace("2026_10_", ""), r["tier"], r["arm"], r["valid_seeds"],
            100 * r["p_home"], r["home_win_brier"], r["score_error"]))
    lines += ["", "## Prop level (pre-kickoff lines)", "",
              "| Game | Arm | Tier | Items | Prop Brier | Market Brier |", "|---|---|---|---:|---:|---:|"]
    for r in sorted(rows, key=lambda r: (r["game"], r["arm"])):
        if r["prop_brier"] is None:
            continue
        lines.append("| %s | %s | %s | %d | %.4f | %s |" % (
            r["game"].replace("2026_10_", ""), r["arm"], r["tier"], r["prop_items"], r["prop_brier"],
            "-" if r["market_prop_brier"] is None else "%.4f" % r["market_prop_brier"]))
    (OUT / "ALL-GAMES-GRADING.md").write_text("\n".join(lines) + "\n")
    if pending:
        lines_pending = ["", "Pending: still in progress at grading time - " +
                         ", ".join("%s (%s)" % (p["game"].replace("2026_10_", ""), p["status"]) for p in pending)]
        with (OUT / "ALL-GAMES-GRADING.md").open("a") as fh:
            fh.write("\n".join(lines_pending) + "\n")
    print("graded", len({r["game"] for r in rows}), "games,", len(rows), "arm-rows, failures:", len(failures))
    for f in failures:
        print("FAIL", f)


if __name__ == "__main__":
    main()
