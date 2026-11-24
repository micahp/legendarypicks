"""Capture NFL-published 1996 regular-season team tables; fail on incomplete tables."""
import argparse
import datetime
import hashlib
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = self.in_row = self.in_cell = False
        self.tables = []
        self.table = []
        self.row = []
        self.cell = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self.table = []
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.cell = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data.strip())

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.in_cell:
            self.row.append(" ".join(x for x in self.cell if x))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            self.table.append(self.row)
            self.in_row = False
        elif tag == "table" and self.in_table:
            self.tables.append(self.table)
            self.in_table = False


parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
result = {"retrieved_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "tables": {}}
sources = {kind: f"https://www.nfl.com/stats/team-stats/offense/{kind}/1996/reg/all"
           for kind in ("passing", "rushing", "downs", "scoring")}
sources.update({f"special_{kind}": f"https://www.nfl.com/stats/team-stats/special-teams/{kind}/1996/reg/all"
                for kind in ("field-goals", "scoring")})
for kind, url in sources.items():
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    parsed = Tables()
    parsed.feed(data.decode("utf-8"))
    candidates = [table for table in parsed.tables if len(table) == 31]
    if len(candidates) != 1 or any(len(row) != len(candidates[0][0]) for row in candidates[0]):
        raise SystemExit(f"Unexpected {kind} table shape; no output written")
    rows = candidates[0]
    if len({re.sub(r"\s+", " ", row[0]) for row in rows[1:]}) != 30:
        raise SystemExit(f"Duplicate teams in {kind}; no output written")
    result["tables"][kind] = {"url": url, "sha256_html": hashlib.sha256(data).hexdigest(),
                              "headers": rows[0], "rows": rows[1:]}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(f"Captured {len(sources)} 30-team tables in {args.output}")
