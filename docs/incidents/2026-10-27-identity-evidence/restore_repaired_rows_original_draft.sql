-- NOT RUN. Restores the three roster rows changed by the 2026-10-27 repair to their saved values.
-- Only team and team_code change; updated_at and player_id were never changed by the repair.
-- Run only after review. Each UPDATE must touch exactly one row; check changes() before COMMIT.
BEGIN IMMEDIATE;
UPDATE published_roster SET team='Los Angeles FC', team_code='LAFC'
 WHERE league='mls' AND source='fotmob' AND source_player_key='1259117' AND team='Paysandu' AND player_id IS NULL;
-- expect changes()=1
UPDATE published_roster SET team='Los Angeles FC', team_code='LAFC'
 WHERE league='lcup' AND source='fotmob' AND source_player_key='1259117' AND team='Paysandu' AND player_id IS NULL;
-- expect changes()=1
UPDATE published_roster SET team='Red Bull New York', team_code='RBNY'
 WHERE league='mls' AND source='fotmob' AND source_player_key='1787871' AND team='CD FAS' AND player_id IS NULL;
-- expect changes()=1
-- If every expected count matched, COMMIT; otherwise ROLLBACK.
