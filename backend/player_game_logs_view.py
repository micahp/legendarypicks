"""Provider-separated appearance view definitions.

Each provider keeps its own row and stat payload. This view folds matching
provider rows onto one appearance, then adds provider-only appearances once.
"""


VIEW = "player_game_logs_all"

PREVIOUS_DDL_VIEW = """
CREATE VIEW player_game_logs_all AS
    SELECT e.player_id, e.league, e.season, e.game_no, e.game_id, e.game_date,
           e.team, e.opponent, e.home_away, e.game_type,
           e.stats AS espn_stats, f.stats AS fotmob_stats
      FROM player_game_logs e
      LEFT JOIN player_game_logs_fotmob f
        ON f.player_id = e.player_id AND f.game_date = e.game_date
    UNION ALL
    SELECT f.player_id, f.league, f.season, f.game_no, f.game_id, f.game_date,
           f.team, f.opponent, f.home_away, f.game_type,
           NULL AS espn_stats, f.stats AS fotmob_stats
      FROM player_game_logs_fotmob f
     WHERE f.player_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM player_game_logs e
                        WHERE e.player_id = f.player_id AND e.game_date = f.game_date)
""".strip()


DDL_VIEW = """
CREATE VIEW player_game_logs_all AS
    SELECT e.player_id, e.league, COALESCE(s.season,e.season) AS season,
           COALESCE(s.game_no,e.game_no) AS game_no,
           COALESCE(s.game_id,e.game_id) AS game_id, e.game_date,
           COALESCE(s.team,e.team) AS team,
           COALESCE(s.opponent,e.opponent) AS opponent,
           COALESCE(s.home_away,e.home_away) AS home_away,
           COALESCE(s.game_type,e.game_type) AS game_type,
           e.stats AS espn_stats, f.stats AS fotmob_stats,
           s.stats AS sportsdataverse_stats,
           s.appearance_status AS appearance_status
      FROM player_game_logs e
      LEFT JOIN player_game_logs_fotmob f
        ON f.player_id = e.player_id AND f.game_date = e.game_date
      LEFT JOIN (
          SELECT l.* FROM player_game_logs_sportsdataverse l
          JOIN nba_sportsdataverse_releases r
            ON r.season = l.season AND r.release_hash = l.release_hash
      ) s
        ON s.player_id = e.player_id AND s.game_date = e.game_date
       AND e.league = 'nba'
    UNION ALL
    SELECT f.player_id, f.league, COALESCE(s.season,f.season) AS season,
           COALESCE(s.game_no,f.game_no) AS game_no,
           COALESCE(s.game_id,f.game_id) AS game_id, f.game_date,
           COALESCE(s.team,f.team) AS team,
           COALESCE(s.opponent,f.opponent) AS opponent,
           COALESCE(s.home_away,f.home_away) AS home_away,
           COALESCE(s.game_type,f.game_type) AS game_type,
           NULL AS espn_stats, f.stats AS fotmob_stats,
           s.stats AS sportsdataverse_stats,
           s.appearance_status AS appearance_status
      FROM player_game_logs_fotmob f
      LEFT JOIN (
          SELECT l.* FROM player_game_logs_sportsdataverse l
          JOIN nba_sportsdataverse_releases r
            ON r.season = l.season AND r.release_hash = l.release_hash
      ) s
        ON s.player_id = f.player_id AND s.game_date = f.game_date
       AND f.league = 'nba'
     WHERE f.player_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM player_game_logs e
                        WHERE e.player_id = f.player_id AND e.game_date = f.game_date)
    UNION ALL
    SELECT s.player_id, s.league, s.season, s.game_no, s.game_id, s.game_date,
           s.team, s.opponent, s.home_away, s.game_type,
           NULL AS espn_stats, NULL AS fotmob_stats,
           s.stats AS sportsdataverse_stats,
           s.appearance_status AS appearance_status
      FROM player_game_logs_sportsdataverse s
      JOIN nba_sportsdataverse_releases r
        ON r.season = s.season AND r.release_hash = s.release_hash
     WHERE s.player_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM player_game_logs e
                        WHERE e.player_id = s.player_id AND e.game_date = s.game_date)
       AND NOT EXISTS (SELECT 1 FROM player_game_logs_fotmob f
                        WHERE f.player_id = s.player_id AND f.game_date = s.game_date)
""".strip()


ROTOWIRE_DDL_VIEW = """
CREATE VIEW player_game_logs_all AS
    SELECT e.player_id, e.league, COALESCE(s.season,e.season) AS season,
           COALESCE(s.game_no,e.game_no) AS game_no,
           COALESCE(s.game_id,e.game_id) AS game_id, e.game_date,
           COALESCE(s.team,e.team) AS team,
           COALESCE(s.opponent,e.opponent) AS opponent,
           COALESCE(s.home_away,e.home_away) AS home_away,
           COALESCE(s.game_type,e.game_type) AS game_type,
           e.stats AS espn_stats, f.stats AS fotmob_stats,
           r.stats AS rotowire_stats, s.stats AS sportsdataverse_stats,
           s.appearance_status AS appearance_status
      FROM player_game_logs e
      LEFT JOIN player_game_logs_fotmob f
        ON f.player_id = e.player_id AND f.game_date = e.game_date
      LEFT JOIN player_game_logs_rotowire r
        ON r.player_id = e.player_id AND r.game_date = e.game_date
       AND r.league = e.league
      LEFT JOIN (
          SELECT l.* FROM player_game_logs_sportsdataverse l
          JOIN nba_sportsdataverse_releases rel
            ON rel.season = l.season AND rel.release_hash = l.release_hash
      ) s
        ON s.player_id = e.player_id AND s.game_date = e.game_date
       AND e.league = 'nba'
    UNION ALL
    SELECT f.player_id, f.league, COALESCE(s.season,f.season) AS season,
           COALESCE(s.game_no,f.game_no) AS game_no,
           COALESCE(s.game_id,f.game_id) AS game_id, f.game_date,
           COALESCE(s.team,f.team) AS team,
           COALESCE(s.opponent,f.opponent) AS opponent,
           COALESCE(s.home_away,f.home_away) AS home_away,
           COALESCE(s.game_type,f.game_type) AS game_type,
           NULL AS espn_stats, f.stats AS fotmob_stats,
           r.stats AS rotowire_stats, s.stats AS sportsdataverse_stats,
           s.appearance_status AS appearance_status
      FROM player_game_logs_fotmob f
      LEFT JOIN player_game_logs_rotowire r
        ON r.player_id = f.player_id AND r.game_date = f.game_date
       AND r.league = f.league
      LEFT JOIN (
          SELECT l.* FROM player_game_logs_sportsdataverse l
          JOIN nba_sportsdataverse_releases rel
            ON rel.season = l.season AND rel.release_hash = l.release_hash
      ) s
        ON s.player_id = f.player_id AND s.game_date = f.game_date
       AND f.league = 'nba'
     WHERE f.player_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM player_game_logs e
                        WHERE e.player_id = f.player_id AND e.game_date = f.game_date)
    UNION ALL
    SELECT r.player_id, r.league, COALESCE(s.season,r.season) AS season,
           COALESCE(s.game_no,r.game_no) AS game_no,
           COALESCE(s.game_id,r.game_id) AS game_id, r.game_date,
           COALESCE(s.team,r.team) AS team,
           COALESCE(s.opponent,r.opponent) AS opponent,
           COALESCE(s.home_away,r.home_away) AS home_away,
           COALESCE(s.game_type,r.game_type) AS game_type,
           NULL AS espn_stats, NULL AS fotmob_stats,
           r.stats AS rotowire_stats, s.stats AS sportsdataverse_stats,
           s.appearance_status AS appearance_status
      FROM player_game_logs_rotowire r
      LEFT JOIN (
          SELECT l.* FROM player_game_logs_sportsdataverse l
          JOIN nba_sportsdataverse_releases rel
            ON rel.season = l.season AND rel.release_hash = l.release_hash
      ) s
        ON s.player_id = r.player_id AND s.game_date = r.game_date
       AND r.league = 'nba'
     WHERE r.player_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM player_game_logs e
                        WHERE e.player_id = r.player_id AND e.game_date = r.game_date)
       AND NOT EXISTS (SELECT 1 FROM player_game_logs_fotmob f
                        WHERE f.player_id = r.player_id AND f.game_date = r.game_date
                          AND f.league = r.league)
    UNION ALL
    SELECT s.player_id, s.league, s.season, s.game_no, s.game_id, s.game_date,
           s.team, s.opponent, s.home_away, s.game_type,
           NULL AS espn_stats, NULL AS fotmob_stats,
           NULL AS rotowire_stats, s.stats AS sportsdataverse_stats,
           s.appearance_status AS appearance_status
      FROM player_game_logs_sportsdataverse s
      JOIN nba_sportsdataverse_releases rel
        ON rel.season = s.season AND rel.release_hash = s.release_hash
     WHERE s.player_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM player_game_logs e
                        WHERE e.player_id = s.player_id AND e.game_date = s.game_date)
       AND NOT EXISTS (SELECT 1 FROM player_game_logs_fotmob f
                        WHERE f.player_id = s.player_id AND f.game_date = s.game_date)
       AND NOT EXISTS (SELECT 1 FROM player_game_logs_rotowire r
                        WHERE r.player_id = s.player_id AND r.game_date = s.game_date
                          AND r.league = s.league)
""".strip()
