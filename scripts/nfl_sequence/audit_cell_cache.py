"""One-pass historical sample indexes for read-only SLC mechanism audits.

The training pool already retains source rows. Only compact counts and numeric
gains are indexed, so each scored play avoids rescanning its historical cell.
"""
from bisect import bisect_left
from collections import Counter, defaultdict


class CellFeatures:
    __slots__ = ("intent_events", "_yards", "_team_yards", "_actions",
                 "_team_actions", "_gain")

    def __init__(self, samples, intent_for):
        self.intent_events = defaultdict(Counter)
        self._yards = defaultdict(list)
        self._team_yards = {
            "offense": defaultdict(lambda: defaultdict(list)),
            "defense": defaultdict(lambda: defaultdict(list)),
        }
        self._actions = Counter()
        self._team_actions = {
            "offense": defaultdict(Counter),
            "defense": defaultdict(Counter),
        }
        gain = defaultdict(lambda: {"total": 0, "touchdowns": 0, "non_td": []})
        for event, row, _runoff, _spot in samples:
            self.intent_events[intent_for(event, row)][event] += 1
            offense, defense = row.get("posteam"), row.get("defteam")
            action = ("punt" if event == "punt" else
                      "field_goal" if event == "field_goal_attempt" else "go")
            self._actions[action] += 1
            self._team_actions["offense"][offense][action] += 1
            self._team_actions["defense"][defense][action] += 1
            yards = row.get("yards_gained")
            if yards is None:
                continue
            if event in ("run", "pass_complete", "sack"):
                self._yards[event].append(yards)
                self._team_yards["offense"][event][offense].append(yards)
                self._team_yards["defense"][event][defense].append(yards)
            if event in ("run", "pass_complete"):
                bucket = gain[event]
                bucket["total"] += 1
                if row.get("touchdown") == 1:
                    bucket["touchdowns"] += 1
                else:
                    bucket["non_td"].append(int(yards))
        for data in gain.values():
            data["non_td"].sort()
        self._gain = dict(gain)

    def yards(self, event, *, side=None, team=None):
        if side is None:
            return self._yards.get(event, [])
        return self._team_yards[side].get(event, {}).get(team, [])

    def gain_probability(self, event, togo):
        """P(yards >= togo OR offensive TD | event), in O(log historical plays)."""
        data = self._gain.get(event)
        if not data:
            return None
        successful = (data["touchdowns"] + len(data["non_td"])
                      - bisect_left(data["non_td"], int(togo)))
        return successful / data["total"]

    def action_counts(self, *, side=None, team=None, fg_allowed=True):
        """Return a copy so score-time FG filtering cannot alter the cache."""
        counts = (self._actions.copy() if side is None else
                  self._team_actions[side].get(team, Counter()).copy())
        if not fg_allowed:
            counts.pop("field_goal", None)
        return counts


def index_pool(pool, intent_for):
    """Build every per-cell index exactly once for a frozen historical pool."""
    return {cell: CellFeatures(samples, intent_for) for cell, samples in pool.items()}
