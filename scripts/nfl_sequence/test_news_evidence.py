"""Regression tests for RotoWire news evidence bound to a frozen SLC snapshot (news_evidence.py).

The timeline mirrors the 2026 Ravens week 9 case: a named starter on Nov 3, a projected-starter update on Nov 4, and a
post-cutoff change that must not reach the snapshot.
"""
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import news_evidence as ne  # noqa: E402
import pregame_snapshot  # noqa: E402
import source_preflight  # noqa: E402
from nfl_news import NewsFeedError  # noqa: E402

CUTOFF = '2026-11-05T18:00:00Z'  # before the week 9 kickoff (2026-11-06 01:15Z)
GAME_ID = '2026_09_CLE_BAL'
WORKLOAD_MODULES = ('slc_engine.py', 'slc_playcall.py', 'player_outcomes.py', 'target_roles.py', 'player_shares.py',
                    'season_layers.py', 'participation_field.py', 'decision_layer.py', 'qb_decisions.py',
                    'game_state.py', 'e1_drive.py', 'reducer.py')


def update_xml(update_id, player_id, first, last, team, position, published, headline, notes, analysis, injury=''):
    status = f' Status="{injury}"' if injury else ''
    return f"""
    <Update Id="{update_id}">
      <DateTime>{published}</DateTime>
      <Headline>{headline}</Headline>
      <Notes>{notes}</Notes>
      <Analysis>{analysis}</Analysis>
      <Injury{status} Type="" Location="" ReturnDate="" />
      <Player Id="{player_id}">
        <FirstName>{first}</FirstName><LastName>{last}</LastName>
        <Position>{position}</Position>
        <Link>https://www.rotowire.com/football/player/{first.lower()}-{last.lower()}-{player_id}</Link>
      </Player>
      <Team Code="{team}" />
    </Update>
    """


def feed(updates):
    return ("<News><League>NFL</League><Date>2026-11-04</Date><Updates>" + "".join(updates)
            + "</Updates></News>").encode()


def filler():
    """Twenty updates for a team outside the game, so every capture is a complete feed."""
    return [update_xml(9000 + i, 8000 + i, f'Filler{i}', 'Player', 'DET', 'RB', '2026-10-01T09:00:00-04:00',
                       f'Filler headline {i}', 'Filler notes.', 'Filler analysis.') for i in range(20)]


FAGNANO_NAMED = update_xml(101, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-03T14:00:00-05:00',
                           'Joe Fagnano named Week 9 starter',
                           "The report says the Ravens' coach confirmed Fagnano would start.", 'Analysis text.')
FAGNANO_EXPECTED = update_xml(102, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-04T10:00:00-05:00',
                              'Fagnano remains projected starter', 'Notes text.',
                              "The article incorporates new information about Jacoby Brissett, while maintaining "
                              "Fagnano's expected starting status.")
BRISSETT_QUESTIONABLE = update_xml(103, 1002, 'Jacoby', 'Brissett', 'BAL', 'QB', '2026-11-04T12:00:00-05:00',
                                   'Brissett listed on injury report', 'Notes text.', 'Analysis text.',
                                   injury='Questionable')
BRISSETT_NEGATED = update_xml(104, 1002, 'Jacoby', 'Brissett', 'BAL', 'QB', '2026-11-03T16:00:00-05:00',
                              'Brissett headline', 'Notes text.', 'Brissett is not expected to start.')
BRISSETT_OTHER_WEEK = update_xml(105, 1002, 'Jacoby', 'Brissett', 'BAL', 'QB', '2026-10-27T10:00:00-04:00',
                                 'Brissett expected to start', 'Notes text.', 'Analysis text.')
UNRESOLVED = update_xml(106, 1999, 'Nobody', 'Here', 'BAL', 'WR', '2026-11-04T11:00:00-05:00',
                        'Nobody Here named starter', 'Notes text.', 'Analysis text.')
PUBLISHED_AFTER_CUTOFF = update_xml(107, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-05T15:00:00-05:00',
                                    'Fagnano named starter again', 'Notes text.', 'Analysis text.')
FAGNANO_HEADLINE_ONLY = update_xml(110, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-03T15:00:00-05:00',
                                   'Named Week 9 starter', 'Notes text.', 'Analysis text.')
HEADLINE_NAMES_OTHER = update_xml(111, 1002, 'Jacoby', 'Brissett', 'BAL', 'QB', '2026-11-04T09:00:00-05:00',
                                  'Fagnano named starter', 'Notes text.', 'Analysis text.')
BRISSETT_IR = update_xml(112, 1002, 'Jacoby', 'Brissett', 'BAL', 'QB', '2026-11-04T13:00:00-05:00',
                         'Brissett placed on IR', 'Notes text.', 'Analysis text.', injury='IR')
FAGNANO_CHANGED_LATER = update_xml(101, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-03T14:00:00-05:00',
                                   'Joe Fagnano ruled out', 'Notes text.', 'Analysis text.')


def make_db(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT, position TEXT, league TEXT, nfl_gsis_id TEXT);
        CREATE TABLE nfl_schedule(game_id TEXT, season INTEGER, game_type TEXT, week INTEGER, gameday TEXT,
                                  gametime TEXT, away_team TEXT, home_team TEXT);
    """)
    con.executemany('INSERT INTO players VALUES(?,?,?,?,?,?)', [
        (1001, 'Joe Fagnano', 'BAL', 'QB', 'nfl', '00-0040001'),
        (1002, 'Jacoby Brissett', 'BAL', 'QB', 'nfl', '00-0030001'),
        (1003, 'Dillon Gabriel', 'CLE', 'QB', 'nfl', '00-0040100'),
    ])
    con.executemany('INSERT INTO nfl_schedule VALUES(?,?,?,?,?,?,?,?)', [
        ('2026_08_BUF_BAL', 2026, 'REG', 8, '2026-10-29', '20:15', 'BAL', 'BUF'),
        (GAME_ID, 2026, 'REG', 9, '2026-11-05', '20:15', 'BAL', 'CLE'),
        ('2026_10_BAL_PIT', 2026, 'REG', 10, '2026-11-08', '13:00', 'PIT', 'BAL'),
    ])
    con.commit()
    con.close()


def make_snapshot():
    snapshot = {
        'schema': pregame_snapshot.SCHEMA,
        'as_of': CUTOFF,
        'roster_snapshot_id': 'nfl-depth-chart:test',
        'schedule': {'game_id': GAME_ID, 'season': 2026, 'week': 9, 'home_team': 'BAL', 'away_team': 'CLE'},
        'rosters': {
            'home': {'team': 'BAL', 'players': [
                {'player_id': 1001, 'gsis_id': '00-0040001', 'player_name': 'Joe Fagnano', 'pos_abb': 'QB', 'pos_rank': 1},
                {'player_id': 1002, 'gsis_id': '00-0030001', 'player_name': 'Jacoby Brissett', 'pos_abb': 'QB',
                 'pos_rank': 2}]},
            'away': {'team': 'CLE', 'players': [
                {'player_id': 1003, 'gsis_id': '00-0040100', 'player_name': 'Dillon Gabriel', 'pos_abb': 'QB',
                 'pos_rank': 1}]},
        },
    }
    return pregame_snapshot.reseal(snapshot)


class NewsEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = str(self.root / 'picks.db')
        make_db(self.db)
        self.captures = self.root / 'captures'
        self.snapshot = make_snapshot()

    def capture(self, updates, acquired):
        return ne.capture(feed(filler() + updates), self.captures, acquired)

    def standard_captures(self):
        self.capture([FAGNANO_NAMED, BRISSETT_NEGATED, BRISSETT_OTHER_WEEK], '2026-11-03T20:00:00Z')
        self.capture([FAGNANO_NAMED, FAGNANO_EXPECTED, BRISSETT_QUESTIONABLE, UNRESOLVED, PUBLISHED_AFTER_CUTOFF,
                      BRISSETT_NEGATED, BRISSETT_OTHER_WEEK, FAGNANO_HEADLINE_ONLY, HEADLINE_NAMES_OTHER,
                      BRISSETT_IR], '2026-11-04T16:00:00Z')
        # acquired after the cutoff: must not be read or influence the snapshot
        self.capture([FAGNANO_CHANGED_LATER], '2026-11-05T19:00:00Z')

    def items(self, evidence):
        return {row['update_id']: row for row in evidence['items']}

    def test_named_starter_and_projection_are_scoped_and_classified(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        items = self.items(evidence)
        named = items[101]
        self.assertEqual({c['class'] for c in named['classes']}, {'starter_named', 'coach_confirmation_reported'})
        self.assertEqual(named['scope']['method'], 'next_kickoff_after_publication')
        self.assertEqual(named['scope']['kickoff_utc'], '2026-11-06T01:15:00Z')
        self.assertEqual(named['player']['lp_player_id'], 1001)
        self.assertTrue(named['in_snapshot_roster'])
        expected = items[102]
        self.assertEqual({c['class'] for c in expected['classes']}, {'starter_expected'})
        self.assertEqual(expected['classes'][0]['span'], 'Fagnano remains projected starter')

    def test_first_seen_is_the_earliest_capture_of_the_version(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertEqual(self.items(evidence)[101]['first_seen_utc'], '2026-11-03T20:00:00Z')

    def test_injury_designation_comes_from_the_structured_status(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        injury = self.items(evidence)[103]
        self.assertEqual([c['class'] for c in injury['classes']], ['injury_designation'])
        self.assertEqual(injury['classes'][0]['span'], 'Injury Status=Questionable')

    def test_headline_without_the_player_name_is_attributed_to_its_player(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        row = self.items(evidence)[110]
        self.assertEqual([c['class'] for c in row['classes']], ['starter_named'])
        self.assertEqual(row['player']['lp_player_id'], 1001)

    def test_headline_naming_another_player_on_either_team_is_not_attributed(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertNotIn(111, self.items(evidence))

    def test_non_game_injury_status_is_not_a_game_designation(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertEqual([c['class'] for c in self.items(evidence)[112]['classes']], ['injury_status_other'])

    def test_explicit_subject_claim_survives_a_separate_teammate_mention(self):
        multi = update_xml(113, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-04T18:00:00-05:00',
                           'Fagnano update', 'Brissett is out, and Joe Fagnano is named starter.', 'Analysis text.')
        self.capture([multi], '2026-11-04T18:30:00Z')
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertIn('starter_named', [c['class'] for c in self.items(evidence)[113]['classes']])

    def test_explicit_subject_claim_survives_a_preceding_possessive_teammate_mention(self):
        possessive = update_xml(114, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-04T19:00:00-05:00',
                                'Fagnano update', 'Notes text.', "Brissett's status is unclear; Joe Fagnano named starter.")
        self.capture([possessive], '2026-11-05T00:30:00Z')
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertIn('starter_named', [c['class'] for c in self.items(evidence)[114]['classes']])

    def test_same_feed_player_surname_guards_a_teammate_claim_missing_from_the_db(self):
        subject = update_xml(115, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-04T19:00:00-05:00',
                            'Fagnano update', 'Notes text.', 'Newcomer is expected to start Thursday.')
        other = update_xml(116, 1998, 'Alex', 'Newcomer', 'BAL', 'QB', '2026-11-04T19:00:00-05:00',
                           'Newcomer update', 'Notes text.', 'Analysis text.')
        self.capture([subject, other], '2026-11-05T00:30:00Z')
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertNotIn(115, self.items(evidence))

    def test_subject_pronoun_and_age_reference_resolve_from_recent_subject_mention(self):
        item = {'last_name': 'Pitre', 'headline': 'Practice update',
                'notes': 'Pitre practiced fully Wednesday.',
                'analysis': 'Pitre missed the previous game. The 26-year-old should resume his starting role Sunday.',
                'injury_status': ''}
        classes = {row['class'] for row in ne.classify(item, {'Jackson'})}
        self.assertEqual(classes, {'starter_expected'})

    def test_item_subject_resolves_a_pronoun_when_no_competing_player_is_named(self):
        item = {'last_name': 'Johnson', 'headline': 'Practice update', 'notes': '',
                'analysis': 'He should be back in his starting role Sunday.', 'injury_status': ''}
        classes = {row['class'] for row in ne.classify(item, {'Smith'})}
        self.assertEqual(classes, {'starter_expected'})

    def test_subject_claim_is_not_suppressed_by_sentence_level_negation_elsewhere(self):
        item = {'last_name': 'Johnson', 'headline': 'Practice update', 'notes': '',
                'analysis': 'Johnson may not be at full strength, but he should return to his starting role.',
                'injury_status': ''}
        classes = {row['class'] for row in ne.classify(item)}
        self.assertEqual(classes, {'starter_expected'})

    def test_negation_scoped_to_the_start_claim_still_suppresses_it(self):
        item = {'last_name': 'Johnson', 'headline': 'Practice update', 'notes': '',
                'analysis': 'Johnson should not start Thursday.', 'injury_status': ''}
        self.assertEqual(ne.classify(item), [])

    def test_negated_starter_announcement_is_not_emitted(self):
        item = {'last_name': 'Johnson', 'headline': 'Practice update', 'notes': '',
                'analysis': "Johnson hasn't been named the starter for Sunday.", 'injury_status': ''}
        self.assertEqual(ne.classify(item), [])

    def test_hypothetical_naming_is_not_a_completed_starter_announcement(self):
        item = {'last_name': 'Johnson', 'headline': 'Practice update', 'notes': '',
                'analysis': 'Johnson might be named the starter for Sunday.', 'injury_status': ''}
        self.assertEqual(ne.classify(item), [])

    def test_pronoun_after_a_teammate_mention_is_not_assigned_to_the_subject(self):
        item = {'last_name': 'Fagnano', 'headline': 'Fagnano update', 'notes': 'Fagnano practiced Tuesday.',
                'analysis': 'Brissett met with coaches. He is expected to start Thursday.', 'injury_status': ''}
        classes = {row['class'] for row in ne.classify(item, {'Brissett'})}
        self.assertNotIn('starter_expected', classes)

    def test_conditional_teammate_start_remains_excluded(self):
        item = {'last_name': 'Okereke', 'headline': 'Okereke update', 'notes': 'Okereke was limited Tuesday.',
                'analysis': 'If Okereke cannot play Sunday, Tyrel Dodson would likely get the start in his place.',
                'injury_status': ''}
        self.assertEqual(ne.classify(item, {'Dodson'}), [])

    def test_practice_start_and_past_start_counts_are_not_game_start_claims(self):
        item = {'last_name': 'Rice', 'headline': 'Rice update', 'notes': 'Rice is limited to start preparation Tuesday.',
                'analysis': 'He had no starts through five career appearances.', 'injury_status': ''}
        self.assertEqual(ne.classify(item), [])

    def test_dnp_to_start_week_phrase_describes_timing_not_a_starting_role(self):
        item = {'last_name': 'Wicks', 'headline': 'Practice update', 'notes': '',
                'analysis': 'Wicks is trending toward being a DNP to start Week 9.', 'injury_status': ''}
        self.assertEqual(ne.classify(item), [])

    def test_definite_return_to_starting_role_is_named_claim(self):
        item = {'last_name': 'Holland', 'headline': 'Practice update', 'notes': 'Holland practiced fully Tuesday.',
                'analysis': 'Holland has cleared the protocol. He will be back in his starting role Sunday.',
                'injury_status': ''}
        classes = {row['class'] for row in ne.classify(item)}
        self.assertEqual(classes, {'starter_named'})

    def test_role_expectation_and_decided_assignment_language_are_extracted(self):
        item = {'last_name': 'Wentz', 'headline': 'In line to draw MNF start',
                'notes': 'Wentz is stated to start Monday night.',
                'analysis': 'Wentz will get the Week 9 assignment at QB.', 'injury_status': ''}
        classes = {row['class'] for row in ne.classify(item)}
        self.assertEqual(classes, {'starter_expected', 'starter_named'})

    def test_coach_naming_a_starter_is_reported_as_coach_confirmation(self):
        item = {'last_name': 'Fagnano', 'headline': 'Week 9 update', 'notes': '',
                'analysis': 'Head coach Jesse Minter named Fagnano as the starting quarterback for Thursday.',
                'injury_status': ''}
        classes = {row['class'] for row in ne.classify(item)}
        self.assertEqual(classes, {'starter_named', 'coach_confirmation_reported'})

    def test_reported_would_start_and_announced_might_start_are_distinguished(self):
        confirmed = {'last_name': 'Fagnano', 'headline': 'Week 9 update', 'notes': '',
                     'analysis': 'Head coach confirmed Fagnano would start Thursday.', 'injury_status': ''}
        possible = {'last_name': 'Fagnano', 'headline': 'Week 9 update', 'notes': '',
                    'analysis': 'Head coach announced Fagnano might start Thursday.', 'injury_status': ''}
        confirmed_classes = {row['class'] for row in ne.classify(confirmed)}
        self.assertEqual(confirmed_classes, {'starter_named', 'coach_confirmation_reported'})
        self.assertEqual(ne.classify(possible), [])

    def test_publisher_time_after_cutoff_is_excluded_even_in_a_pre_cutoff_capture(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertNotIn(107, self.items(evidence))
        self.assertEqual(evidence['counts']['published_after_cutoff'], 1)

    def test_post_cutoff_capture_is_not_read_and_its_change_never_reaches_the_snapshot(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertEqual(evidence['captures_after_cutoff_count'], 1)
        self.assertEqual(len(evidence['captures_before_cutoff']), 2)
        self.assertEqual(self.items(evidence)[101]['classes'][0]['span'], 'Joe Fagnano named Week 9 starter')
        self.assertNotIn('ruled out', json.dumps(evidence))

    def test_update_from_another_week_is_not_attached_to_this_game(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertNotIn(105, self.items(evidence))
        self.assertGreaterEqual(evidence['counts']['not_next_game'], 1)

    def test_negated_sentence_makes_no_starter_claim(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertNotIn(104, self.items(evidence))
        self.assertGreaterEqual(evidence['counts']['no_classified_content'], 1)

    def test_unresolved_player_is_kept_unlinked_and_counted(self):
        self.standard_captures()
        evidence = ne.build(self.db, self.captures, self.snapshot)
        row = self.items(evidence)[106]
        self.assertIsNone(row['player']['lp_player_id'])
        self.assertFalse(row['in_snapshot_roster'])
        self.assertEqual(evidence['counts']['player_unresolved'], 1)

    def test_evidence_never_changes_the_snapshot_and_declares_no_workload_effect(self):
        self.standard_captures()
        before = copy.deepcopy(self.snapshot)
        evidence = ne.build(self.db, self.captures, self.snapshot)
        self.assertEqual(self.snapshot, before)
        self.assertEqual(evidence['workload_effect'], 'none')
        self.assertEqual(evidence['snapshot_sha256'], self.snapshot['snapshot_sha256'])
        self.assertEqual(evidence['roster_snapshot_id'], self.snapshot['roster_snapshot_id'])

    def test_build_is_reproducible_from_the_captures(self):
        self.standard_captures()
        first = ne.build(self.db, self.captures, self.snapshot)
        second = ne.build(self.db, self.captures, self.snapshot)
        self.assertEqual(first['evidence_sha256'], second['evidence_sha256'])

    def test_naive_publisher_time_is_refused_at_capture(self):
        naive = update_xml(108, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-04T10:00:00', 'Fagnano starter',
                           'Notes text.', 'Analysis text.')
        with self.assertRaisesRegex(ValueError, 'without a timezone'):
            self.capture([naive], '2026-11-04T16:00:00Z')
        self.assertFalse((self.captures / 'manifest.json').exists())

    def test_naive_publisher_time_is_refused_at_build_when_the_whole_feed_is_naive(self):
        naive = [update_xml(9100 + i, 8100 + i, f'Naive{i}', 'Player', 'DET', 'RB', '2026-10-01T09:00:00',
                            f'Naive headline {i}', 'Notes text.', 'Analysis text.') for i in range(20)]
        naive.append(update_xml(108, 1001, 'Joe', 'Fagnano', 'BAL', 'QB', '2026-11-04T10:00:00', 'Fagnano starter',
                                'Notes text.', 'Analysis text.'))
        self.captures.mkdir(parents=True, exist_ok=True)
        raw = feed(naive)
        # an all-naive feed passes the backend sort, so the refusal must come from build's own publisher-time check
        entry = {'name': 'rotowire-nfl-news-20261104T160000Z.xml', 'url': 'test',
                 'acquired_at_utc': '2026-11-04T16:00:00Z', 'sha256': ne.hashlib.sha256(raw).hexdigest(),
                 'bytes': len(raw), 'feed_date': '2026-11-04', 'updates': len(naive)}
        (self.captures / entry['name']).write_bytes(raw)
        (self.captures / 'manifest.json').write_text(json.dumps({'schema': ne.SCHEMA_CAPTURE, 'source': ne.SOURCE,
                                                                 'files': [entry]}))
        with self.assertRaisesRegex(ValueError, 'timezone-qualified'):
            ne.build(self.db, self.captures, self.snapshot)

    def test_capture_file_changed_after_capture_is_refused(self):
        self.standard_captures()
        target = self.captures / 'rotowire-nfl-news-20261104T160000Z.xml'
        target.write_bytes(target.read_bytes().replace(b'Fagnano', b'Brissett', 1))
        with self.assertRaisesRegex(ValueError, 'does not match its manifest hash'):
            ne.build(self.db, self.captures, self.snapshot)

    def test_no_capture_at_or_before_cutoff_is_refused(self):
        self.capture([FAGNANO_NAMED], '2026-11-05T19:00:00Z')
        with self.assertRaisesRegex(ValueError, 'no news capture was acquired at or before the cutoff'):
            ne.build(self.db, self.captures, self.snapshot)

    def test_partial_feed_is_refused_at_capture(self):
        with self.assertRaises(NewsFeedError):
            ne.capture(feed([FAGNANO_NAMED]), self.captures, '2026-11-04T16:00:00Z')

    def test_second_capture_in_the_same_second_is_refused(self):
        self.capture([FAGNANO_NAMED], '2026-11-04T16:00:00Z')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.capture([FAGNANO_NAMED], '2026-11-04T16:00:00Z')

    def test_preflight_refuses_manual_roster_overrides_with_news(self):
        self.standard_captures()
        args = type('Args', (), {'news_evidence_dir': str(self.captures), 'db': self.db,
                                 'roster_snapshot': 'manual.json', 'availability_snapshot': None,
                                 'availability_store': None})()
        with self.assertRaisesRegex(source_preflight.PreflightError, 'cannot be combined with manual overrides'):
            source_preflight.validate_news_evidence(args, self.snapshot)

    def test_preflight_is_off_without_the_flag_and_binds_with_it(self):
        self.standard_captures()
        self.assertIsNone(source_preflight.validate_news_evidence(type('Args', (), {})(), self.snapshot))
        args = type('Args', (), {'news_evidence_dir': str(self.captures), 'db': self.db, 'roster_snapshot': None,
                                 'availability_snapshot': None, 'availability_store': None})()
        evidence = source_preflight.validate_news_evidence(args, self.snapshot)
        self.assertEqual(evidence['workload_effect'], 'none')

    def test_preflight_reports_a_missing_capture_directory_as_a_preflight_failure(self):
        args = type('Args', (), {'news_evidence_dir': str(self.root / 'missing'), 'db': self.db,
                                 'roster_snapshot': None, 'availability_snapshot': None,
                                 'availability_store': None})()
        with self.assertRaises(source_preflight.PreflightError):
            source_preflight.validate_news_evidence(args, self.snapshot)

    def test_workload_modules_do_not_read_news_evidence(self):
        for name in WORKLOAD_MODULES:
            path = HERE / name
            self.assertTrue(path.exists(), f'workload module missing, check this list: {name}')
            source = path.read_text()
            self.assertNotIn('news_evidence', source, name)
            self.assertNotIn('nfl_news', source, name)


if __name__ == '__main__':
    unittest.main()
