#!/usr/bin/env python3
"""evaluate_gold.py -- run extract_status on the gold sample and score it against gold/labels.csv.

  python3 evaluate_gold.py                 dev split (default; used for tuning)
  python3 evaluate_gold.py --split test --final
                                           test split, one shot: writes gold/final-test-results.json and refuses to
                                           run again once that file exists, so the rules cannot be tuned on test

Scoring, for each designation class c in OUT, DOUBTFUL, QUESTIONABLE:
  precision_c = predicted c and gold c / predicted c   (abstentions are not predictions)
  recall_c    = predicted c and gold c / gold c        (an abstention on a gold c is a miss)
Abstention rate = predicted UNKNOWN / items. Intervals are Wilson 95 percent.
Provenance for every item (source URL, span, rule, timestamps from article_evidence.csv) is written to
gold/extractions_<split>.csv.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter

import extract_status as ex

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, "gold")
CLASSES = ("OUT", "DOUBTFUL", "QUESTIONABLE")


def wilson(k, n, z=1.959964):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def pct(x):
    return "n/a" if x != x else "%.1f%%" % (100 * x)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["dev", "test"], default="dev")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--cache-dir", default="/tmp/lp-inj-resolve-cache")
    ap.add_argument("--show", type=int, default=60, help="mismatches to print")
    a = ap.parse_args(argv)

    final_path = os.path.join(GOLD, "final-test-results.json")
    if a.split == "test":
        if not a.final:
            raise SystemExit("test split is evaluated only with --final (one shot, after dev is frozen)")
        if os.path.exists(final_path):
            raise SystemExit("test already evaluated: %s exists; do not re-run" % final_path)

    labels = {r["item_id"]: r for r in csv.DictReader(open(os.path.join(GOLD, "labels.csv")))}
    items = [r for r in csv.DictReader(open(os.path.join(GOLD, "sample.csv"))) if r["split"] == a.split]
    evidence = {(r["game_id"], r["url"]): r for r in csv.DictReader(open(os.path.join(HERE, "article_evidence.csv")))}
    module_hash = hashlib.sha256(open(ex.__file__, "rb").read()).hexdigest()[:16]

    rows, pages = [], {}
    for it in items:
        url = it["article_url"]
        if url not in pages:
            path = os.path.join(a.cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".html")
            pages[url] = open(path, encoding="utf-8", errors="replace").read()
        res = ex.extract(pages[url], it["player"], it["game_id"], it["team"], int(it["week"]), url)
        gold = labels[it["item_id"]]["gold_label"]
        ev = evidence.get((it["game_id"], url), {})
        rows.append(dict(item_id=it["item_id"], split=a.split, stratum=it["stratum"], game_id=it["game_id"],
                         team=it["team"], week=it["week"], gsis_id=it["gsis_id"], player=it["player"],
                         article_url=url, route=res["route"], predicted=res["status"], rule=res["rule"],
                         span=res["span"], gold=gold, correct=int(res["status"] == gold),
                         published_utc=ev.get("published_utc", ""), modified_utc=ev.get("modified_utc", ""),
                         cutoff_utc=ev.get("cutoff_utc", ""), content_state=ev.get("content_state", ""),
                         method="rules-v1:" + module_hash))

    out_csv = os.path.join(GOLD, "extractions_%s.csv" % a.split)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    n = len(rows)
    pred = Counter(r["predicted"] for r in rows)
    gold_n = Counter(r["gold"] for r in rows)
    summary = {"split": a.split, "items": n, "extractor": "rules-v1:" + module_hash,
               "abstain": pred["UNKNOWN"], "abstention_rate": pred["UNKNOWN"] / n, "classes": {}}
    print("split=%s items=%d extractor=rules-v1:%s" % (a.split, n, module_hash))
    print("predicted:", dict(sorted(pred.items())))
    print("gold:     ", dict(sorted(gold_n.items())))
    print("abstention: %d of %d (%s)" % (pred["UNKNOWN"], n, pct(pred["UNKNOWN"] / n)))
    for c in CLASSES:
        tp = sum(1 for r in rows if r["predicted"] == c and r["gold"] == c)
        npred, ngold = pred[c], gold_n[c]
        p_lo, p_hi = wilson(tp, npred)
        r_lo, r_hi = wilson(tp, ngold)
        prec = tp / npred if npred else float("nan")
        rec = tp / ngold if ngold else float("nan")
        print("%-12s precision %s (%d of %d; 95%% CI %s-%s)  recall %s (%d of %d; 95%% CI %s-%s)" % (
            c, pct(prec), tp, npred, pct(p_lo), pct(p_hi), pct(rec), tp, ngold, pct(r_lo), pct(r_hi)))
        summary["classes"][c] = dict(tp=tp, predicted=npred, gold=ngold, precision=prec, recall=rec,
                                     precision_ci=[p_lo, p_hi], recall_ci=[r_lo, r_hi])
    labels_order = ("OUT", "DOUBTFUL", "QUESTIONABLE", "NONE", "OTHER", "UNKNOWN")
    print("confusion (rows gold, cols predicted):")
    print("%-12s" % "" + "".join("%12s" % p for p in labels_order))
    for g in labels_order:
        print("%-12s" % g + "".join("%12d" % sum(1 for r in rows if r["gold"] == g and r["predicted"] == p)
                                     for p in labels_order))
    mism = [r for r in rows if not r["correct"]]
    print("\nmismatches: %d" % len(mism))
    for r in mism[:a.show]:
        print("  %s %-9s gold=%-12s pred=%-12s rule=%-30s %s | %s" % (
            r["item_id"], r["stratum"], r["gold"], r["predicted"], r["rule"], r["player"], r["span"][:150]))
    if a.split == "test":
        with open(final_path, "w") as f:
            json.dump(summary, f, indent=2, default=float)
        print("wrote", final_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
