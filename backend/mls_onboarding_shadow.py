"""Read-only shadow of MLS onboarding against live publisher responses. Nothing persists.

Usage: python mls_onboarding_shadow.py PROD_DB COPY_DB AUDIT_PAIRS_JSONL REPORT_JSON [--sample-seed N]

1. Fetches today's squads from FotMob and MLS Soccer through the production providers. The production database is
   opened read-only, and only to read the club list those providers use.
2. Evaluates the onboarding decision (mls_identity.onboard) on COPY_DB, which must be a disposable copy, inside a
   transaction that is ALWAYS rolled back. It reports what would be created, rekeyed and queued. Nothing persists.
3. Exercises the live date-of-birth lookups and the corroboration rule on known records: a sample of the 815
   audited cross-source pairs, stratified by the audit's own status. Each live verdict is compared with the audit.

Refuses PROD_DB as the copy. Writes only to REPORT_JSON.
"""
import collections
import datetime as dt
import json
import os
import random
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ingest_published_rosters as ipr  # noqa: E402
import mls_identity  # noqa: E402

SAMPLE_PLAN = {"supported": 20, "supported_order_unresolved": 10, "biographical_disagreement": 15,
               "mls_date_missing": 4}


def live_squads(prod_path):
    """Today's squads, read through the production providers. The production file is opened read-only."""
    con = sqlite3.connect("file:%s?mode=ro" % prod_path, uri=True)
    con.row_factory = sqlite3.Row
    try:
        squads = {"fotmob": ipr._fotmob_squads(con, "mls"), "mlssoccer": ipr._mls_squads(con, "mls")}
    finally:
        con.close()
    return squads


def evaluate_onboarding(copy_path, squads, now):
    """Run the production onboarding decision on a disposable copy, then roll everything back."""
    con = sqlite3.connect(copy_path, timeout=120)
    con.row_factory = sqlite3.Row
    mls_identity.ensure_schema(con)
    con.commit()
    binds_before = con.execute("SELECT COUNT(*) FROM player_source_ids").fetchone()[0]
    players_before = con.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    bound = {(s, str(k)) for s, k in con.execute("SELECT source, source_player_key FROM player_source_ids "
                                                 "WHERE league IN ('mls','lcup')")}
    unbound = [(src, str(m["source_player_key"]), m.get("name"), m.get("team"))
               for src in ("fotmob", "mlssoccer") for m in squads[src]
               if (src, str(m["source_player_key"])) not in bound]
    con.execute("BEGIN IMMEDIATE")
    try:
        outcome = mls_identity.onboard(con, squads, mls_identity.default_lookup, now)
        queued = con.execute("SELECT source, source_player_key, reason FROM identity_onboarding_queue "
                             "WHERE status='open'").fetchall()
        result = {
            "unbound_keys_in_live_squads": len(unbound),
            "unbound_keys": [{"source": s, "source_player_key": k, "name": n, "team": t} for s, k, n, t in unbound],
            "would_create_players": len(outcome["created"]),
            "would_rekey": len(outcome["rekeyed"]),
            "would_queue": [{"source": q["source"], "source_player_key": q["source_player_key"], "reason": q["reason"]}
                            for q in queued],
        }
    finally:
        con.execute("ROLLBACK")
    persisted = {
        "players_before": players_before,
        "players_after": con.execute("SELECT COUNT(*) FROM players").fetchone()[0],
        "binds_before": binds_before,
        "binds_after": con.execute("SELECT COUNT(*) FROM player_source_ids").fetchone()[0],
    }
    con.close()
    result["copy_persisted_after_rollback"] = persisted
    return result


def known_pair_checks(pairs_path, seed):
    """Live lookups for a stratified sample of audited pairs, compared with the audit's own status."""
    rows = [json.loads(line) for line in open(pairs_path)]
    rng = random.Random(seed)
    by_status = collections.defaultdict(list)
    for row in rows:
        by_status[row["final_status"]].append(row)
    chosen = []
    for status, n in (("supported", SAMPLE_PLAN["supported"]),
                      ("supported_order_unresolved", SAMPLE_PLAN["supported_order_unresolved"]),
                      ("biographical_disagreement", SAMPLE_PLAN["biographical_disagreement"]),
                      ("mls_date_missing", SAMPLE_PLAN["mls_date_missing"])):
        pool = sorted(by_status.get(status, []), key=lambda r: r["player_id"])
        chosen.extend(rng.sample(pool, min(n, len(pool))))
    out = []
    for row in chosen:
        fotmob_dates = mls_identity.default_lookup("fotmob", str(row["fotmob_key"]))
        mls_dates = mls_identity.default_lookup("mlssoccer", str(row["mlssoccer_key"]))
        dob, _reason = mls_identity.corroborated_dob(sorted(set(mls_dates)), sorted(set(fotmob_dates)))
        corroborated = dob is not None
        expected = row["final_status"] in ("supported", "supported_order_unresolved")
        out.append({"player_id": row["player_id"], "audit_status": row["final_status"],
                    "live_fotmob_dates": fotmob_dates, "live_mls_dates": mls_dates,
                    "live_corroborated": corroborated, "agrees_with_audit": corroborated == expected})
    return out


def main(argv):
    seed = 20261028
    if "--sample-seed" in argv:
        seed = int(argv[argv.index("--sample-seed") + 1])
    prod_path, copy_path, pairs_path, report_path = argv[1], argv[2], argv[3], argv[4]
    if os.path.abspath(copy_path) == os.path.abspath(prod_path):
        raise SystemExit("refusing: the copy must not be the production database")
    if not os.path.exists(copy_path):
        raise SystemExit("the disposable copy must exist (create it with mls_cutover_copy.py)")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    squads = live_squads(prod_path)
    decision = evaluate_onboarding(copy_path, squads, now)
    checks = known_pair_checks(pairs_path, seed)
    agree = sum(1 for c in checks if c["agrees_with_audit"])
    report = {"captured_at": now, "live_squad_counts": {k: len(v) for k, v in squads.items()},
              "onboarding_decision_on_copy": decision,
              "known_record_checks": {"sample": len(checks), "agree_with_audit": agree,
                                      "disagree": len(checks) - agree,
                                      "by_audit_status": dict(collections.Counter(c["audit_status"] for c in checks))},
              "checks": checks}
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=1, ensure_ascii=False)
    print(json.dumps({k: report[k] for k in ("live_squad_counts", "known_record_checks")}, indent=1))
    print("unbound live keys:", decision["unbound_keys_in_live_squads"],
          "| would create:", decision["would_create_players"], "| copy persisted:", decision["copy_persisted_after_rollback"])


if __name__ == "__main__":
    main(sys.argv)
