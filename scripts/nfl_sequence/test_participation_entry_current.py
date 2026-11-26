"""Focused HE regression: legacy behavior remains the default."""
import unittest
from participation_field import Field, TeamKeyed

class EntryWeightTest(unittest.TestCase):
    def test_entry_current_is_independent_of_leave_rate(self):
        field = Field.__new__(Field)
        field.rate = lambda *args: 0.4
        field.entry_share = TeamKeyed(team_at=0)
        field.entry_share[('MIN', 'p1')] = 0.8
        field.entry_share[('MIN', 'p0')] = 0.0
        field.entry_current = False
        self.assertEqual(field.entry_weight('p1', 'MIN', '11', 'RB'), 0.4)
        field.entry_current = True
        self.assertEqual(field.entry_weight('p1', 'MIN', '11', 'RB'), 0.8)
        self.assertEqual(field.entry_weight('p0', 'MIN', '11', 'RB'), 0.0)
        self.assertEqual(field.entry_weight('new', 'MIN', '11', 'RB'), 0.4)

if __name__ == '__main__':
    unittest.main()
