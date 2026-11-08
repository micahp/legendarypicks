"""Capture RotoWire NFL news as raw files, and build game-scoped pregame news evidence for a frozen SLC snapshot.

Two steps, kept apart:

- capture: the raw feed is fetched, validated with backend/nfl_news.parse_news_feed, and written exactly as served. The
  manifest records each file's SHA-256 and our acquisition time (UTC). Nothing is kept only in memory.
- build: the evidence for one frozen snapshot is read from the captures. An update is admitted only when
  (a) its captured version was acquired at or before the snapshot cutoff, (b) its publisher time is at or before the
  cutoff, and (c) the game is the team's next kickoff after that publisher time, so an item about another week does not
  attach to this game.

The evidence is a record. It classifies what the report says (a named starter, an expected starter, a coach confirmation
attributed by the report, an injury designation). It never writes to a roster, an availability value or a workload input:
the snapshot is read, not changed, and no workload module imports this file (see test_news_evidence).

Not captured by this module: team articles, fantasy projections and any other source. They are listed in `not_captured`
so a missing source is recorded as unknown, not as no news.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'backend'))
import nfl_news  # noqa: E402  (backend RotoWire feed reader and player resolver)
import team_codes  # noqa: E402  (backend team vocabulary; RotoWire and the snapshot both use it)
import pregame_capture  # noqa: E402  (kickoff rule: nflverse gametime is Eastern local time)

SCHEMA_CAPTURE = 'lp-nfl-news-capture-1'
SCHEMA_EVIDENCE = 'lp-nfl-news-evidence-1'
SOURCE = 'rotowire_nfl_news'
WORKLOAD_EFFECT = 'none'
NOT_CAPTURED = ('team_articles', 'team_injury_reports_as_news', 'fantasy_projections_espn_cbs', 'depth_chart_news')
CLASSES = ('starter_named', 'starter_expected', 'coach_confirmation_reported', 'injury_designation',
           'injury_status_other')
GAME_DESIGNATIONS = frozenset({'OUT', 'DOUBTFUL', 'QUESTIONABLE', 'PROBABLE'})
UNOFFICIAL_START = re.compile(
    r'\blisted as (?:a |the )?starting\b[^.!?;]{0,90}\bunofficial depth chart\b', re.IGNORECASE)
TEXT_DESIGNATION = re.compile(
    r'\b(?:is (?:officially )?(?:listed|designated) (?:as )?(?:out|questionable|doubtful|probable)'
    r'|(?:has been |is )?ruled out|will not play|won\x27t play|remains out)'
    r'\s+(?:for |in |on )?(?:Week\s+\d+|(?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)\b)',
    re.IGNORECASE)
PRACTICE_SQUAD_IR = re.compile(
    r'\bplaced\b[^.!?;]{0,90}\bpractice[- ]squad (?:IR|injured (?:list|reserve))\b', re.IGNORECASE)

SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
CLAUSE_SPLIT = re.compile(r'\s+(?:but|however|yet|although|though|whereas)\s+|;\s*', re.IGNORECASE)
START_WORD = r'start(?:s|ed|ing|er|ers)?'
START = re.compile(rf'\b{START_WORD}\b', re.IGNORECASE)
NAMED = re.compile(rf'\b(?:named|announced|confirmed|tabbed)\b[^.!?;]{{0,80}}?\b{START_WORD}\b|'
                    rf'\b{START_WORD}\b[^.!?;]{{0,35}}?\b(?:named|announced|confirmed|tabbed)\b',
                    re.IGNORECASE)
EXPECTED = re.compile(rf'\b(?:expected|projected|projects|likely|set|slated|should|favored|favorite|in line|on track|poised)\b'
                      rf'[^.!?;]{{0,45}}?\b{START_WORD}\b', re.IGNORECASE)
WILL_START = re.compile(r'\b(?:will|shall)\s+(?:(?:still|also|again|continue to)\s+)?'
                        r'(?:start|be starting)\b', re.IGNORECASE)
WILL_START_ROLE = re.compile(
    r'\bwill\s+(?:be|return|resume|take over|remain|retain|hold|keep)\b[^.!?;]{0,35}\b'
    r'(?:starter|starting\s+(?:(?:[A-Za-z-]+)\s+){0,2}'
    r'(?:roles?|jobs?|positions?|spots?|lineups?|quarterbacks?|QBs?|receivers?|wideouts?|running\s+backs?|'
    r'cornerbacks?|CBs?|guards?|linebackers?|safet(?:y|ies)|tackles?|centers?|tight\s+ends?|RBs?|WRs?|TEs?|'
    r'DEs?|DTs?|OL))\b', re.IGNORECASE)
WILL_START_NOUN = re.compile(
    r'\bwill\s+(?:get|make|draw|earn|receive|take)\b[^.!?;]{0,35}\b'
    r'(?:(?:first|second|third|next|the|a|his|her|their)\s+)?start\b', re.IGNORECASE)
DEFINITE = (WILL_START, WILL_START_ROLE, WILL_START_NOUN)
DIRECT_START = re.compile(r'\b(?:is|are)\s+starting\b|\bstarts?\s+(?:(?:on|this|next)\s+)?'
                          r'(?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Week\s+\d+|the game)\b',
                          re.IGNORECASE)
WEEKLY_STATUS_START = re.compile(r'\bDNP\b[^.!?;]{0,45}\bto\s+start\s+Week\s+\d+\b', re.IGNORECASE)
START_ASSIGNMENT = re.compile(
    r'\bwill\s+(?:get|draw|receive|take|earn)\b[^.!?;]{0,60}\b(?:starting\s+)?(?:assignment|job|nod|call)\b',
    re.IGNORECASE)
COACH = re.compile(r'\b(?:coach|head coach|team|staff|organization)\b', re.IGNORECASE)
COACH_CONFIRM = re.compile(r'\b(?:confirm(?:s|ed|ing)?|announc(?:e|es|ed|ing)|named|names|said|says|told)\b',
                           re.IGNORECASE)
HYPOTHETICAL_MODAL = re.compile(r'\b(?P<modal>could|might|would)\b[^.!?;]{0,55}\b' + START_WORD + r'\b',
                                re.IGNORECASE)
NEGATIVE_BEFORE_EXPECTATION = re.compile(
    r"\b(?:not|never|no longer|isn't|aren't|wasn't|weren't|hasn't|haven't|hadn't|doesn't|don't|didn't|"
    r"won't|can't|is not|are not|was not|were not|has not|have not|had not|does not|do not|did not|will not)"
    r"\s+(?:(?:be|been)\s+)?$",
    re.IGNORECASE)
NEGATIVE_IN_CLAIM = re.compile(
    r"\b(?:not|never|no longer|won't|will not|isn't|is not|aren't|are not|shouldn't|should not|"
    r"couldn't|could not|wouldn't|would not|doesn't|does not|didn't|did not|can't|cannot|unlikely)\b",
    re.IGNORECASE)
SUBJECT_REFERENCE = re.compile(
    r'\b(?:he|him|his|she|her|hers|they|them|their|theirs|themselves|'
    r'the\s+(?:\d{1,2}[- ]year[- ]old|(?:\d{4}\s+)?(?:first|second|third|fourth|fifth|sixth|'
    r'seventh|eighth|ninth|tenth)[- ]round\s+pick|rookie|veteran|favorite|backup|quarterback|QB|'
    r'signal[- ]caller|running back|wideout|receiver|linebacker|cornerback|safety|guard|tackle|center|'
    r'tight end))\b', re.IGNORECASE)
NAME_TOKEN = re.compile(r"\b[A-Z][A-Za-z'\-]*[a-z][A-Za-z'\-]*\b")


def _utc(text, label):
    try:
        parsed = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label}: invalid timestamp {text!r}') from exc
    if parsed.tzinfo is None:
        raise ValueError(f'{label}: a timezone-qualified time is required, got {text!r}')
    return parsed.astimezone(timezone.utc)


def _iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def _canonical_sha(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def fetch(url=nfl_news.ROTOWIRE_NFL_NEWS_URL, timeout=20):
    """The raw feed bytes as served. Used only by the capture command; build never fetches."""
    with urllib.request.urlopen(url, timeout=timeout) as response:  # the public RotoWire NFL news feed
        return response.read()


def _parse_feed(raw):
    """The backend feed reader. It sorts by publisher time, so a naive timestamp beside aware ones fails there with a bare
    TypeError; that is reported here as the publisher-time refusal it is."""
    try:
        return nfl_news.parse_news_feed(raw)
    except TypeError as exc:
        raise ValueError('news feed has a publisher time without a timezone; refused') from exc


def capture(feed_bytes, capture_dir, acquired_at, url=nfl_news.ROTOWIRE_NFL_NEWS_URL):
    """Store one raw feed after it passes the feed validator. A partial or invalid feed raises NewsFeedError."""
    acquired = _utc(acquired_at, 'acquired_at')
    feed = _parse_feed(feed_bytes)
    directory = Path(capture_dir)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {'schema': SCHEMA_CAPTURE, 'source': SOURCE, 'files': []}
    name = f"rotowire-nfl-news-{acquired.strftime('%Y%m%dT%H%M%SZ')}.xml"
    if (directory / name).exists() or any(entry['name'] == name for entry in manifest['files']):
        raise ValueError(f'capture {name} already exists; a second capture in the same second is refused')
    (directory / name).write_bytes(feed_bytes)
    entry = {'name': name, 'url': url, 'acquired_at_utc': _iso(acquired),
             'sha256': hashlib.sha256(feed_bytes).hexdigest(), 'bytes': len(feed_bytes),
             'feed_date': feed['feed_date'], 'updates': len(feed['items'])}
    manifest['files'].append(entry)
    manifest['files'].sort(key=lambda item: item['acquired_at_utc'])
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    return entry


def read_captures(capture_dir, cutoff):
    """(entry, raw bytes) for each capture acquired at or before the cutoff, each checked against its manifest hash.

    Captures acquired after the cutoff are not opened: their content could not have been known at the cutoff. Their
    count is returned instead.
    """
    directory = Path(capture_dir)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('schema') != SCHEMA_CAPTURE:
        raise ValueError(f'{directory}: not a news capture manifest')
    before, after = [], 0
    for entry in manifest['files']:
        if _utc(entry['acquired_at_utc'], entry['name']) > cutoff:
            after += 1
            continue
        raw = (directory / entry['name']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError(f"news capture {entry['name']} does not match its manifest hash")
        before.append((entry, raw))
    return before, after


def _name_tokens(text):
    """Capitalised words, lower-cased, with a possessive 's and apostrophes removed and hyphenated names also split. A
    player's name is capitalised in the text; a role word such as "coach" is not, so it cannot match a surname "Coach"."""
    out = set()
    for word in re.findall(r"\b[A-Z][A-Za-z'\-]*[a-z][A-Za-z'\-]*\b", text):
        word = re.sub(r"'s$", '', word, flags=re.IGNORECASE).replace("'", '').lower()
        out.add(word)
        out.update(part for part in word.split('-') if part)
    return out


def _reported_surnames(items):
    """Surnames of players represented in the same feed, including recent moves missing from the DB roster."""
    out = {}
    for item in items:
        try:
            team = nfl_news.normalize_team(item['team'])
        except team_codes.UnknownTeamCode:
            continue
        tokens = nfl_news.normalize_person_name(item['last_name']).split()
        if tokens:
            out.setdefault(team, set()).add(tokens[-1].lower())
    return out


def _surname_mentions(text, own_surnames, other_surnames):
    """Known player-surname mentions with offsets and an unambiguous subject/other tag."""
    mentions = []
    other_names = {part.lower() for name in other_surnames for part in str(name).replace("'", '').split('-') if part}
    for match in NAME_TOKEN.finditer(text):
        token = re.sub(r"'s$", '', match.group(), flags=re.IGNORECASE).replace("'", '').lower()
        parts = {part for part in token.split('-') if part}
        is_subject = bool(parts & own_surnames)
        is_other = bool(parts & other_names)
        owner = 'subject' if is_subject and not is_other else 'other' if is_other and not is_subject else None
        if is_subject or is_other:
            mentions.append((match.start(), match.end(), owner))
    return mentions


def _claim_matches(clause):
    """Return starter-claim class and source spans, with negation scoped to each claim."""
    expected = list(EXPECTED.finditer(clause))
    matches = []
    for match in UNOFFICIAL_START.finditer(clause):
        if not _claim_is_negated(clause, match) and not _claim_is_hypothetical(clause, match):
            matches.append(('starter_expected', match))
    for match in NAMED.finditer(clause):
        if not _claim_is_negated(clause, match) and not _claim_is_hypothetical(clause, match):
            matches.append(('starter_named', match))
    for match in expected:
        if (not _claim_is_negated(clause, match) and not _claim_is_hypothetical(clause, match)
                and not re.search(r'\b(?:behind|backup|supporting role)\b', match.group(), re.IGNORECASE)):
            matches.append(('starter_expected', match))
    definite = [match for pattern in DEFINITE for match in pattern.finditer(clause)]
    definite += list(DIRECT_START.finditer(clause)) + list(START_ASSIGNMENT.finditer(clause))
    weekly_status_start = WEEKLY_STATUS_START.search(clause)
    for match in definite:
        overlaps_expectation = any(match.start() < item.end() and item.start() < match.end() for item in expected)
        is_week_period = (weekly_status_start and weekly_status_start.start() <= match.start()
                          and match.end() <= weekly_status_start.end())
        if (not overlaps_expectation and not is_week_period and not _claim_is_negated(clause, match)
                and not _claim_is_hypothetical(clause, match)):
            matches.append(('starter_named', match))
    return matches


def _claim_is_negated(clause, match):
    prefix = clause[max(0, match.start() - 24):match.start()]
    claim = clause[match.start():match.end()]
    return bool(NEGATIVE_BEFORE_EXPECTATION.search(prefix) or NEGATIVE_IN_CLAIM.search(claim))


def _claim_is_hypothetical(clause, match):
    context_start = max(0, match.start() - 45)
    context = clause[context_start:match.end()]
    modal = HYPOTHETICAL_MODAL.search(context)
    if (modal and context_start + modal.start() >= match.start()
            and modal.group('modal').lower() == 'would'
            and re.match(r'\s*(?:named|announced|confirmed)\b', clause[match.start():], re.IGNORECASE)):
        return False
    return bool(modal)


def _claim_is_subject(clause, match, own_surnames, other_surnames, prior_entity, implicit_headline):
    mentions = _surname_mentions(clause, own_surnames, other_surnames)
    overlapping = [entry for entry in mentions if entry[0] < match.end() and match.start() < entry[1]]
    if overlapping:
        return len({entry[2] for entry in overlapping}) == 1 and overlapping[0][2] == 'subject'

    before = [entry for entry in mentions if entry[1] <= match.start()]
    if before:
        return before[-1][2] == 'subject'

    if prior_entity == 'subject' and SUBJECT_REFERENCE.search(clause):
        return True
    if mentions:
        nearest = min(mentions, key=lambda entry: max(entry[0] - match.end(), match.start() - entry[1], 0))
        distance = max(nearest[0] - match.end(), match.start() - nearest[1], 0)
        tied = [entry for entry in mentions
                if max(entry[0] - match.end(), match.start() - entry[1], 0) == distance]
        return len({entry[2] for entry in tied}) == 1 and nearest[2] == 'subject'
    return implicit_headline


def _last_mentioned_entity(clause, own_surnames, other_surnames, prior_entity):
    mentions = _surname_mentions(clause, own_surnames, other_surnames)
    return mentions[-1][2] if mentions else prior_entity


def classify(item, other_surnames=frozenset()):
    """Classify starter evidence with local negation and player-reference resolution.

    A nameless headline belongs to the update's player. Body claims need an explicit surname or a clear pronoun/role
    reference whose most recent named player is the subject. A nearby teammate's name no longer suppresses a separate
    claim, while a claim nearest to another player or an ambiguous pronoun remains excluded.
    """
    found = {}
    upcoming = bool(item.get('team')) and ('upcoming_game' not in item or bool(item['upcoming_game']))
    own_surnames = _name_tokens(item['last_name'])
    prior_entity = 'subject'  # The feed item is anchored to its Player element; named teammates override this context.
    for index, text in enumerate((item['headline'], item['notes'], item['analysis'])):
        for sentence in SENTENCE_SPLIT.split(text):
            clauses = [part.strip() for part in CLAUSE_SPLIT.split(sentence) if part.strip()]
            for clause in clauses:
                for name, pattern in (('injury_designation', TEXT_DESIGNATION),
                                      ('injury_status_other', PRACTICE_SQUAD_IR)):
                    if name == 'injury_designation' and not upcoming:
                        continue
                    for hit in pattern.finditer(clause):
                        prefix = clause[max(0, hit.start() - 40):hit.start()]
                        if (re.search(r'\b(?:could|might|would|may|not)\s+(?:be\s+)?$', prefix, re.IGNORECASE)
                                or re.search(r'\b(?:last|past|previous)\s+(?:week|season|game)\b',
                                             clause, re.IGNORECASE)):
                            continue
                        week = re.search(r'\bWeek\s+(\d+)', hit.group(), re.IGNORECASE)
                        game = item.get('upcoming_game')
                        if week and game and int(game.split('_')[1]) != int(week.group(1)):
                            continue
                        if _claim_is_subject(clause, hit, own_surnames, other_surnames, prior_entity, index == 0):
                            found.setdefault(name, sentence.strip()[:300])
                hits = _claim_matches(clause)
                for name, hit in hits:
                    if not _claim_is_subject(clause, hit, own_surnames, other_surnames, prior_entity, index == 0):
                        continue
                    if name not in found:
                        found[name] = sentence.strip()[:300]
                    if (name == 'starter_named' and COACH.search(clause) and COACH_CONFIRM.search(clause)
                            and (START.search(clause) or START_ASSIGNMENT.search(clause))):
                        found.setdefault('coach_confirmation_reported', sentence.strip()[:300])
                prior_entity = _last_mentioned_entity(clause, own_surnames, other_surnames, prior_entity)
    if item['injury_status']:
        status = item['injury_status'].upper()
        name = 'injury_designation' if status in GAME_DESIGNATIONS else 'injury_status_other'
        if name != 'injury_designation' or upcoming:
            found.setdefault(name, f"Injury Status={item['injury_status']}")
    return [{'class': name, 'span': found[name]} for name in CLASSES if name in found]


def _game_kickoffs(con, team, season):
    """Sorted (kickoff_utc, game_id) for the team's REG and POST games, or None when a kickoff is not published."""
    rows = con.execute(
        """SELECT game_id, gameday, gametime FROM nfl_schedule
            WHERE season=? AND game_type IN ('REG','POST') AND (home_team=? OR away_team=?)""",
        (season, team, team)).fetchall()
    out = []
    for row in rows:
        if not row['gameday'] or not row['gametime']:
            return None
        out.append((pregame_capture.kickoff_utc(row['gameday'], row['gametime']), row['game_id']))
    return sorted(out)


def build(db, capture_dir, snapshot):
    """Evidence for one frozen snapshot, read from the captures. Raises ValueError when no capture precedes the cutoff."""
    game = snapshot['schedule']
    game_id = game['game_id']
    season = int(game['season'])
    cutoff = _utc(snapshot['as_of'], 'snapshot as_of')
    before, after_count = read_captures(capture_dir, cutoff)
    if not before:
        raise ValueError(f'{game_id}: no news capture was acquired at or before the cutoff {_iso(cutoff)}')

    counts = Counter()
    versions = {}
    for entry, raw in before:
        acquired = _utc(entry['acquired_at_utc'], entry['name'])
        for item in _parse_feed(raw)['items']:
            digest = _canonical_sha(item)
            prior = versions.get(item['id'])
            if prior and prior['item_sha256'] == digest:
                continue
            if prior:
                counts['superseded_by_later_capture'] += 1
            versions[item['id']] = {'item': item, 'item_sha256': digest, 'first_seen': acquired, 'capture': entry}

    teams = {game['home_team'], game['away_team']}
    reported_surnames = _reported_surnames([version['item'] for version in versions.values()])
    current_reported_surnames = set().union(*(reported_surnames.get(team, set()) for team in teams))
    roster_index = {side: {player['gsis_id']: player for player in roster['players']}
                    for side, roster in snapshot['rosters'].items()}
    items = []
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        surnames = {}
        for row in con.execute(
                "SELECT id, name FROM players WHERE league='nfl' AND team IN (?, ?)", (game['home_team'], game['away_team'])):
            tokens = nfl_news.normalize_person_name(row['name']).split()
            if tokens:
                surnames[int(row['id'])] = tokens[-1]
        for update_id in sorted(versions):
            version = versions[update_id]
            item = version['item']
            published = _utc(item['published'], f'update {update_id} DateTime')
            if published > cutoff:
                counts['published_after_cutoff'] += 1
                continue
            try:
                team = nfl_news.normalize_team(item['team'])
            except team_codes.UnknownTeamCode:
                counts['unknown_team'] += 1
                continue
            if team not in teams:
                counts['other_team'] += 1
                continue
            kickoffs = _game_kickoffs(con, team, season)
            if kickoffs is None:
                counts['schedule_incomplete'] += 1
                continue
            next_game = next((entry for entry in kickoffs if entry[0] > published), None)
            if next_game is None or next_game[1] != game_id:
                counts['not_next_game'] += 1
                continue
            own = _name_tokens(item['last_name'])
            other = frozenset((set(surnames.values()) | current_reported_surnames) - own)
            classes = classify(item, other)
            if not classes:
                counts['no_classified_content'] += 1
                continue
            resolution = nfl_news.resolve_source_player(con, item)
            lp_player_id = resolution['player_id']
            gsis_id = None
            if lp_player_id is not None:
                row = con.execute('SELECT nfl_gsis_id FROM players WHERE id=?', (lp_player_id,)).fetchone()
                gsis_id = row['nfl_gsis_id'] if row else None
            if lp_player_id is None:
                counts['player_unresolved'] += 1
            side = 'home' if team == game['home_team'] else 'away'
            items.append({
                'update_id': update_id,
                'publisher_time_utc': _iso(published),
                'first_seen_utc': _iso(version['first_seen']),
                'capture': version['capture']['name'],
                'capture_sha256': version['capture']['sha256'],
                'item_sha256': version['item_sha256'],
                'source_url': item['link'],
                'headline': item['headline'],
                'team': team,
                'side': side,
                'player': {'name': f"{item['first_name']} {item['last_name']}", 'position': item['position'],
                           'source_player_id': item['source_player_id'], 'lp_player_id': lp_player_id,
                           'gsis_id': gsis_id, 'resolution': resolution['method']},
                'in_snapshot_roster': bool(gsis_id) and gsis_id in roster_index.get(side, {}),
                'scope': {'method': 'next_kickoff_after_publication', 'kickoff_utc': _iso(next_game[0])},
                'classes': classes,
            })
    finally:
        con.close()

    items.sort(key=lambda row: (row['publisher_time_utc'], row['update_id']))
    body = {
        'schema': SCHEMA_EVIDENCE,
        'source': SOURCE,
        'game_id': game_id,
        'season': season,
        'week': int(game['week']),
        'as_of': _iso(cutoff),
        'snapshot_sha256': snapshot['snapshot_sha256'],
        'roster_snapshot_id': snapshot['roster_snapshot_id'],
        'workload_effect': WORKLOAD_EFFECT,
        'captures_before_cutoff': [
            {key: entry[key] for key in ('name', 'url', 'acquired_at_utc', 'sha256', 'bytes', 'feed_date', 'updates')}
            for entry, _ in before],
        'captures_after_cutoff_count': after_count,
        'counts': dict(sorted(counts.items())),
        'items': items,
        'not_captured': list(NOT_CAPTURED),
    }
    body['evidence_sha256'] = _canonical_sha({k: v for k, v in body.items() if k != 'evidence_sha256'})
    return body


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='command', required=True)
    cap = sub.add_parser('capture', help='fetch the RotoWire NFL news feed now and store the raw file')
    cap.add_argument('--dir', required=True)
    bld = sub.add_parser('build', help='build game-scoped evidence for one frozen snapshot')
    bld.add_argument('--dir', required=True)
    bld.add_argument('--db', required=True)
    bld.add_argument('--snapshot-file', required=True)
    bld.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    if a.command == 'capture':
        entry = capture(fetch(), a.dir, _iso(datetime.now(timezone.utc)))
        print(json.dumps(entry, indent=1, sort_keys=True))
        return 0
    with open(a.snapshot_file) as handle:
        snapshot = json.load(handle)
    evidence = build(a.db, a.dir, snapshot)
    Path(a.out).write_text(json.dumps(evidence, indent=1, sort_keys=True) + '\n')
    print(f"{len(evidence['items'])} items; counts {evidence['counts']}; evidence_sha256 {evidence['evidence_sha256']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
