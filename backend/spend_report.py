#!/usr/bin/env python3
"""What we actually spend on outbound requests, read off the spend log.

    venv/bin/python spend_report.py                 last 24h
    venv/bin/python spend_report.py --hours 168     last week
    venv/bin/python spend_report.py --host site.web.api.espn.com

Written 2026-08-18 because every figure we have about ESPN's limit except the
response cap is INFERRED from behaviour (docs/DESIGN-request-budget.md §1).
The question this exists to answer is the one in §4:

    does a 403 correlate with a request count, or with a time of day,
    or with nothing?

If refusals cluster after a run of requests, the per-host count wall is real
and a shared counter is the right machine. If they do not, the wall is not what
we think it is, and the work is chunking and caching instead. Either way it is
answered from data rather than from a sentence somebody remembers.
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paced_http


def _load(path, hours):
    import datetime as dt
    cutoff = (dt.datetime.utcnow() - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # a torn line is one lost record, not a dead report
                if row.get("ts", "") >= cutoff:
                    rows.append(row)
    except FileNotFoundError:
        return None
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", default=paced_http.SPEND_LOG)
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--host", help="restrict to one host")
    args = ap.parse_args(argv)

    rows = _load(args.log, args.hours)
    if rows is None:
        print(f"no spend log at {args.log}. Nothing has run since it was added,")
        print("or LP_HTTP_SPEND_LOG points elsewhere. Absent evidence is not a zero.")
        return 2
    if args.host:
        rows = [r for r in rows if r.get("host") == args.host]
    if not rows:
        print(f"no requests in the last {args.hours:g}h")
        return 0

    live = [r for r in rows if not r.get("cached")]
    cached = [r for r in rows if r.get("cached")]
    print(f"\n{len(rows):,} logged in the last {args.hours:g}h "
          f"({len(live):,} sent, {len(cached):,} served from cache, "
          f"{100 * len(cached) / len(rows):.0f}% hit rate)")

    print("\nper host (sent / cached / refused)")
    by_host = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows:
        cell = by_host[r.get("host", "?")]
        if r.get("cached"):
            cell[1] += 1
        else:
            cell[0] += 1
            if r.get("status") in (401, 403, 429):
                cell[2] += 1
    for host, (sent, hit, refused) in sorted(by_host.items(), key=lambda kv: -kv[1][0]):
        flag = "   <-- refusals" if refused else ""
        print(f"  {host:<34} {sent:>6,} {hit:>7,} {refused:>6,}{flag}")

    print("\nper process (requests actually sent)")
    by_proc = collections.Counter(r.get("proc", "?") for r in live)
    for proc, n in by_proc.most_common(12):
        print(f"  {proc:<34} {n:>6,}")

    print("\nsent per hour, per host")
    per_hour = collections.defaultdict(collections.Counter)
    for r in live:
        per_hour[r.get("ts", "")[:13]][r.get("host", "?")] += 1
    for hour in sorted(per_hour)[-12:]:
        cells = ", ".join(f"{h.split('.')[0]}={n}" for h, n in per_hour[hour].most_common(4))
        print(f"  {hour}  {sum(per_hour[hour].values()):>5,}  {cells}")

    # THE QUESTION. How many requests went to a host in the hour before it
    # refused us? A count that clusters is a count wall; one that does not is
    # evidence the wall is something else.
    refusals = [r for r in live if r.get("status") in (401, 403, 429)]
    print(f"\nrefusals: {len(refusals)}")
    if refusals:
        print("  requests sent to that host in the 60 minutes before each refusal:")
        for r in refusals[:15]:
            host, ts = r.get("host"), r.get("ts", "")
            import datetime as dt
            try:
                at = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
            window = (at - dt.timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%S")
            n = sum(1 for x in live if x.get("host") == host and window <= x.get("ts", "") < ts)
            print(f"    {ts}  {host:<30} {n:>5,} in the prior hour  ({r.get('proc')})")
        print("\n  A count wall shows up as these numbers clustering near one value.")
        print("  Scattered numbers mean the refusal is not about how many we sent.")
    else:
        print("  none. No evidence either way yet; leave it running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
