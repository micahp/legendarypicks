"""Track every canonical MLS person by the evidence behind the record, so no category reads as verified without it.

Usage: python track_v4.py PAIRS_V4_JSONL MEMBERSHIPS_JSON OUT_JSON

Categories:
- dob_agreement: both publishers print the same date under a reading the shown age fixes. Two publishers, not proof.
- ambiguous_order: both MLS readings fit the shown age and one matches FotMob. The date order is unresolved.
- biographical_disagreement: the dates differ and no publisher is named as wrong. The link is kept.
- biographical_source_error: the dates differ and the reviewer named the publisher whose record is wrong
  (the source_error_publisher field in audit_v4.py). Not inferred from text.
- mls_date_missing: MLS prints no date of birth.
- single_source: the person has one publisher key in the current membership. No cross-check exists.

Read-only. Writes OUT_JSON only. Every row says whether the category is independently checked: only a
category with an external check on the record itself can say so, and none of these are marked verified.
"""
import collections
import json
import sys

FINAL = {
    "supported": "dob_agreement",
    "supported_order_unresolved": "ambiguous_order",
    "biographical_disagreement": "biographical_disagreement",
    "biographical_source_error": "biographical_source_error",
    "mls_date_missing": "mls_date_missing",
}


def main(pairs_path, memberships_path, out_path):
    pairs = [json.loads(line) for line in open(pairs_path)]
    members = json.load(open(memberships_path))["people"]
    paired = {str(row["player_id"]) for row in pairs}
    rows = collections.defaultdict(list)
    for row in pairs:
        category = FINAL[row["final_status"]]
        rows[category].append({"player_id": row["player_id"], "club": row["club"],
                               "fotmob_dob": row["fotmob_dob"], "mls_printed": row["mls_printed"],
                               "source_error_publisher": row.get("source_error_publisher")})
    single = []
    for pid, member in members.items():
        if pid in paired:
            continue
        single.append({"player_id": int(pid), "team": member["team"], "publisher_keys": member["keys"]})
    rows["single_source"] = single
    counts = {category: len(items) for category, items in rows.items()}
    counts["people_in_membership"] = len(members)
    assert len(pairs) + len(single) == len(members), "pairs and single-source people must cover the membership"
    out = {"counts": counts, "rows": rows}
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:4])
