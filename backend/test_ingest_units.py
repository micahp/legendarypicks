"""Static contract for the uninstalled ingest-registry units.

Retargeted from an earlier `test_soccer_logs_service_units.py`, which guarded a per-ingest
soccer unit. That unit was dropped in favour of one registry timer, because a timer per
ingest is the pattern that lost `ingest_soccer_logs.py` for 28 days. The assertions are the
ones that were worth keeping: one ExecStart, dev before prod, and an absolute calendar.
"""
from pathlib import Path

UNITS = Path(__file__).resolve().parents[1] / "ops" / "systemd"


def _uncommented(text):
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def test_the_job_service_runs_dev_then_prod_in_one_execstart():
    """systemd abandons later ExecStart lines of a oneshot once one exits non-zero, so a
    second line would let a dev failure silently cancel prod."""
    text = (UNITS / "legendarypicks-ingest-jobs.service").read_text()
    assert text.count("ExecStart=") == 1
    assert text.index("picks.dev.db") < text.index("data/picks.db")
    assert "run_ingest_jobs.py" in text


def test_freshness_is_a_separate_unit_from_the_ingest():
    """One shared colour for "the ingest failed" and "the data is stale" is how soccer sat
    696h stale while nothing ever failed."""
    jobs = (UNITS / "legendarypicks-ingest-jobs.service").read_text()
    fresh = (UNITS / "legendarypicks-ingest-freshness.service").read_text()
    assert "monitor_ingest_freshness.py" in fresh
    assert "monitor_ingest_freshness.py" not in jobs


def test_both_timers_are_absolute_and_never_monotonic():
    """A monotonic timer whose reference activation systemd forgot reports enabled and
    active with no next elapse. That parked the Bovada timers for three days."""
    for name in ("legendarypicks-ingest-jobs.timer",
                 "legendarypicks-ingest-freshness.timer"):
        text = (UNITS / name).read_text()
        assert "OnCalendar=" in text, name
        assert "OnBootSec=" not in text, name
        assert "OnUnitActiveSec=" not in text, name
        assert "Persistent=true" in text, name


def test_the_two_timers_do_not_fire_at_the_same_minute():
    """A check must not race the job it checks."""
    def minutes(name):
        return {l.split("=", 1)[1].strip()
                for l in _uncommented((UNITS / name).read_text()).splitlines()
                if l.startswith("OnCalendar=")}
    assert not (minutes("legendarypicks-ingest-jobs.timer")
                & minutes("legendarypicks-ingest-freshness.timer"))


def test_the_registry_timer_does_not_collide_with_the_props_timer():
    """Two batch jobs must not spend the same publisher's per-minute budget at once."""
    def minutes(name):
        return {l.split("=", 1)[1].strip()
                for l in _uncommented((UNITS / name).read_text()).splitlines()
                if l.startswith("OnCalendar=")}
    assert not (minutes("legendarypicks-ingest-jobs.timer")
                & minutes("legendarypicks-props.timer"))


def test_no_per_ingest_soccer_unit_survives():
    """The dropped units must stay dropped: installing both would double the ESPN spend."""
    assert not (UNITS / "legendarypicks-soccer-logs.service").exists()
    assert not (UNITS / "legendarypicks-soccer-logs.timer").exists()
