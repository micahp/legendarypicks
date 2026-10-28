#!/usr/bin/env python3
"""National Weather Service forecast for each week 8 game at a venue that is not a fixed dome.

Uses api.weather.gov: /points gives the forecast grid, forecastHourly gives hourly periods. The period containing the
kickoff hour is recorded with the forecast's own updateTime, so a reader can see how old the forecast is.
Retractable roofs are forecast too: the roof state at kickoff is not known from a forecast.
Output: forecasts.json next to this script. Two requests per venue, one second apart.
"""
import json
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DB = 'file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro'
UA = 'LegendaryPicksResearch/1.0 (weather forecast for backtests and pregame inputs)'
# The database uses WSH and LAR; the venue table is keyed on the nflverse codes WAS and LA.
DB_TO_VENUE = {'WSH': 'WAS', 'LAR': 'LA'}


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/geo+json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    time.sleep(1.0)
    return body


def kickoff_utc(gameday, gametime):
    return pd.Timestamp(f'{gameday} {gametime or "13:00"}').tz_localize('America/New_York').tz_convert('UTC')


def main():
    venues = json.loads((HERE / 'venues.json').read_text())
    shared = venues['shared_venue_teams']
    con = sqlite3.connect(DB, uri=True)
    games = con.execute("select game_id, away_team, home_team, gameday, gametime from nfl_schedule "
                        "where season=2026 and week=8 order by gameday, gametime").fetchall()
    cache = {}
    out = {'fetched_at_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'source': 'api.weather.gov forecastHourly', 'games': {}}
    for game_id, away, home, gameday, gametime in games:
        venue_team = shared.get(home, DB_TO_VENUE.get(home, home))
        venue = venues['venues'][venue_team]
        kickoff = kickoff_utc(gameday, gametime)
        entry = {'home': home, 'away': away, 'venue': venue['stadium'], 'roof': venue['roof'],
                 'kickoff_utc': kickoff.strftime('%Y-%m-%dT%H:%M:%SZ'),
                 'kickoff_local': kickoff.tz_convert('America/New_York').strftime('%Y-%m-%d %H:%M %Z'),
                 'weekday_local': kickoff.tz_convert('America/New_York').strftime('%A')}
        if venue['roof'] == 'Fixed dome':
            entry['forecast'] = None
            entry['forecast_note'] = 'fixed dome: no outdoor weather'
        else:
            geo = venue['geo']
            key = (geo['lat'], geo['lon'])
            try:
                if key not in cache:
                    points = get(f"https://api.weather.gov/points/{geo['lat']},{geo['lon']}")
                    hourly_url = points['properties']['forecastHourly']
                    cache[key] = (hourly_url, get(hourly_url))
                hourly_url, forecast = cache[key]
                periods = forecast['properties']['periods']
                issued = forecast['properties']['updateTime']
                match = min(periods, key=lambda p: abs(pd.Timestamp(p['startTime']) - kickoff))
                entry['forecast'] = {
                    'period_start': match['startTime'], 'temperature_f': match['temperature'],
                    'precip_probability_pct': (match.get('probabilityOfPrecipitation') or {}).get('value'),
                    'wind': match.get('windSpeed'), 'wind_direction': match.get('windDirection'),
                    'short': match.get('shortForecast'), 'issued_utc': issued, 'source_url': hourly_url,
                    'hours_from_issue_to_kickoff': round((kickoff - pd.Timestamp(issued)).total_seconds() / 3600, 1),
                }
            except Exception as exc:  # recorded per game; the other games continue
                entry['forecast'] = None
                entry['forecast_error'] = f'{type(exc).__name__}: {str(exc)[:200]}'
        out['games'][game_id] = entry
        print(game_id, entry.get('forecast') and {k: entry['forecast'][k] for k in
                                                 ('temperature_f', 'precip_probability_pct', 'wind', 'short')},
              entry.get('forecast_error', ''), flush=True)
    (HERE / 'forecasts.json').write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
