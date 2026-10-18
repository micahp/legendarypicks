"""The weekly availability refresh must rebuild player_game_availability after its inputs.

Review finding P1 (2026-10-10): the refresh ingested weekly stats, snaps and injuries and exited,
so the derived table went stale. These tests run the real script with every step stubbed, so they
observe the order of steps the script issues, not its text.
"""
import os
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "nfl-availability.sh")


def run_refresh(fail_step=None):
    """Run the script with run_step/log stubbed; return the list of (env, step) it ran."""
    with tempfile.TemporaryDirectory() as d:
        calls = os.path.join(d, "calls")
        dev_db = os.path.join(d, "dev.db")
        prod_db = os.path.join(d, "prod.db")
        for p in (dev_db, prod_db):
            open(p, "w").close()
        src = open(SCRIPT).read()
        src = src.replace("cd /root/legendarypicks/backend", "cd " + d)
        src = src.replace("DEV_DB=/root/legendarypicks/backend/data/picks.dev.db", "DEV_DB=" + dev_db)
        src = src.replace("PROD_DB=/root/legendarypicks/backend/data/picks.db", "PROD_DB=" + prod_db)
        lib = os.path.join(d, "lib.sh")
        with open(lib, "w") as f:
            f.write(
                "STEP_FAILURES=0; FAILED_STEPS=''\n"
                "log(){ :; }\nfinish(){ :; }\n"
                "run_step(){ shift; echo \"$LP_STEP_LABEL $1\" >> %s;"
                " if [ \"$1\" = \"%s\" ]; then STEP_FAILURES=$((STEP_FAILURES+1)); fi; }\n"
                % (calls, fail_step or "")
            )
        src = src.replace(". /root/legendarypicks/scripts/news-lib.sh", ". " + lib)
        # The season probe is a python heredoc; the stub PY prints a season.
        fake_py = os.path.join(d, "py")
        with open(fake_py, "w") as f:
            f.write("#!/bin/sh\ncat >/dev/null\necho 2026\n")
        os.chmod(fake_py, 0o755)
        src = src.replace("PY=/root/legendarypicks/backend/venv/bin/python", "PY=" + fake_py)
        script = os.path.join(d, "refresh.sh")
        with open(script, "w") as f:
            f.write(src)
        for marker in ("/root/legendarypicks/backend/data/picks", "news-lib.sh", "venv/bin/python"):
            assert marker not in src, "stub did not replace " + marker
        subprocess.run(["bash", script], check=True, capture_output=True, timeout=30)
        return [tuple(line.split()) for line in open(calls).read().splitlines()]


class RefreshRebuild(unittest.TestCase):
    def test_dev_rebuilds_availability_after_all_three_inputs(self):
        dev = [step for env, step in run_refresh() if env == "DEV"]
        self.assertIn("migrate_player_game_availability.py", dev)
        build = dev.index("migrate_player_game_availability.py")
        for step in ("ingest_nfl_weekly_stats.py", "ingest_nfl_snap_counts.py", "ingest_nfl_injuries.py"):
            self.assertLess(dev.index(step), build)

    def test_failed_input_skips_the_rebuild(self):
        dev = [step for env, step in run_refresh(fail_step="ingest_nfl_snap_counts.py") if env == "DEV"]
        self.assertNotIn("migrate_player_game_availability.py", dev)

    def test_prod_is_never_rebuilt(self):
        prod = [step for env, step in run_refresh() if env == "PROD"]
        self.assertIn("ingest_nfl_snap_counts.py", prod)
        self.assertNotIn("migrate_player_game_availability.py", prod)


if __name__ == "__main__":
    unittest.main()
