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


def mls_dob(slug):
    """(date, shown_age, note) from the MLS player page, or (None, None, reason)."""
    text = re.sub(r"<[^>]+>", " | ", ipr._MLS_FETCH.text(ipr._MLS_SITE + "/players/%s/" % slug))
    match = re.search(r"Date of Birth[^0-9]{0,40}(\d{1,2})\.(\d{1,2})\.(\d{4})\s*\((\d+)\)", text)
    if not match:
        return None, None, "no date of birth on the page"
    a, b, year, shown = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
    # MLS prints month.day.year. The shown age decides it, so a swapped day and month cannot pass.
    for month, day in ((b, a), (a, b)):
        try:
            born = datetime.date(year, month, day)
        except ValueError:
            continue
        if age_on(born) == shown:
            reading = "printed month.day.year (US)" if (month, day) == (a, b) else "printed day.month.year"
            return born, shown, reading + ", consistent with the shown age"
    return None, shown, "printed date does not match the shown age"


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


def main(fixture_path, copy_db, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    pairs = pairs_from(fixture_path, copy_db)
    print("cross-source pairs:", len(pairs), flush=True)
    slugs = mls_key_to_slug()
    print("MLS slugs mapped:", len(slugs), flush=True)

    rows = []
    for index, (pid, (fkey, fmember), (mkey, mmember)) in enumerate(pairs, 1):
        f_dob, f_note = fotmob_dob(fkey)
        slug = slugs.get(mkey)
        if slug is None:
            m_dob, m_age, m_note = None, None, "no MLS player page for this key"
        else:
            m_dob, m_age, m_note = mls_dob(slug)
        if f_dob and m_dob:
            verdict = "verified" if f_dob == m_dob else "contradicted"
        else:
            verdict = "unverified"
        name_equal = (fmember.get("name") or "").strip().lower() == (mmember.get("name") or "").strip().lower()
        rows.append({"player_id": pid, "fotmob_key": fkey, "mlssoccer_key": mkey,
                     "club": fmember.get("team"), "name_fotmob": fmember.get("name"),
                     "name_mlssoccer": mmember.get("name"), "name_exact_match": name_equal,
                     "fotmob_dob": f_dob.isoformat() if f_dob else None, "fotmob_note": f_note,
                     "mls_dob": m_dob.isoformat() if m_dob else None, "mls_note": m_note,
                     "verdict": verdict})
        if index % 50 == 0:
            print("  %d / %d" % (index, len(pairs)), flush=True)
            with open(os.path.join(out_dir, "progress.json"), "w") as fh:
                json.dump({"done": index, "of": len(pairs)}, fh)

    summary = {"pairs": len(rows),
               "verified": sum(1 for r in rows if r["verdict"] == "verified"),
               "contradicted": sum(1 for r in rows if r["verdict"] == "contradicted"),
               "unverified": sum(1 for r in rows if r["verdict"] == "unverified"),
               "name_exact_match": sum(1 for r in rows if r["name_exact_match"]),
               "as_of": AS_OF.isoformat()}
    with open(os.path.join(out_dir, "audit.json"), "w") as fh:
        json.dump({"summary": summary, "pairs": rows}, fh, ensure_ascii=False, indent=1)
    print(json.dumps(summary, indent=1), flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
