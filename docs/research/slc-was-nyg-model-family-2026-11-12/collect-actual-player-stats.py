#!/usr/bin/env python3
"""Extract player stat actuals from the saved CBS final box score HTML."""
import argparse
import json
from pathlib import Path

from bs4 import BeautifulSoup

parser = argparse.ArgumentParser()
parser.add_argument("html", type=Path)
parser.add_argument("out", type=Path)
args = parser.parse_args()
soup = BeautifulSoup(args.html.read_text(), "html.parser")
players = {}
for cell in soup.find_all("td", class_="hover-element"):
    espn_id = cell.get("data-player-id")
    name_el = cell.find(class_="player-name-num-pos")
    if not espn_id or not name_el:
        continue
    player = players.setdefault(espn_id, {
        "team": cell.get("data-team-abbr"), "name": name_el.get_text(" ", strip=True),
        "passing": {}, "rushing": {}, "receiving": {},
    })
    for table in cell.select(".hover-stats-tables table.ingame"):
        headers = [el.get_text(" ", strip=True) for el in table.select("tr.header td")]
        values = [el.get_text(" ", strip=True) for el in table.select("tr.data td")]
        category = "passing" if "COMP%" in headers else "receiving" if "TAR" in headers and "REC" in headers else "rushing" if "ATT" in headers else None
        if category is None:
            continue
        for header, value in zip(headers, values):
            if header and value and header not in ("IN-GAME", "SEASON"):
                player[category][header.lower()] = value
# The compact CBS hover card omits quarterback completions/attempts. Its
# detailed passing table has the C/ATT value in the first player-stat cell.
for row in soup.select("table.stats-table tr.no-hover.data-row"):
    cell = row.find("td", class_="hover-element")
    if cell is None or not cell.get("data-player-id"):
        continue
    values = [el.get_text(" ", strip=True) for el in row.select("td.number-element")]
    if not values or "/" not in values[0]:
        continue
    try:
        completions, attempts = (int(part) for part in values[0].split("/", 1))
    except ValueError:
        continue
    player = players.get(cell["data-player-id"])
    if player is not None:
        player["passing"]["comp"] = str(completions)
        player["passing"]["att"] = str(attempts)
args.out.write_text(json.dumps(players, indent=2, sort_keys=True) + "\n")
print(f"wrote {len(players)} player records")
