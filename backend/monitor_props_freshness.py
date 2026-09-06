#!/usr/bin/env python3
"""
monitor_props_freshness.py — guard against props data silently dropping off.

Prod once went 8 days stale because nothing was feeding it AND nothing noticed. This checks each
provider's most-recent prop capture in each environment; if it is older than four times that
provider's cadence it logs a loud ALERT and exits non-zero so the systemd timer records a failure.
It deliberately reports only and never starts an ingest service.

Add an env to ENVS the moment it is supposed to be fed (prod → enable at deploy, once prod has its
own ingest service).
"""
import datetime as dt
import os
import sqlite3
import sys

from run_props_ingest import PROVIDERS

# env -> backend base url. Keep these stable because they are the existing environment identities.
ENVS = {
    "dev": "http://127.0.0.1:8096",
    "prod": "http://127.0.0.1:8100",
}

HERE = os.path.dirname(os.path.abspath(__file__))
DB_BY_BASE = {
    ENVS["dev"]: os.path.join(HERE, "data", "picks.dev.db"),
    ENVS["prod"]: os.path.join(HERE, "data", "picks.db"),
}
SOURCE_TO_PROVIDER = {
    "bovada": "bovada",
    "underdog": "underdog",
    "rotowire:prizepicks": "rotowire",
    "rotowire:underdog": "rotowire",
    "rotowire:sleeper": "rotowire",
}
# Historical Kambi rows remain useful for settled-prop analysis, but Kambi is no longer a
# configured publisher. Naming it here distinguishes an intentionally retired source from a
# new, unmapped label without pretending it is fresh or expecting it to run.
RETIRED_SOURCES = {
    "kambi",
    # PrizePicks is not a configured provider: `ingest_prizepicks_props.py` takes a
    # projections.json path by hand and no timer, cron or registry entry runs it. Its rows
    # stopped on 2026-08-25 because nobody ran it, not because a feed broke, so alerting on
    # them every run reported a decision as a failure.
    "prizepicks",
    "prizepicks-demon",
    "prizepicks-goblin",
}
KNOWN_PROVIDER_IDS = {provider["id"] for provider in PROVIDERS}
PROVIDER_STALE_HOURS = {
    provider["id"]: 4 * provider["cadence_min"] / 60.0 for provider in PROVIDERS
}


def resolve_provider(source):
    """Map a props `source` label to the provider id that publishes it.

    Rotowire emits one label per sportsbook (`rotowire:draftkings-sb`, `rotowire:pick6`,
    `rotowire:betr`, ...) and adds books whenever it likes. Enumerating them meant every new
    book counted as an unknown source and failed this check, which is a claim about our list,
    not about whether rotowire is publishing. The label already carries its provider in the
    prefix, so read the publisher's own encoding. A book going quiet is absorbed by the
    provider's own freshness, which is the question this monitor exists to answer.

    Returns (provider_id, derived). `derived` is True when the prefix answered it, so the
    caller can still say out loud that it saw a label nobody declared.
    """
    if source in SOURCE_TO_PROVIDER:
        return SOURCE_TO_PROVIDER[source], False
    prefix = source.split(":", 1)[0]
    if prefix in KNOWN_PROVIDER_IDS:
        return prefix, True
    return None, False


def latest_capture(base):
    """Newest capture timestamp for every source in one environment's local DB."""
    db_path = DB_BY_BASE[base]
    with sqlite3.connect(db_path, timeout=20) as con:
        rows = con.execute(
            "SELECT source, max(captured_at) FROM props GROUP BY source"
        ).fetchall()
    return {source: _parse_timestamp(captured_at) for source, captured_at in rows}


def _parse_timestamp(value):
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def main():
    now = dt.datetime.now(dt.timezone.utc)
    stale = []
    for env, base in ENVS.items():
        try:
            by_source = latest_capture(base)
        except Exception as e:
            print(f"ALERT [{env}] props freshness check FAILED: {e} ({base})", flush=True)
            stale.append(env)
            continue
        if not by_source:
            print(f"ALERT [{env}] no props in DB at all ({base})", flush=True)
            stale.append(env)
            continue

        provider_captures = {provider["id"]: [] for provider in PROVIDERS}
        for source, captured_at in by_source.items():
            if source in RETIRED_SOURCES:
                print(f"INFO [{env}] RETIRED SOURCE {source}: excluded from freshness", flush=True)
                continue
            provider_id, derived = resolve_provider(source)
            if provider_id is None:
                print(f"ALERT [{env}] UNKNOWN SOURCE {source}", flush=True)
                stale.append(f"{env}:{source}")
                continue
            if derived:
                # Visible, but not a failure: the prefix is evidence, an absent list entry is not.
                print(f"INFO [{env}] {source}: counted under {provider_id} (from label prefix)",
                      flush=True)
            if captured_at is not None:
                provider_captures[provider_id].append(captured_at)

        for provider in PROVIDERS:
            provider_id = provider["id"]
            captures = provider_captures[provider_id]
            threshold_h = PROVIDER_STALE_HOURS[provider_id]
            if not captures:
                print(f"ALERT [{env}] {provider_id} has no props in DB", flush=True)
                stale.append(f"{env}:{provider_id}")
                continue
            latest = max(captures)
            age_h = (now - latest).total_seconds() / 3600
            if age_h > threshold_h:
                print(
                    f"ALERT [{env}] {provider_id} STALE: last capture {latest.isoformat()} "
                    f"({age_h:.1f}h ago, threshold {threshold_h:g}h)",
                    flush=True,
                )
                stale.append(f"{env}:{provider_id}")
            else:
                print(f"OK [{env}] {provider_id} fresh: last capture {age_h:.1f}h ago", flush=True)

    if stale:
        sys.exit(1)  # non-zero makes the existing monitor timer record the failure


if __name__ == "__main__":
    main()
