"""Stored NFL player evidence as of a cutoff, keyed by canonical player id.

Reads the database only. Nothing here calls RotoWire, Sleeper or any other source.

- News: the latest stored version of each update that was captured at or before the cutoff (first_seen_utc is our capture
  time). Publisher time, source URL, RotoWire id and the original text are returned unchanged.
- Starter claims: claims from nfl_news_claims, returned with their subject player. A claim about a teammate is returned
  under that teammate, and the article keeps its original player.
- Projections: player_projections, from the latest as_of at or before the cutoff. Read only, never modified.
- Availability: player_game_availability, from the latest build at or before the cutoff. Read only.
- External projections (external_projections) are keyed by player name, not by player id, so they cannot be joined here
  without guessing. Their row count is reported so the gap stays visible.

Freshness is reported for the serving path: 'fresh' when the newest poll is within FRESH_MINUTES, otherwise 'stale'.
"""
from __future__ import annotations

from datetime import datetime, timezone

FRESH_MINUTES = 45
SOURCE_LABEL = 'RotoWire'


def _utc_iso(value):
    return value.astimezone(timezone.utc).isoformat()


def freshness(con, now):
    row = con.execute('SELECT id, polled_at_utc FROM nfl_player_news_polls ORDER BY id DESC LIMIT 1').fetchone()
    if row is None:
        return {'status': 'missing', 'poll_id': None, 'polled_at_utc': None, 'age_minutes': None}
    age = (now - datetime.fromisoformat(row[1])).total_seconds() / 60
    return {'status': 'fresh' if age <= FRESH_MINUTES else 'stale', 'poll_id': row[0],
            'polled_at_utc': row[1], 'age_minutes': int(age)}


def _known_versions(con, cutoff_iso):
    return con.execute(
        """SELECT u.* FROM nfl_player_news_updates u
           JOIN (SELECT update_id, MAX(first_seen_utc) AS seen FROM nfl_player_news_updates
                 WHERE first_seen_utc <= ? GROUP BY update_id) latest
             ON latest.update_id = u.update_id AND latest.seen = u.first_seen_utc""",
        (cutoff_iso,)).fetchall()


def _claims(con, update_row):
    rows = con.execute(
        """SELECT subject_player_id, update_player_id, attribution, claim_class, field, span
           FROM nfl_player_news_claims WHERE update_id=? AND content_sha256=? ORDER BY claim_index""",
        (update_row['update_id'], update_row['content_sha256'])).fetchall()
    return [dict(row) for row in rows]


def news_for_player(con, player_id, cutoff_iso, limit):
    """Stored articles about this player, or with a claim about this player, known at the cutoff, newest first."""
    articles = []
    for row in _known_versions(con, cutoff_iso):
        claims = _claims(con, row)
        about = [claim for claim in claims if claim['subject_player_id'] == player_id]
        if row['player_id'] != player_id and not about:
            continue
        articles.append({
            'id': row['update_id'],
            'headline': row['headline'],
            'notes': row['notes'],
            'analysis': row['analysis'],
            'published': row['published_raw'],
            'published_utc': row['published_utc'],
            'captured_at_utc': row['first_seen_utc'],
            'url': row['link'],
            'link': row['link'],
            'source_player_id': row['rotowire_player_id'],
            'rotowire_player_id': row['rotowire_player_id'],
            'player_id': row['player_id'],
            'match': row['match'],
            'injury_status': row['injury_status'] or None,
            'injury_type': row['injury_type'] or None,
            'injury_location': row['injury_location'] or None,
            'return_date': row['return_date'] or None,
            'claims': claims,
            'about_player': bool(about),
        })
    articles.sort(key=lambda article: article['published_utc'], reverse=True)
    return articles[:limit]


def projections_for(con, player_id, cutoff_iso, limit=20):
    latest = con.execute('SELECT MAX(as_of) FROM player_projections WHERE player_id=? AND as_of<=?',
                         (player_id, cutoff_iso)).fetchone()[0]
    if latest is None:
        return {'as_of': None, 'rows': []}
    rows = con.execute(
        """SELECT run_id, source, model_version, season, week, game_id, team, stat, mean, median, p10, p90, scenario,
                  p_plays, as_of FROM player_projections WHERE player_id=? AND as_of=?
           ORDER BY season, week, game_id, stat LIMIT ?""", (player_id, latest, limit)).fetchall()
    return {'as_of': latest, 'rows': [dict(row) for row in rows]}


def availability_for(con, player_id, cutoff_iso, limit=10):
    rows = con.execute(
        """SELECT a.season, a.week, a.game_id, a.team, a.played, a.report_status, a.reason, a.source, a.built_at
           FROM player_game_availability a
           JOIN (SELECT game_id, MAX(built_at) AS built FROM player_game_availability
                 WHERE player_id=? AND built_at<=? GROUP BY game_id) latest
             ON latest.game_id = a.game_id AND latest.built = a.built_at
           WHERE a.player_id=? ORDER BY a.season DESC, a.week DESC LIMIT ?""",
        (player_id, cutoff_iso, player_id, limit)).fetchall()
    return [dict(row) for row in rows]


def unjoinable_external_rows(con):
    return con.execute('SELECT COUNT(*) FROM external_projections').fetchone()[0]


def player_evidence(con, player_id, cutoff, limit=10):
    """Everything stored about one canonical player, as of one cutoff (a timezone-aware datetime)."""
    cutoff_iso = _utc_iso(cutoff)
    news = news_for_player(con, player_id, cutoff_iso, limit)
    starter_classes = {'starter_named', 'starter_expected', 'coach_confirmation_reported'}
    starter_claims = [{'article_id': article['id'], **claim} for article in news for claim in article['claims']
                      if claim['subject_player_id'] == player_id and claim['claim_class'] in starter_classes]
    return {
        'player_id': player_id,
        'cutoff_utc': cutoff_iso,
        'news': news,
        'starter_claims': starter_claims,
        'projections': projections_for(con, player_id, cutoff_iso),
        'availability': availability_for(con, player_id, cutoff_iso),
        'external_projections_not_joinable_rows': unjoinable_external_rows(con),
    }


def fantasy_news_response(con, player, limit, now):
    """The response shape the fantasy news panel reads, built from stored data only."""
    fresh = freshness(con, now)
    base = {'player_id': player['id'], 'name': player['name'], 'source': SOURCE_LABEL,
            'source_updated_at': fresh['polled_at_utc']}
    linked = con.execute("SELECT 1 FROM player_source_ids WHERE source='rotowire' AND league='nfl' AND player_id=? LIMIT 1",
                         (player['id'],)).fetchone()
    if linked is None:
        # Without a verified RotoWire id, RotoWire news for this player cannot be identified. Saying "no news" here would
        # be a silent miss, so the response says the identity is missing.
        return {**base, 'data_status': 'unavailable',
                'message': 'RotoWire identity is not linked for this player, so news cannot be verified.', 'articles': []}
    if fresh['status'] == 'missing':
        return {**base, 'data_status': 'unavailable',
                'message': 'Stored NFL news has not been ingested yet.', 'articles': []}
    articles = news_for_player(con, player['id'], _utc_iso(now), limit)
    if fresh['status'] == 'fresh':
        status = 'ready' if articles else 'no_news'
        message = None
    else:
        status = 'stale'
        message = (f"Latest news refresh is {fresh['age_minutes']} minutes old; "
                   + ('showing the last stored news.' if articles else 'no stored news for this player.'))
    return {**base, 'data_status': status, 'message': message, 'articles': articles}
