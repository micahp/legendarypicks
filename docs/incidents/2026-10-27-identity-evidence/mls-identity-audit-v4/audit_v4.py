"""Audit v4: classify the 815 cross-source pairs from the stored v2 evidence, without refetching.

Layer 1, date of birth, for every pair:
  - the MLS page's printed date and shown age, read with a one-day tolerance (the page's age is computed on
    the day it was rendered, which can be the day after the audit date);
  - each reading that fits the shown age, compared with FotMob's date.

Layer 2, identity status, which is separate from roster membership:
  - supported: the dates agree under a reading the age fixes, or under one of two readings the age cannot
    separate. This is independent evidence, not a consequence of the keys resolving.
  - biographical_disagreement: the dates differ. The link is kept. The disagreement needs an external record.
  - mls_date_missing: the MLS page publishes no birth date.
  - mls_publication_error: the MLS page's printed date does not fit its own shown age.

Layer 3, external review (manual, see REVIEW): official club, league, or reference records, with the reason.

Usage: python audit_v4.py V2_PAIRS_JSONL OUT_DIR
"""
import collections
import datetime
import json
import os
import re
import sys

AS_OF = datetime.date(2026, 10, 27)
TOLERANCE_DAYS = (0, 1)  # the page's age may be computed on the audit day or the day after

PRINTED = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*\((\d+)\)")

REVIEW = {
    33067: {"external": "Wikipedia gives 30 Aug 2001; Sporting KC signing summary and ESPN give 29 Aug 2001 (per search summary).",
            "sources": ["https://en.wikipedia.org/wiki/Jayden_Reid_(American_soccer)",
                        "https://www.sportingkc.com/news/sporting-kc-signs-defenders-wyatt-meyer-and-jayden-reid-as-free-agents"],
            "conclusion": "biographical: one-day disagreement between sources. Official club and MLS agree on 29 Aug; FotMob and Wikipedia say 30 Aug. Link kept."},
    52100: {"external": "Most sources, including the club bio, give 7 Jan 2004; FotMob gives 4 Jan 2004 in one profile.",
            "sources": ["https://en.wikipedia.org/wiki/Cody_Baker"],
            "conclusion": "biographical: FotMob is the outlier. Link kept."},
    58334: {"external": "Wikipedia and the Atlanta United player page give 3 Dec 2002 (MLS prints 12.3.2002, age 23). FotMob and SportsDunia give 13 Dec 2002.",
            "sources": ["https://en.wikipedia.org/wiki/Will_Reilly", "https://www.atlutd.com/players/will-reilly",
                        "https://www.mlssoccer.com/players/will-reilly"],
            "conclusion": "biographical: FotMob is the outlier. Identity supported by name, club, and homegrown history. Link kept."},
    58376: {"external": "Chicago Fire's signing release, ESPN, and Soccerway give 25 Aug 1995; FotMob gives 24 Aug.",
            "sources": ["https://chicagofirefc.com/news/chicago-fire-fc-acquires-defender-jack-elliott"],
            "conclusion": "biographical: FotMob is one day off the club record. Link kept."},
    58549: {"external": "FC Dallas's 24 Sep 2024 announcement and FotMob and Opta give 16 Sep 2006. The MLS profile gives 1998. Reviewer-supplied; not independently opened by this audit.",
            "sources": ["https://www.fcdallas.com/northtexassc/news/fc-dallas-academy-product-daniel-baran-signs-first-professional-contract-with-north-texas-sc",
                        "https://www.mlssoccer.com/players/daniel-baran/"],
            "conclusion": "source error on the MLS profile. Identity supported by the FC Dallas academy path. Link kept; the MLS profile should be reported."},
    58598: {"external": "Wikipedia, ESPN's bio, and the Houston Dynamo bio give 28 Aug 2010. MLS prints 29 Aug (age 16).",
            "sources": ["https://en.wikipedia.org/wiki/Matthew_Arana", "https://www.mlssoccer.com/players/matthew-arana/"],
            "conclusion": "source error on the MLS page; FotMob is correct. Link kept."},
    58670: {"external": "Wikipedia gives 27 Apr 2001. FotMob agrees. MLS prints 4.7.2001, which fits neither 7 Apr nor 4 Jul.",
            "sources": ["https://en.wikipedia.org/wiki/Gonzalo_Luj%C3%A1n"],
            "conclusion": "source error on the MLS page; FotMob is correct. Link kept."},
    58767: {"external": "ESPN, FotMob, LiveSoccerTV, and Soccerway give 18 Jul 2000. Wikipedia gives 20 Jul. The club media guide gives 8 Jul.",
            "sources": ["https://www.revolutionsoccer.net/news/revolution-acquire-nigerian-central-midfielder-alhassan-yusuf-from-royal-antwerp-fc",
                        "https://en.wikipedia.org/wiki/Alhassan_Yusuf"],
            "conclusion": "biographical: publishers split across three dates. Identity supported (Nigerian midfielder, Antwerp to New England). Link kept, date unresolved."},
    58909: {"external": "Timbers' player record gives 16 Jul 2002, and MLS prints 16 Jul. Soccerway and Gradient Sports give 26 Jul. Our FotMob API read is 26 Jul. A search summary also claimed FotMob shows 16 Jul; that conflicts with our API read and is not verified.",
            "sources": ["https://www.timbers.com/news/timbers-sign-defender-ian-smith", "https://www.timbers.com/players/ian-smith/"],
            "conclusion": "biographical: the club and MLS agree on 16 Jul; FotMob's API read is the outlier. Link kept. The FotMob value needs a direct check."},
    58965: {"external": "Several profiles, including ESPN's bio, give 15 May 2003; MLS prints 15 May. FotMob gives 13 May.",
            "sources": ["https://africa.espn.com/football/player/bio/_/id/380677/kieran-sargeant",
                        "https://www.mlssoccer.com/news/san-diego-fc-acquire-kieran-sargeant-from-houston-dynamo"],
            "conclusion": "biographical: FotMob is two days off. Link kept."},
    58996: {"external": "Wikipedia and the club's roster profile give 25 May 1994. FotMob and Soccerway give 24 May.",
            "sources": ["https://en.wikipedia.org/wiki/Stefan_Cleveland",
                        "https://www.sportingkc.com/news/sporting-kc-acquires-goalkeeper-stefan-cleveland-in-trade-with-austin-fc"],
            "conclusion": "biographical: FotMob is one day off the club record. Link kept."},
    59000: {"external": "Sporting KC's roster vitals and most other listings give 24 May 2001. FotMob agrees. MLS prints 4.24.2001, which is 24 Apr.",
            "sources": ["https://www.sportingkc.com/news/sporting-kc-acquires-defender-moises-mosquera-in-transfer-from-fc-juarez",
                        "https://www.mlssoccer.com/players/moises-mosquera/"],
            "conclusion": "source error on the MLS page (month wrong); FotMob agrees with the club. Link kept."},
    59005: {"external": "Wikipedia and MLS give 12 Nov 2001. ESPN and FotMob give 1 Nov 2001. Soccerway and Twente list 11 Jan 2001. Three dates across sources.",
            "sources": ["https://en.wikipedia.org/wiki/Wyatt_Meyer",
                        "https://www.sportingkc.com/news/sporting-kc-signs-defenders-wyatt-meyer-and-jayden-reid-as-free-agents"],
            "conclusion": "biographical: unresolved across three dates. Identity supported by name, club, and the 2024 SuperDraft record. Link kept; date needs a club record."},
    71232: {"external": "MLS's player page gives 17 Feb 2003 (Apex, NC). FotMob gives 16 Feb.",
            "sources": ["https://www.mlssoccer.com/players/matthew-edwards/",
                        "https://www.atlutd.com/2/news/atlanta-united-2-signs-defender-matthew-edwards"],
            "conclusion": "biographical: FotMob is one day off. Link kept."},
    71285: {"external": "ESPN athlete 376512 and the MLS player page both give 12 Mar 2007 (MLS age 19). FotMob gives 3 Dec 2007, which is the day-month swap.",
            "sources": ["https://www.mlssoccer.com/players/zackory-campagnolo/"],
            "conclusion": "FotMob error: day and month swapped. Same person (St. Louis City, goalkeeper, USA). Merge stands."},
    58788: {"external": "Wikipedia and ESPN give 28 Oct 1999 (Caseyville, IL). FotMob agrees. MLS prints 28 Oct 1999 with an age computed on 28 Oct.",
            "sources": ["https://en.wikipedia.org/wiki/Jack_Maher_(soccer)"],
            "conclusion": "verified: the date agrees. The MLS age was a day ahead of the audit date. Link kept."},
    71290: {"external": "Not searched. MLS and FotMob both print 28 Oct 2006, and MLS's age is consistent with 28 Oct.",
            "sources": [],
            "conclusion": "verified by two publishers: the date agrees. No external record checked. Link kept."},
    58489: {"external": "Colorado Rapids' bio and Wikipedia give 2 Apr 1995. FotMob agrees. MLS publishes no birth date.",
            "sources": ["https://en.wikipedia.org/wiki/Zack_Steffen"],
            "conclusion": "identity supported by club record and FotMob; MLS has no date. Link kept."},
    58495: {"external": "The Colorado Rapids release, Wikipedia, and FotMob give 11 Jun 1998. MLS publishes no birth date.",
            "sources": ["https://www.coloradorapids.com/news/colorado-rapids-sign-defender-reggie-cannon",
                        "https://en.wikipedia.org/wiki/Reggie_Cannon"],
            "conclusion": "identity supported by club record and FotMob; MLS has no date. Link kept."},
    58508: {"external": "Wikipedia and the Rapids player profile give 13 Jun 2004. FotMob agrees. MLS publishes no birth date. The Rapids list him as a midfielder.",
            "sources": ["https://en.wikipedia.org/wiki/Wayne_Frederick_(footballer)"],
            "conclusion": "identity supported by club record and FotMob; MLS has no date. Link kept. Position differs between sources."},
    59030: {"external": "Wikipedia and the Toronto FC release give 19 May 1993 (Lawrenceville, GA). FotMob agrees. MLS publishes no birth date.",
            "sources": ["https://en.wikipedia.org/wiki/Walker_Zimmerman",
                        "https://www.torontofc.ca/news/toronto-fc-acquire-u-s-international-defender-walker-zimmerman"],
            "conclusion": "identity supported by club record and FotMob; MLS has no date. Link kept."},
}


def readings(first, second, year, shown):
    out = []
    for label, month, day in (("month.day", first, second), ("day.month", second, first)):
        try:
            born = datetime.date(year, month, day)
        except ValueError:
            continue
        if any(age_on(born, AS_OF + datetime.timedelta(days=d)) == shown for d in TOLERANCE_DAYS):
            out.append((label, born))
    return out


def age_on(born, on):
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def classify(row):
    fotmob = datetime.date.fromisoformat(row["fotmob_dob"]) if row["fotmob_dob"] else None
    printed = PRINTED.search(row.get("mls_printed") or "")
    if fotmob is None:
        return "no_fotmob_date", "insufficient", []
    if not printed:
        return "mls_date_missing", "mls_date_missing", []
    first, second, year, shown = (int(x) for x in printed.groups())
    candidates = readings(first, second, year, shown)
    if not candidates:
        return "mls_publication_error", "mls_publication_error", []
    if len(candidates) == 1:
        if candidates[0][1] == fotmob:
            return "verified_dob", "supported", candidates
        return "dob_disagreement", "biographical_disagreement", candidates
    if any(born == fotmob for _, born in candidates):
        return "ambiguous_dob_match", "supported_order_unresolved", candidates
    return "dob_disagreement", "biographical_disagreement", candidates


def main(v2_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rows = [json.loads(line) for line in open(v2_path)]
    out, changes = [], []
    for row in rows:
        dob_status, identity, candidates = classify(row)
        entry = {"player_id": row["player_id"], "club": row["club"], "name_fotmob": row["name_fotmob"],
                 "name_mlssoccer": row["name_mlssoccer"], "fotmob_key": row["fotmob_key"],
                 "mlssoccer_key": row["mlssoccer_key"], "fotmob_dob": row["fotmob_dob"],
                 "mls_printed": " ".join((row.get("mls_printed") or "").split())[-30:],
                 "mls_readings_v4": [[label, born.isoformat()] for label, born in candidates],
                 "dob_status": dob_status, "identity_status": identity,
                 "audit_v2_verdict": row["verdict"]}
        if row["player_id"] in REVIEW:
            entry["external_review"] = REVIEW[row["player_id"]]
        if identity == "biographical_disagreement" and "external_review" in entry:
            entry["final_status"] = "biographical_source_error" if "source error" in entry["external_review"]["conclusion"] or "error" in entry["external_review"]["conclusion"] else "biographical_disagreement"
        elif identity == "supported" or identity == "supported_order_unresolved":
            entry["final_status"] = identity
        else:
            entry["final_status"] = identity
        v2 = row["verdict"]
        if (v2 == "contradicted" and dob_status == "verified_dob") or \
           (v2 == "mls_age_inconsistent" and dob_status == "verified_dob") or \
           (v2 == "verified" and dob_status != "verified_dob"):
            changes.append({"player_id": row["player_id"], "v2": v2, "v4": dob_status,
                            "name": row["name_fotmob"]})
        out.append(entry)
    with open(os.path.join(out_dir, "pairs_v4.jsonl"), "w") as fh:
        for entry in out:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    summary = {"pairs": len(out),
               "dob_status": dict(collections.Counter(e["dob_status"] for e in out)),
               "identity_status": dict(collections.Counter(e["identity_status"] for e in out)),
               "final_status": dict(collections.Counter(e["final_status"] for e in out)),
               "changed_from_v2": changes}
    with open(os.path.join(out_dir, "summary_v4.json"), "w") as fh:
        json.dump(summary, fh, indent=1, ensure_ascii=False)
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
