#!/usr/bin/env python3
"""
run_pipeline.py — Orchestrate the full Legendary Picks data plane.

Order (each step idempotent, safe to re-run):
  1. Ingest props (Bovada scraper → /api/props/ingest)
  2. Link games (prop_games → espn_event_id crosswalk)
  3. Settle finaled games (boxscore → prop_results grading)
  4. Refresh stats/rosters (full-league ingests on a slower cadence)
  5. Coverage report (SLO check)

Usage:
  venv/bin/python scripts/run_pipeline.py [--full] [--dry-run]
    --full : also run full-league stat ingests (slow — do 1-2x/day)
    --dry-run : print what would run, don't execute
"""
import sys, os, subprocess, datetime as dt, json, urllib.request

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(BACKEND, "venv", "bin", "python")
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

API_BASE = os.environ.get("LP_API_BASE", "http://localhost:8000")


def _link_leagues() -> list:
    """The leagues that actually have prop_games, read from the database.

    A literal list here would be the third one in this repo to go stale — MLS
    props existed for months before anything swept them. Falls back to nothing
    rather than to a guess: if the database cannot be read there is no work to
    scope, and inventing a league list would spend budget on leagues that may not
    have a single row.
    """
    import sqlite3
    db = os.environ.get("LP_DB_PATH") or os.path.join(BACKEND, "data", "picks.db")
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
            return [r[0] for r in con.execute(
                "SELECT DISTINCT LOWER(league) FROM prop_games "
                "WHERE date >= DATE('now', '-3 days') AND league IS NOT NULL "
                "ORDER BY 1")]
    except sqlite3.Error as e:
        print(f"    WARN: cannot read prop_games leagues ({e}); linking nothing")
        return []


def _run(cmd: list, step_name: str, timeout: int = 300, env: dict = None) -> bool:
    """Run a command, log output, return success."""
    log_file = os.path.join(LOG_DIR, f"pipeline_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{step_name}.log")
    print(f"  [{step_name}] {cmd[0]}...")
    try:
        result = subprocess.run(
            cmd, cwd=BACKEND, capture_output=True, text=True, timeout=timeout,
            env=env
        )
        with open(log_file, "w") as f:
            f.write(result.stdout)
            if result.stderr:
                f.write("\n--- STDERR ---\n")
                f.write(result.stderr)
        if result.returncode != 0:
            print(f"    ❌ FAIL (exit {result.returncode}) — log: {log_file}")
            # Print last 5 lines
            for line in result.stdout.strip().split("\n")[-5:]:
                print(f"      {line}")
            return False
        print(f"    ✅ OK — log: {log_file}")
        return True
    except subprocess.TimeoutExpired:
        print(f"    ❌ TIMEOUT ({timeout}s)")
        return False
    except Exception as e:
        print(f"    ❌ ERROR: {e}")
        return False


def step_ingest_props(dry_run: bool = False) -> bool:
    """Scrape Bovada props and ingest via API."""
    if dry_run:
        print("  [dry-run] Would scrape Bovada and POST to /api/props/ingest")
        return True
    # Run bovada_scraper for MLB only (fastest, most props)
    return _run(
        [VENV_PY, "-m", "bovada_scraper", "mlb", "--ingest"],
        "ingest_props", timeout=120
    )


def step_link_games(dry_run: bool = False) -> bool:
    """Crosswalk prop_games → ESPN event IDs, one league at a time.

    This called the linker unscoped, which asks it to reconsider every slate ever
    ingested — 54 of them, 162 requests against a host whose ceiling is ~100. The
    linker refused, correctly, on every run since the guard landed, and because a
    refusal used to exit 0 this step printed "link: ✅" on top of it every thirty
    minutes. Months of unlinked prop_games were then blamed on ESPN being down.

    Scoped per league and windowed to recent slates, each call is a handful of
    requests. The shared cache directory means the leagues that share a date pay
    for it once. A league that fails does not stop the rest: they are independent
    crosswalks and one bad vocabulary should not cost the others their run.
    """
    if dry_run:
        print("  [dry-run] Would run link_prop_games.py --league <lg> --days 3")
        return True
    env = dict(os.environ)
    env.setdefault("LP_ESPN_CACHE_DIR", os.path.join(LOG_DIR, "espn-cache"))
    ok = True
    for lg in _link_leagues():
        if not _run([VENV_PY, "link_prop_games.py", "--league", lg, "--days", "3"],
                    f"link_games_{lg}", timeout=120, env=env):
            ok = False
    return ok


def step_settle(dry_run: bool = False) -> bool:
    """Settle all finaled games with unsettled props."""
    if dry_run:
        print("  [dry-run] Would run settle_props.py")
        return True
    return _run(
        [VENV_PY, "settle_props.py"],
        "settle", timeout=300
    )


def step_refresh_stats(dry_run: bool = False) -> bool:
    """Refresh full-league stats (NHL + MLB are the heavy ones)."""
    if dry_run:
        print("  [dry-run] Would run full-league stat ingests")
        return True
    success = True
    # NHL roster + stats (fast, full coverage)
    if not _run([VENV_PY, "ingest_nhl.py"], "ingest_nhl", timeout=300):
        success = False
    # MLB Statcast (slow — full season)
    if not _run([VENV_PY, "ingest_statcast.py", "--days", "200"], "ingest_mlb", timeout=600):
        success = False
    return success


def step_coverage_report(dry_run: bool = False) -> bool:
    """Run coverage report."""
    if dry_run:
        print("  [dry-run] Would run coverage_report.py")
        return True
    return _run(
        [VENV_PY, os.path.join(SCRIPTS, "coverage_report.py")],
        "coverage", timeout=120
    )


def main():
    dry_run = "--dry-run" in sys.argv
    full = "--full" in sys.argv

    print(f"{'='*60}")
    print(f"Legendary Picks Pipeline — {dt.datetime.now().isoformat()}")
    if dry_run:
        print("DRY RUN — no changes will be made")
    print(f"{'='*60}")

    results = {}

    # Step 1: Ingest fresh props (always)
    results["ingest"] = step_ingest_props(dry_run)

    # Step 2: Link games to ESPN (always)
    results["link"] = step_link_games(dry_run)

    # Step 3: Settle finaled games (always)
    results["settle"] = step_settle(dry_run)

    # Step 4: Full-league stat refresh (only with --full)
    if full:
        results["stats"] = step_refresh_stats(dry_run)

    # Step 5: Coverage report (always, light)
    results["coverage"] = step_coverage_report(dry_run)

    # Summary
    print(f"\n{'='*60}")
    print(f"Pipeline complete:")
    for step, ok in results.items():
        print(f"  {step}: {'✅' if ok else '❌'}")
    if dry_run:
        print("  (DRY RUN)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
