#!/usr/bin/env python3
"""audit_labels.py -- scheme audit of narrative gold labels, applied identically to dev and test.

Rule (fixed before the audit ran; it does not depend on the extractor): a narrative label of OUT, DOUBTFUL or
QUESTIONABLE stands only when the article body (JSON-LD articleBody) contains a sentence that names the player and
states a designation word. If it does not, the designation was read from related content, a teaser or a page
sidebar, and the labelling scheme says those mean NONE.

Writes gold/label_audit.csv (every revision, with the old label) and rewrites gold/labels.csv with the new labels.
Run once. Re-running is a no-op because revised labels no longer carry a designation.
"""
import csv
import hashlib
import os
import re
import sys

import extract_status as ex

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, "gold")
CACHE = "/tmp/lp-inj-resolve-cache"
DESIGNATION = re.compile(r"\b(out|doubtful|questionable|ruled out)\b", re.I)
FLAGGED = ("OUT", "DOUBTFUL", "QUESTIONABLE")


def page(url):
    return open(os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".html"), encoding="utf-8",
                errors="replace").read()


def body_designates(body, player):
    return any(ex.name_in(s, player) and DESIGNATION.search(s) for s in ex.body_sentences(body or ""))


def main(argv=None):
    items = {r["item_id"]: r for r in csv.DictReader(open(os.path.join(GOLD, "sample.csv")))}
    labels = list(csv.DictReader(open(os.path.join(GOLD, "labels.csv"))))
    fields = list(labels[0].keys())
    audit = []
    for lb in labels:
        it = items[lb["item_id"]]
        if it["stratum"] != "narrative" or lb["gold_label"] not in FLAGGED:
            continue
        body, _ = ex.article(page(it["article_url"]))
        if body_designates(body, it["player"]):
            continue
        audit.append(dict(item_id=lb["item_id"], split=lb["split"], player=it["player"], old=lb["gold_label"],
                          new="NONE", reason="designation sentence not in article body (related or teaser content)"))
        lb["gold_label"] = "NONE"
        lb["note"] = (lb["note"] + "; " if lb["note"] else "") + "scheme audit: designation not in body, NONE"
    with open(os.path.join(GOLD, "labels.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(labels)
    with open(os.path.join(GOLD, "label_audit.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["item_id", "split", "player", "old", "new", "reason"])
        w.writeheader()
        w.writerows(audit)
    for split in ("dev", "test"):
        n = sum(1 for a in audit if a["split"] == split)
        print("%s: %d narrative labels revised to NONE" % (split, n))
    for a in audit:
        print("  %s %s %-22s %s -> %s" % (a["item_id"], a["split"], a["player"], a["old"], a["new"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
