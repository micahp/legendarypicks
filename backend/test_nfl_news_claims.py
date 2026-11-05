import unittest

import nfl_news_claims as claims

ROSTER = [
    claims.roster_entry(100, 'Tyler Huntley'),
    claims.roster_entry(101, 'Joe Fagnano'),
    claims.roster_entry(102, 'Jesse Smith'),
    claims.roster_entry(103, 'Jake Smith'),
]


class ClaimTests(unittest.TestCase):
    def run_extract(self, own, **fields):
        update = {'headline': '', 'notes': '', 'analysis': ''}
        update.update(fields)
        return claims.extract(update, own, ROSTER)

    def test_headline_without_a_name_belongs_to_the_update_player(self):
        result, counts = self.run_extract(101, headline='Named Week 9 starter')
        self.assertEqual([(101, 'own', 'starter_named', 'headline')],
                         [(c['subject_player_id'], c['attribution'], c['claim_class'], c['field']) for c in result])
        self.assertEqual(1, counts['own'])

    def test_teammate_named_in_notes_is_the_subject_not_the_update_player(self):
        result, counts = self.run_extract(100, headline='Injury update',
                                          notes='Coach Jesse Minter named Joe Fagnano Week 9 starter.')
        self.assertEqual([(101, 'named_in_other_update')],
                         [(c['subject_player_id'], c['attribution']) for c in result])
        self.assertEqual(1, counts['named_in_other_update'])

    def test_surname_alone_is_used_only_when_it_is_unique_on_the_team(self):
        result, _ = self.run_extract(100, notes='Minter named Fagnano Week 9 starter.')
        self.assertEqual([101], [c['subject_player_id'] for c in result])

    def test_ambiguous_surname_on_the_team_is_not_attributed(self):
        result, counts = self.run_extract(100, notes='Minter named Smith Week 9 starter.')
        self.assertEqual([], result)
        self.assertEqual(1, counts['ambiguous_mention'])

    def test_sentence_naming_two_roster_players_is_not_attributed(self):
        result, counts = self.run_extract(100, notes='Minter named Joe Fagnano the starter ahead of Tyler Huntley.')
        self.assertEqual([], result)
        self.assertEqual(1, counts['multi_player_sentence'])

    def test_shared_surname_blocks_attribution(self):
        # Two Smiths on the team: "Smith" alone cannot say which one is meant, so the sentence is not attributed.
        result, counts = self.run_extract(100, notes='Minter said Smith is expected to start Week 9.')
        self.assertEqual([], result)
        self.assertEqual(1, counts['ambiguous_mention'])

    def test_full_name_explains_a_shared_surname(self):
        result, counts = self.run_extract(100, notes='Minter named Jesse Smith the Week 9 starter.')
        self.assertEqual([102], [c['subject_player_id'] for c in result])
        self.assertEqual(0, counts['ambiguous_mention'])

    def test_negated_starter_sentence_makes_no_claim(self):
        result, counts = self.run_extract(101, headline='Not expected to start Week 9')
        self.assertEqual([], result)
        self.assertEqual(1, counts['negated'])

    def test_text_without_a_starter_pattern_makes_no_claim(self):
        result, counts = self.run_extract(101, headline='Practices fully', notes='Fagnano was a full participant.')
        self.assertEqual([], result)
        self.assertEqual(0, sum(counts.values()))

    def test_coach_confirmation_is_its_own_class(self):
        result, _ = self.run_extract(101, notes='Coach Jesse Minter confirmed that Fagnano will start Thursday.')
        self.assertIn('coach_confirmation_reported', [c['claim_class'] for c in result])

    def test_each_class_is_kept_once_per_subject_and_field(self):
        result, _ = self.run_extract(101, notes='Fagnano is expected to start. Fagnano is also expected to start.')
        self.assertEqual(1, len([c for c in result if c['claim_class'] == 'starter_expected']))

    def test_own_player_missing_from_the_roster_still_counts_as_a_mention(self):
        # Watson's team roster row is stale or his surname is shared, so he is not on the roster. The sentence still names
        # him, so a sentence that also names a teammate is two-player and must not be attributed to the teammate.
        roster = [claims.roster_entry(102, 'Jesse Smith'), claims.roster_entry(103, 'Jake Smith')]
        result, counts = claims.extract({'headline': '', 'notes': 'Watson is expected to start, leaving Jesse Smith '
                                         'as the likely starting quarterback.', 'analysis': ''},
                                        200, roster, own_name='Deshaun Watson')
        self.assertEqual([], result)
        self.assertEqual(1, counts['multi_player_sentence'])


if __name__ == '__main__':
    unittest.main()
