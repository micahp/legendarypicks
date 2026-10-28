"""Audit the cross-source MLS identity pairs against independent evidence: each publisher's date of birth.

Usage: python identity_audit_mls.py FIXTURE_JSON COPY_DB OUT_DIR

For every current person who has both a FotMob key and an MLS Soccer key (the pairs the snapshot links):
- FotMob date of birth: the player-data record that FotMob publishes for the FotMob key.
- MLS date of birth: the player page that MLS publishes for the MLS key. The page prints the date and the
  age. The age is checked against the date, so a day and month swap cannot pass silently.

Verdicts, per pair:
- verified: both dates are present and equal.
- contradicted: both dates are present and differ.
- unverified: a date is missing from one or both publishers.

Name agreement is reported next to the verdict. It is not evidence of identity on its own.

Read-only. Network use is limited to the two publishers' public pages, paced by the existing fetch helpers.
Writes only to OUT_DIR.
"""
import collections
import datetime
import json
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ingest_published_rosters as ipr  # noqa: E402
from ingest_fotmob_soccer_logs import _get as fotmob_get  # noqa: E402

AS_OF = datetime.date(2026, 10, 27)
RETRY_WAITS = (5, 20, 60)  # seconds between attempts on a transient network failure


def _retry(fetch, *args):
    """Call fetch, retrying transient network failures. Raises the last error when every attempt fails."""
    last = None
    for attempt, wait in enumerate((0,) + RETRY_WAITS):
        if wait:
            time.sleep(wait)
        try:
            return fetch(*args)
        except (OSError, ValueError) as exc:  # URLError is an OSError; ValueError covers bad JSON
            last = exc
    raise last


def age_on(born, on=AS_OF):
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def mls_key_to_slug():
    """optaId -> playerSlug, from every club roster MLS publishes."""
    mapping = {}
    for club in ipr._mls_club_slugs():
        page = ipr._MLS_FETCH.text(ipr._MLS_SITE + "/clubs/%s/roster/" % club)
        for payload in ipr._widgets(page):
            _collect(payload, mapping)
    return mapping


def _collect(node, mapping):
    if isinstance(node, dict):
        if "optaId" in node and "playerSlug" in node:
            mapping[str(node["optaId"])] = node["playerSlug"]
        for value in node.values():
            _collect(value, mapping)
    elif isinstance(node, list):
        for value in node:
            _collect(value, mapping)


def mls_page(slug):
    """The printed birth date and shown age from an MLS player page, as the printed numbers."""
    text = re.sub(r"<[^>]+>", " | ", ipr._MLS_FETCH.text(ipr._MLS_SITE + "/players/%s/" % slug))
    match = re.search(r"Date of Birth[^0-9]{0,40}(\d{1,2})\.(\d{1,2})\.(\d{4})\s*\((\d+)\)", text)
    if not match:
        return None
    return {"printed": match.group(0)[-40:], "first": int(match.group(1)), "second": int(match.group(2)),
            "year": int(match.group(3)), "shown_age": int(match.group(4))}


def readings(page):
    """Every calendar date the printed numbers can mean that is consistent with the shown age.

    MLS prints the day and month with the same separator, so both orders can be valid dates. Both are kept
    unless the shown age picks one. The page never says which order it uses.
    """
    out = []
    for label, month, day in (("month.day", page["first"], page["second"]),
                               ("day.month", page["second"], page["first"])):
        try:
            born = datetime.date(page["year"], month, day)
        except ValueError:
            continue
        if age_on(born) == page["shown_age"]:
            out.append((label, born))
    return out


def fotmob_dob(player_id):
    body = fotmob_get("https://www.fotmob.com/api/data/playerData?id=%s" % player_id)
    if isinstance(body.get("body"), dict):
        body = body["body"]
    raw = (body.get("birthDate") or {}).get("utcTime")
    if not raw:
        return None, "no birthDate in FotMob playerData"
    return datetime.date.fromisoformat(raw[:10]), "FotMob birthDate"


def pairs_from(fixture_path, copy_db):
    fx = json.load(open(fixture_path))
    con = sqlite3.connect("file:%s?mode=ro" % copy_db, uri=True)
    names = {}
    for source in ("fotmob", "mlssoccer"):
        for member in fx["squads"][source]:
            names[(source, str(member["source_player_key"]))] = member
    binds = {}
    for source, key, player_id in con.execute(
            "SELECT source, source_player_key, player_id FROM player_source_ids WHERE league IN ('mls','lcup')"):
        binds[(source, str(key))] = player_id
    by_person = {}
    for (source, key), member in names.items():
        pid = binds.get((source, key))
        if pid is None:
            continue
        by_person.setdefault(pid, {})[source] = (key, member)
    pairs = []
    for pid, sources in sorted(by_person.items()):
        if "fotmob" in sources and "mlssoccer" in sources:
            pairs.append((pid, sources["fotmob"], sources["mlssoccer"]))
    return pairs


def main(fixture_path, copy_db, out_dir, reuse_fotmob_from=None):
    os.makedirs(out_dir, exist_ok=True)
    pairs = pairs_from(fixture_path, copy_db)
    print("cross-source pairs:", len(pairs), flush=True)
    slugs = {}
    for attempt in range(len(RETRY_WAITS) + 1):
        slugs = mls_key_to_slug()
        if len(slugs) >= 800:  # 965 on 2026-10-27; a short map means the club index failed, so try again
            break
        time.sleep(RETRY_WAITS[min(attempt, len(RETRY_WAITS) - 1)])
    if len(slugs) < 800:
        raise SystemExit("MLS slug map incomplete (%d); not running the audit on a partial map" % len(slugs))
    print("MLS slugs mapped:", len(slugs), flush=True)

    results_path = os.path.join(out_dir, "pairs.jsonl")
    reused = {}
    if reuse_fotmob_from and os.path.exists(reuse_fotmob_from):
        # FotMob dates were fetched in an earlier run and do not depend on the MLS parser, so reuse them.
        for line in open(reuse_fotmob_from):
            row = json.loads(line)
            reused[row["player_id"]] = row
    done = {}
    if os.path.exists(results_path):
        for line in open(results_path):
            row = json.loads(line)
            done[row["player_id"]] = row
    rows = list(done.values())
    with open(results_path, "a") as sink:
        for index, (pid, (fkey, fmember), (mkey, mmember)) in enumerate(pairs, 1):
            if pid in done:
                continue
            f_dob, f_note = None, None
            if pid in reused and reused[pid]["fotmob_dob"]:
                f_dob = datetime.date.fromisoformat(reused[pid]["fotmob_dob"])
                f_note = reused[pid]["fotmob_note"]
            else:
                try:
                    f_dob, f_note = _retry(fotmob_dob, fkey)
                except Exception as exc:  # noqa: BLE001 - a failed fetch is recorded, never silently dropped
                    f_note = "fetch failed after retries: %s" % exc
            slug = slugs.get(mkey)
            page, mls_candidates, m_note = None, [], "no MLS player page for this key"
            if slug is not None:
                try:
                    page = _retry(mls_page, slug)
                    if page is None:
                        m_note = "no date of birth on the MLS page"
                    else:
                        mls_candidates = readings(page)
                        m_note = "printed %s, shown age %d" % (page["printed"][:28], page["shown_age"])
                except Exception as exc:  # noqa: BLE001
                    m_note = "fetch failed after retries: %s" % exc
            if not f_dob or page is None:
                verdict = "unverified"
            elif not mls_candidates:
                verdict = "mls_age_inconsistent"  # neither reading fits the shown age: a publisher data problem
            elif len(mls_candidates) == 1:
                verdict = "verified" if mls_candidates[0][1] == f_dob else "contradicted"  # the age decided it
            elif any(born == f_dob for _, born in mls_candidates):
                verdict = "ambiguous_matches_one_reading"  # both readings fit the age; one matches FotMob
            else:
                verdict = "contradicted"
            name_equal = (fmember.get("name") or "").strip().lower() == (mmember.get("name") or "").strip().lower()
            row = {"player_id": pid, "fotmob_key": fkey, "mlssoccer_key": mkey,
                   "club": fmember.get("team"), "name_fotmob": fmember.get("name"),
                   "name_mlssoccer": mmember.get("name"), "name_exact_match": name_equal,
                   "fotmob_dob": f_dob.isoformat() if f_dob else None, "fotmob_note": f_note,
                   "mls_printed": page["printed"] if page else None,
                   "mls_readings": [[label, born.isoformat()] for label, born in mls_candidates],
                   "mls_note": m_note, "verdict": verdict}
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
            rows.append(row)
            if index % 50 == 0:
                print("  %d / %d" % (index, len(pairs)), flush=True)

    verdicts = collections.Counter(r["verdict"] for r in rows)
    summary = {"pairs": len(rows), "by_verdict": dict(verdicts),
               "verified": verdicts["verified"], "contradicted": verdicts["contradicted"],
               "ambiguous_matches_one_reading": verdicts["ambiguous_matches_one_reading"],
               "mls_age_inconsistent": verdicts["mls_age_inconsistent"],
               "unverified": verdicts["unverified"],
               "name_exact_match": sum(1 for r in rows if r["name_exact_match"]),
               "as_of": AS_OF.isoformat()}
    with open(os.path.join(out_dir, "audit.json"), "w") as fh:
        json.dump({"summary": summary, "pairs": rows}, fh, ensure_ascii=False, indent=1)
    print(json.dumps(summary, indent=1), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
