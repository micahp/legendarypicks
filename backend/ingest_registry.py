#!/usr/bin/env python3
"""ingest_registry.py: the jobs that keep non-props tables fed, and how to tell they are fed.

WHY THIS EXISTS.

`backend/` holds 49 `ingest_*.py` against about 14 systemd timers. Writing an ingest and
scheduling an ingest were two separate acts joined by nothing but somebody remembering, and
on 2026-09-06 that cost was measured: `ingest_soccer_logs.py` appeared in no unit, no
crontab and no runner script. It worked, it was tested, and it had only ever run by hand.
MLS appearance rows stopped on 2026-08-08 while finaled games ran to 2026-09-05. Behind that
28-day gap sat 1,150 unsettled `goals` props, 409 `assists`, and every card market, and
`settlement/mls_settle.py` turned each missing appearance into `pending` with no error, so
settlement kept reporting success the whole time.

A registry entry makes those two acts ONE act. You cannot add a job here without declaring
its cadence, the host budget it shares, and -- the part that matters -- how an outsider can
tell whether it actually ran. `validate()` refuses the import otherwise, so the failure
happens at load, loudly, instead of as a table that quietly stops advancing.

WHAT IT IS NOT. This is not a second runner. `run_props_ingest.py` already owns the durable
`ingest_runs` ledger, `ingest_provider_state.last_ok_at` keyed per (job, db_path), cadence
skipping, host locks and the run lock. `run_ingest_jobs.py` drives THIS registry through
THAT code. Two registries, one engine, because two engines would drift.

`freshness` is the declaration `monitor_ingest_freshness.py` reads. It answers "this table
should be advancing and is not", which grep over unit files cannot: reachability by name
over-counts (a mention in a comment reads as an edge) and under-counts (runners import
runners). Whether rows arrive is the only honest instrument.
"""
from typing import Dict, List, Optional

# Jobs share the shape `run_props_ingest.PROVIDERS` uses, plus two keys that registry
# understands: `env` (per-job child environment) and `freshness` (required, see above).
#
# host_lock: jobs naming the same host_lock never run concurrently. ESPN's limit is a BURST
# RATE per host shared with the serving path, not a per-run count, so two ESPN jobs at once
# is the failure mode that took all three ESPN hosts down on 2026-08-18. See
# `.claude/skills/espn-request-budget`.
JOBS: List[Dict[str, object]] = [
    {
        "id": "soccer_logs",
        "cadence_min": 60,
        "timeout_sec": 1800,
        "host_lock": "espn",
        # The summary path answers a whole match in one request and publishes goals,
        # assists and cards. `--deep` is roughly one core-api request PER ATHLETE (~45 a
        # fixture) and buys only tackles/clearances/crosses/passes, so it is deliberately
        # not scheduled: it belongs in a hand-run backfill, not an hourly job.
        #
        # DEPENDENCY, and it is deliberate that this fails loudly until it lands: these
        # steps omit `--season`, which on `dev` today is a REQUIRED argument, so the job
        # exits 2 with argparse's own message. The fix is on branch
        # `fix/soccer-logs-pipeline`, where `--season` defaults to ESPN's published current
        # season via /seasons?limit=1. Hardcoding `--season 2026` here would make the job
        # run and silently pin the pipeline to one year, which is the failure this registry
        # exists to prevent. A job that refuses is better than a job that lies.
        "steps": [
            ["ingest_soccer_logs.py", "--league", "mls", "--request-budget", "12"],
            ["ingest_soccer_logs.py", "--league", "lcup", "--request-budget", "12"],
        ],
        # 12 calls at 4s spacing is about 15 requests in a rolling minute. The scoreboard
        # path already spends a measured ~5/min on site.web.api, and the median run of
        # requests preceding a 200 is 36/min against 63 preceding a 403.
        "env": {"LP_INGEST_MIN_INTERVAL": "4.0"},
        "needs_api_base": False,
        "freshness": [
            {
                "table": "player_game_logs",
                "date_column": "game_date",
                "where": "league = 'mls'",
                "stale_hours": 48,
                "label": "mls appearances",
            },
            {
                "table": "player_game_logs",
                "date_column": "game_date",
                "where": "league = 'lcup'",
                "stale_hours": 168,
                "label": "leagues cup appearances",
            },
        ],
    },
]

_REQUIRED = ("id", "cadence_min", "timeout_sec", "host_lock", "steps", "freshness")
_REQUIRED_FRESHNESS = ("table", "date_column", "stale_hours", "label")


class RegistryError(ValueError):
    """A job declaration that would schedule work nobody can verify ran."""


def validate(jobs: Optional[List[Dict[str, object]]] = None) -> None:
    """Refuse a job that cannot be scheduled or cannot be checked.

    Deliberately raises at import rather than returning a bool. A registry that silently
    accepts an unverifiable job is the exact defect this module exists to remove.
    """
    jobs = JOBS if jobs is None else jobs
    seen = set()
    for job in jobs:
        job_id = job.get("id")
        if not job_id or not isinstance(job_id, str):
            raise RegistryError("a job has no string id: {!r}".format(job))
        if job_id in seen:
            raise RegistryError("duplicate job id {!r}".format(job_id))
        seen.add(job_id)
        for key in _REQUIRED:
            if key not in job:
                raise RegistryError("job {!r} is missing {!r}".format(job_id, key))
        if not job["steps"]:
            raise RegistryError("job {!r} declares no steps".format(job_id))
        for step in job["steps"]:
            if not isinstance(step, (list, tuple)) or not step:
                raise RegistryError("job {!r} has a malformed step {!r}".format(job_id, step))
        for key in ("cadence_min", "timeout_sec"):
            value = job[key]
            if not isinstance(value, (int, float)) or value <= 0:
                raise RegistryError(
                    "job {!r} has a non-positive {}: {!r}".format(job_id, key, value))
        if not job["freshness"]:
            raise RegistryError(
                "job {!r} declares no freshness target. Every job must say how an outsider "
                "can tell it ran; a job nobody can check is how the soccer logs went 28 "
                "days stale while every instrument read healthy.".format(job_id))
        for target in job["freshness"]:
            for key in _REQUIRED_FRESHNESS:
                if key not in target:
                    raise RegistryError(
                        "job {!r} freshness target is missing {!r}: {!r}".format(
                            job_id, key, target))
            if not isinstance(target["stale_hours"], (int, float)) or target["stale_hours"] <= 0:
                raise RegistryError(
                    "job {!r} target {!r} has a non-positive stale_hours".format(
                        job_id, target["label"]))


def job_ids(jobs: Optional[List[Dict[str, object]]] = None) -> List[str]:
    return [job["id"] for job in (JOBS if jobs is None else jobs)]


def freshness_targets(jobs: Optional[List[Dict[str, object]]] = None):
    """Every declared target, tagged with the job responsible for feeding it."""
    for job in (JOBS if jobs is None else jobs):
        for target in job["freshness"]:
            merged = dict(target)
            merged["job"] = job["id"]
            merged["cadence_min"] = job["cadence_min"]
            yield merged


# Import-time, on purpose. See validate().
validate()
