"""Build the game-level ledger for the goalie-adjustment research.

Outputs research/nhl/goalie-adjustment-2026-10-18/data/ledger.parquet with one row per
(goalie, game) plus one row per game (scores, teams, date). Regular season only,
2008-2025. Derived entirely from /root/nhl_database_2025-26-playoffs.duckdb.
"""
import duckdb
import pandas as pd
import os

DB = '/root/nhl_database_2025-26-playoffs.duckdb'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(OUT, exist_ok=True)

TEAM_FIX = {'L.A': 'LAK', 'N.J': 'NJD', 'S.J': 'SJS', 'T.B': 'TBL',
            'ATL': 'WPG',  # Thrasher franchise history not modelled separately
            'ARI': 'UTA',  # Coyotes -> Utah continuation
            }

con = duckdb.connect(DB, read_only=True)

# --- per-goalie-per-game ledger from shots (the shot-level source of truth) ---
ledger = con.execute("""
WITH sh AS (
  SELECT season, game_id,
         CASE WHEN team = 'HOME' THEN 'AWAY' ELSE 'HOME' END AS goalie_team_side,
         goalieIdForShot AS goalie_id,
         COUNT(*) AS shots_faced,
         SUM(xGoal) AS xg_against,
         SUM(goal) AS goals_against,
         MIN(time) AS first_shot_time
  FROM shots
  WHERE isPlayoffGame = 0 AND goalieIdForShot > 0 AND shotOnEmptyNet = 0
  GROUP BY season, game_id, goalie_team_side, goalie_id
)
SELECT season, game_id, goalie_team_side, goalie_id, shots_faced, xg_against, goals_against, first_shot_time
FROM sh ORDER BY season, game_id
""").fetchdf()

# a goalie STARTED the game if he faced that side's first shot-against
ledger['is_start'] = False
gkey = ledger.groupby(['season', 'game_id', 'goalie_team_side'])['first_shot_time'].transform('min')
ledger.loc[ledger['first_shot_time'] == gkey, 'is_start'] = True

# --- game-level scores, teams from shots ---
games = con.execute("""
SELECT season, game_id,
       MAX(CASE WHEN team='HOME' THEN goal ELSE 0 END) + 0 AS dummy,
       SUM(CASE WHEN team='HOME' THEN 1 ELSE 0 END) AS dummy2
FROM shots WHERE isPlayoffGame=0 GROUP BY season, game_id LIMIT 1
""").fetchdf()

scores = con.execute("""
SELECT season, game_id,
       SUM(CASE WHEN team='HOME' THEN goal ELSE 0 END) AS home_goals,
       SUM(CASE WHEN team='AWAY' THEN goal ELSE 0 END) AS away_goals
FROM shots WHERE isPlayoffGame=0
GROUP BY season, game_id
""").fetchdf()

teams = con.execute("""
SELECT season, game_id,
       MIN(CASE WHEN team='HOME' THEN homeTeamCode END) AS home_team,
       MIN(CASE WHEN team='AWAY' THEN awayTeamCode END) AS away_team
FROM shots WHERE isPlayoffGame=0
GROUP BY season, game_id
""").fetchdf()

# --- game dates from goalies_gamelogs (gameId % 10000 == game_id - 20000) ---
dates = con.execute("""
SELECT season, gameId % 10000 AS gn, MIN(gameDate) AS gameDate
FROM goalies_gamelogs
GROUP BY season, gn
""").fetchdf()

games_df = scores.merge(teams, on=['season', 'game_id'], how='inner')
games_df['gn'] = games_df['game_id'] - 20000
games_df = games_df.merge(dates, on=['season', 'gn'], how='left')
games_df['home_team'] = games_df['home_team'].replace(TEAM_FIX)
games_df['away_team'] = games_df['away_team'].replace(TEAM_FIX)
games_df = games_df.drop(columns=['gn']).dropna(subset=['gameDate'])
games_df['gameDate'] = pd.to_datetime(games_df['gameDate'].astype('int64').astype(str), format='%Y%m%d')

ledger = ledger.merge(games_df[['season', 'game_id', 'home_team', 'away_team', 'gameDate',
                                'home_goals', 'away_goals']],
                      on=['season', 'game_id'], how='inner')
ledger['goalie_team'] = ledger.apply(
    lambda r: r['home_team'] if r['goalie_team_side'] == 'HOME' else r['away_team'], axis=1)

ledger.to_parquet(os.path.join(OUT, 'ledger.parquet'))
games_df.to_parquet(os.path.join(OUT, 'games.parquet'))

print(f"games: {len(games_df):,}  ledger rows: {len(ledger):,}")
print(f"seasons: {games_df['season'].min()}-{games_df['season'].max()}")
print(f"goalies: {ledger['goalie_id'].nunique():,}")
print("date range:", games_df['gameDate'].min(), "to", games_df['gameDate'].max())
print("ledger cols:", list(ledger.columns))
print(games_df.head(3).to_string())
