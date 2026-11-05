#!/usr/bin/env python3
"""make_gold_sample.py -- draw the gold-set sample from pool.csv, split into dev and test before any labelling.

Strata (drawn with a fixed seed, so the sample is reproducible):
  table      player rows of an official status table, drawn from each Game Status class
  narrative  a sentence naming the player also contains a designation word (out, doubtful, questionable, ruled out)
  mention    the player's name appears in prose with no designation word in that sentence (difficult negatives
             are most of these: recap and feature mentions of rostered players)

The dev split is used to write and tune the extractor. The test split is labelled and frozen before the extractor
is run on it. Each item keeps the raw table row or the sentences it was drawn from, so a label can be checked
against the text it was made from.

Usage: python3 make_gold_sample.py [--seed 20260505] [--cache-dir DIR]
Writes gold/sample.csv (item_id, split, stratum, identifiers, route, raw_status, context).
"""
import argparse
import csv
import hashlib
import os
import random
import re
import sys
from collections import defaultdict

import status_text as st
from build_pool import key, name_key

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGNATION = re.compile(r"\b(out|doubtful|questionable|ruled out)\b")
QUOTA = {  # (dev, test) per stratum; the table stratum is allocated across status classes
    "table": (25, 25),
    "narrative": (40, 40),
    "mention": (10, 10),
}
TABLE_CLASS = {"out": "Out", "doubtful": "Doubtful", "questionable": "Questionable", "": "blank", "-": "dash"}


def table_class(raw):
    token = raw.strip().lower().strip("()- ").strip()
    if raw.strip() in {"-", "--", "(-)", "----"} or token == "":
        return "blank" if raw.strip() == "" else "dash"
    if token in ("out", "doubtful", "questionable"):
        return token.capitalize() if token != "out" else "Out"
    return "other"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=20260505)
    ap.add_argument("--cache-dir", default="/tmp/lp-inj-resolve-cache")
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)

    pool = list(csv.DictReader(open(os.path.join(HERE, "pool.csv"))))
    pages, items = {}, defaultdict(list)
    for r in pool:
        url = r["article_url"]
        if url not in pages:
            path = os.path.join(a.cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".html")
            pages[url] = open(path, encoding="utf-8", errors="replace").read()
        page = pages[url]
        name = name_key(r["player"])
        pattern = re.compile(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])")
        rows = st.status_tables(page)[0] if r["has_status_table"] == "1" else []
        table_row = next((row for row in rows if key(st.table_player(row.get("Player", ""))) == name), None)
        sents = [s for s in st.sentences(page) if pattern.search(key(s))]
        base = {"game_id": r["game_id"], "team": r["team"], "week": r["week"], "gsis_id": r["gsis_id"],
                "player": r["player"], "article_url": url}
        if table_row is not None:
            raw = st.status_column(table_row)
            items["table:" + table_class(raw)].append(dict(base, route="table", raw_status=raw,
                                                           context=" | ".join(f"{h}={v}" for h, v in table_row.items())))
        elif any(DESIGNATION.search(key(s)) for s in sents):
            hits = [s for s in sents if DESIGNATION.search(key(s))]
            items["narrative"].append(dict(base, route="narrative", raw_status="", context=" || ".join(hits[:3])))
        elif sents:
            items["mention"].append(dict(base, route="mention", raw_status="", context=" || ".join(sents[:2])))

    out = []
    n = 0
    table_classes = sorted(k for k in items if k.startswith("table:"))
    for stratum_key in table_classes:
        pool_items = sorted(items[stratum_key], key=lambda x: (x["article_url"], x["player"]))
        dev_n = max(1, round(QUOTA["table"][0] * len(pool_items) / sum(len(items[k]) for k in table_classes)))
        test_n = max(1, round(QUOTA["table"][1] * len(pool_items) / sum(len(items[k]) for k in table_classes)))
        for split, count in (("dev", dev_n), ("test", test_n)):
            for it in rng.sample(pool_items, min(count, len(pool_items))):
                pool_items.remove(it)
                out.append((split, "table", it))
    for stratum in ("narrative", "mention"):
        pool_items = sorted(items[stratum], key=lambda x: (x["article_url"], x["player"]))
        for split, count in zip(("dev", "test"), QUOTA[stratum]):
            for it in rng.sample(pool_items, min(count, len(pool_items))):
                pool_items.remove(it)
                out.append((split, stratum, it))

    os.makedirs(os.path.join(HERE, "gold"), exist_ok=True)
    with open(os.path.join(HERE, "gold", "sample.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "split", "stratum", "game_id", "team", "week", "gsis_id", "player", "article_url",
                    "route", "raw_status", "context"])
        for split, stratum, it in out:
            n += 1
            w.writerow(["G%03d" % n, split, stratum, it["game_id"], it["team"], it["week"], it["gsis_id"], it["player"],
                        it["article_url"], it["route"], it["raw_status"], it["context"]])
    counts = defaultdict(int)
    for split, stratum, _ in out:
        counts[(split, stratum)] += 1
    for key_, v in sorted(counts.items()):
        print("%-5s %-10s %d" % (key_[0], key_[1], v))
    print("table classes available:", {k: len(items[k]) for k in table_classes})
    return 0


if __name__ == "__main__":
    sys.exit(main())
