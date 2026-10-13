#!/usr/bin/env python3
"""Restore publisher capitalisation to MLB player names stored all-lowercase.

407 of 2,439 MLB players on dev and 106 of 2,449 on prod carry names like
`jeff mcneil`. 231 of them have props on the board, so the props page renders
lowercase names next to correctly-cased ones from every other league.

The name is taken from MLB StatsAPI keyed on the row's own `mlbam_id`, NOT
derived. `"jeff mcneil".title()` is `Jeff Mcneil`, and there is no string rule
that recovers McNeil, O'Neill, de la Cruz and Jr. from a lowercased form -- the
capitalisation is information that was destroyed, and only the publisher still
has it.

FAILS CLOSED on identity: a row is updated only when the API's name matches the
stored one once both are accent-folded and lowercased. A row whose API name is a
DIFFERENT person is reported and skipped, never renamed. Case is the only thing
this changes.

  python3 repair_mlb_name_case.py --db data/picks.dev.db --check
  python3 repair_mlb_name_case.py --db data/picks.dev.db --apply
"""
import argparse
import json
import sqlite3
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone

API = "https://statsapi.mlb.com/api/v1/people"
BATCH = 100


def fold(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join("".join(c for c in text.lower() if c.isalnum() or c.isspace()).split())


def recase(stored, published):
    """The publisher's CASE applied to OUR letters.

    Taking the publisher's string outright strips accents it does not carry:
    the first run turned `jos\u00e9 herrera` into `Jose Herrera`, losing an
    accent on 9 rows across the two databases. Accent marks are information we
    hold and StatsAPI sometimes does not, and this repair is about CASE.

    Returns None when the two differ by more than case and accents, so the
    caller skips rather than inventing a name.
    """
    if len(stored) != len(published):
        return None
    return "".join(c.upper() if published[i].isupper() else c
                   for i, c in enumerate(stored))


def published_names(ids):
    out = {}
    for start in range(0, len(ids), BATCH):
        chunk = ids[start:start + BATCH]
        url = f"{API}?personIds={','.join(str(i) for i in chunk)}&fields=people,id,fullName"
        with urllib.request.urlopen(url, timeout=40) as response:
            payload = json.loads(response.read())
        for person in payload.get("people", []):
            if person.get("id") is not None and person.get("fullName"):
                out[int(person["id"])] = person["fullName"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, name, mlbam_id FROM players"
        " WHERE league='mlb' AND name=LOWER(name) AND name<>''").fetchall()
    print(f"{args.db}")
    print(f"  all-lowercase mlb names: {len(rows)}")
    without = [r for r in rows if r["mlbam_id"] is None]
    if without:
        print(f"  ...of which {len(without)} have NO mlbam_id and cannot be repaired from"
              f" the publisher; they are left alone, not guessed")

    keyed = [r for r in rows if r["mlbam_id"] is not None]
    names = published_names([r["mlbam_id"] for r in keyed]) if keyed else {}
    fixable, mismatched, missing = [], [], []
    for r in keyed:
        published = names.get(int(r["mlbam_id"]))
        if not published:
            missing.append(r); continue
        if fold(published) != fold(r["name"]):
            mismatched.append((r["name"], published)); continue
        corrected = recase(r["name"], published)
        if corrected is None:
            mismatched.append((r["name"], published)); continue
        if corrected != r["name"]:
            fixable.append((r["id"], corrected, r["name"]))

    print(f"  publisher answered for {len(names)} of {len(keyed)}")
    print(f"  case-only repairs available: {len(fixable)}")
    if missing:
        print(f"  publisher had no row for {len(missing)} -- skipped")
    if mismatched:
        print(f"  IDENTITY MISMATCH, skipped (never renamed): {len(mismatched)}")
        for stored, published in mismatched[:5]:
            print(f"     stored={stored!r}  publisher={published!r}")
    for _id, published, stored in fixable[:8]:
        print(f"     {stored!r} -> {published!r}")

    if args.check or not fixable:
        print("  check only -- nothing written" if args.check else "  nothing to do")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = f"{args.db}.pre-name-case-{stamp}.bak"
    con.execute("VACUUM INTO ?", (backup,))
    ok = sqlite3.connect(backup).execute("PRAGMA quick_check").fetchone()[0]
    print(f"  backup: {backup} (quick_check={ok})")
    if ok != "ok":
        raise SystemExit("backup failed quick_check; nothing written")

    con.execute("BEGIN IMMEDIATE")
    con.executemany("UPDATE players SET name=? WHERE id=?",
                    [(published, _id) for _id, published, _ in fixable])
    con.commit()
    left = con.execute(
        "SELECT COUNT(*) FROM players WHERE league='mlb' AND name=LOWER(name) AND name<>''"
    ).fetchone()[0]
    print(f"  repaired {len(fixable)}; still lowercase: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
