"""Capture NFL's published 1996 league standings and reconcile points for/against."""
import argparse
import datetime
import hashlib
import json
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.rows = []
        self.tables = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.rows = []
        elif self.depth == 1 and tag == "tr":
            self.row = []
        elif self.depth == 1 and self.row is not None and tag in ("td", "th"):
            self.cell = []

    def handle_data(self, value):
        if self.cell is not None:
            self.cell.append(value.strip())

    def handle_endtag(self, tag):
        if self.depth == 1 and tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join(x for x in self.cell if x))
            self.cell = None
        elif self.depth == 1 and tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.tables.append(self.rows)


parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
url = "https://www.nfl.com/standings/league/1996/reg"
request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(request, timeout=30) as response:
    data = response.read()
parsed = Tables()
parsed.feed(data.decode("utf-8"))
tables = [table for table in parsed.tables if len(table) == 31 and "PF" in table[0] and "PA" in table[0]]
if len(tables) != 1 or any(len(row) != len(tables[0][0]) for row in tables[0]):
    raise SystemExit("Unexpected standings table shape; no output written")
table = tables[0]
pf, pa = table[0].index("PF"), table[0].index("PA")
if len({row[0] for row in table[1:]}) != 30:
    raise SystemExit("Duplicate team rows; no output written")
points_for = sum(int(row[pf]) for row in table[1:])
points_against = sum(int(row[pa]) for row in table[1:])
if points_for != points_against:
    raise SystemExit(f"League points do not reconcile: {points_for} vs {points_against}")
result = {"url": url, "retrieved_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "sha256_html": hashlib.sha256(data).hexdigest(), "headers": table[0],
          "rows": table[1:], "league_points_for": points_for, "league_points_against": points_against}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(f"Captured 30 teams; points for/against both {points_for}")
