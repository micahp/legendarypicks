#!/usr/bin/env python3
"""Venue table keyed on each home team's current stadium.

Name, roof type and listed capacity come from the Wikipedia list of NFL stadiums (fetched 2026-10-27). Coordinates come from
OpenStreetMap Nominatim (one request per second, one query per venue). Output: venues.json next to this script.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
import nfl_team_codes  # noqa: E402

UA = 'LegendaryPicksResearch/1.0 (venue lookup for backtests)'
WIKI = 'https://en.wikipedia.org/wiki/List_of_National_Football_League_stadiums'

# home team -> (stadium, city, state, roof, listed capacity)
VENUES = {
    'ARI': ('State Farm Stadium', 'Glendale', 'Arizona', 'Retractable', 63400),
    'ATL': ('Mercedes-Benz Stadium', 'Atlanta', 'Georgia', 'Retractable', 71000),
    'BAL': ('M&T Bank Stadium', 'Baltimore', 'Maryland', 'Open', 71008),
    'BUF': ('Highmark Stadium', 'Orchard Park', 'New York', 'Open', 60108),
    'CAR': ('Bank of America Stadium', 'Charlotte', 'North Carolina', 'Open', 75037),
    'CHI': ('Soldier Field', 'Chicago', 'Illinois', 'Open', 62500),
    'CIN': ('Paycor Stadium', 'Cincinnati', 'Ohio', 'Open', 65515),
    'CLE': ('Huntington Bank Field', 'Cleveland', 'Ohio', 'Open', 67895),
    'DAL': ('AT&T Stadium', 'Arlington', 'Texas', 'Retractable', 80000),
    'DEN': ('Empower Field at Mile High', 'Denver', 'Colorado', 'Open', 76125),
    'DET': ('Ford Field', 'Detroit', 'Michigan', 'Fixed dome', 65000),
    'GB': ('Lambeau Field', 'Green Bay', 'Wisconsin', 'Open', 81441),
    'HOU': ('Reliant Stadium', 'Houston', 'Texas', 'Retractable', 72220),
    'IND': ('Lucas Oil Stadium', 'Indianapolis', 'Indiana', 'Retractable', 67000),
    'JAX': ('EverBank Stadium', 'Jacksonville', 'Florida', 'Open', 69132),
    'KC': ('Arrowhead Stadium', 'Kansas City', 'Missouri', 'Open', 73426),
    'LV': ('Allegiant Stadium', 'Paradise', 'Nevada', 'Fixed dome', 66000),
    'LA': ('SoFi Stadium', 'Inglewood', 'California', 'Fixed dome', 70000),
    'MIA': ('Hard Rock Stadium', 'Miami Gardens', 'Florida', 'Open', 65326),
    'MIN': ('U.S. Bank Stadium', 'Minneapolis', 'Minnesota', 'Fixed dome', 66655),
    'NE': ('Gillette Stadium', 'Foxborough', 'Massachusetts', 'Open', 66829),
    'NO': ('Caesars Superdome', 'New Orleans', 'Louisiana', 'Fixed dome', 73208),
    'NYG': ('MetLife Stadium', 'East Rutherford', 'New Jersey', 'Open', 82500),
    'PHI': ('Lincoln Financial Field', 'Philadelphia', 'Pennsylvania', 'Open', 69596),
    'PIT': ('Acrisure Stadium', 'Pittsburgh', 'Pennsylvania', 'Open', 68984),
    'SEA': ('Lumen Field', 'Seattle', 'Washington', 'Open', 69000),
    'SF': ("Levi's Stadium", 'Santa Clara', 'California', 'Open', 68500),
    'TB': ('Raymond James Stadium', 'Tampa', 'Florida', 'Open', 65890),
    'TEN': ('Nissan Stadium', 'Nashville', 'Tennessee', 'Open', 69143),
    'WAS': ('Northwest Stadium', 'Landover', 'Maryland', 'Open', 64000),
}
# The NY Jets and Giants share MetLife; the Chargers and Rams share SoFi. Both teams point at the same venue row.
SHARED = {'NYJ': 'NYG', 'LAC': 'LA', 'LAR': nfl_team_codes.to_nflverse_team_code('LAR')}


def geocode(name, city, state):
    query = urllib.parse.urlencode({'q': f'{name}, {city}, {state}, USA', 'format': 'json', 'limit': 1})
    req = urllib.request.Request(f'https://nominatim.openstreetmap.org/search?{query}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        hits = json.loads(resp.read())
    time.sleep(1.1)
    if not hits:
        return None
    return {'lat': round(float(hits[0]['lat']), 4), 'lon': round(float(hits[0]['lon']), 4),
            'osm_display_name': hits[0]['display_name'], 'osm_type': hits[0].get('type')}


def main():
    venues = {}
    for team, (name, city, state, roof, capacity) in VENUES.items():
        geo = geocode(name, city, state)
        venues[team] = {'stadium': name, 'city': city, 'state': state, 'roof': roof, 'listed_capacity': capacity,
                        'geo': geo}
        print(team, name, geo and (geo['lat'], geo['lon']), flush=True)
    doc = {'fetched_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'capacity_source': WIKI, 'geocoder': 'OpenStreetMap Nominatim',
           'shared_venue_teams': SHARED, 'venues': venues}
    (HERE / 'venues.json').write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n')
    missing = [t for t, v in venues.items() if v['geo'] is None]
    print('missing coordinates:', missing)


if __name__ == '__main__':
    main()
