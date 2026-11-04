"""Lineup participation: the eleven offensive players on the field, snap by snap (SLC v2, research).

A lineup is a transition, not a fresh draw each snap. The offense calls a personnel package (formal_playcall's code, so '113'
is 11 personnel). The players already on the field stay on unless the new package needs different counts or a player leaves on
his own, with a leave hazard the caller supplies. Moving between packages changes only the players the new counts require.
Entrants come from the eligible roster by the caller's weights. Carriers and targets come only from the players on the field.

Acceptance criteria: docs/research/SLC-V2-LINEUP-ACCEPTANCE-2026-11-02.md (AC1 to AC9). Nothing here is fitted. Entry weights,
leave hazards and usage weights are inputs, so the mechanics are tested apart from any estimate.
"""
import random

import formal_playcall as fp

SLOTS = ('QB', 'BACK', 'TE', 'WR', 'OL')
SLOT_OF = {'QB': 'QB', 'RB': 'BACK', 'FB': 'BACK', 'TE': 'TE', 'WR': 'WR', 'OL': 'OL'}
CARRIER_SLOTS = ('QB', 'BACK', 'WR', 'TE')
TARGET_SLOTS = ('BACK', 'TE', 'WR')


class ShortRoster(ValueError):
    """The package needs more players of a group than the eligible roster has. Nothing is filled from another group."""


class InvalidPackage(ValueError):
    """The code is not an eleven-man offensive package with one or more QBs and five to seven linemen."""


def package(code):
    """'113' -> {'QB': 1, 'BACK': 1, 'TE': 1, 'WR': 3, 'OL': 5}. The QB count is what remains of eleven, so a two-QB package
    keeps its second QB. '112-OL6' has six linemen. A special-teams, invalid or unknown code is refused with its reason."""
    if code.startswith((fp.SPECIAL, fp.INVALID, fp.UNKNOWN)):
        raise InvalidPackage(f'{code}: not an offensive personnel package')
    digits, _, line = code.partition('-OL')
    if len(digits) != 3 or not digits.isdigit() or (line and not line.isdigit()):
        raise InvalidPackage(f'{code}: unreadable personnel code')
    backs, te, wr = (int(d) for d in digits)
    ol = int(line) if line else 5
    qb = fp.OFFENSE_SIZE - ol - backs - te - wr
    if qb < 1:
        raise InvalidPackage(f'{code}: no QB left in eleven')
    if not 5 <= ol <= 7:
        raise InvalidPackage(f'{code}: {ol} linemen')
    return {'QB': qb, 'BACK': backs, 'TE': te, 'WR': wr, 'OL': ol}


class Ledger:
    """Snaps, entries, exits and opportunities per player. A scramble is kept apart from a designed carry (AC7)."""

    def __init__(self):
        self.team_snaps = 0
        self.snaps, self.entries, self.exits = {}, {}, {}
        self.carries, self.qb_designed_runs, self.scrambles, self.targets = {}, {}, {}, {}

    @staticmethod
    def _add(table, player_id):
        table[player_id] = table.get(player_id, 0) + 1

    def snap_share(self, player_id):
        """Simulated snaps over the team's simulated offensive snaps, the plays a lineup was built for (AC9)."""
        if self.team_snaps == 0:
            raise ValueError('no snaps recorded')
        return self.snaps.get(player_id, 0) / self.team_snaps


class Offense:
    """One team's offense through a game. Pass the same rng for the whole game; the same inputs and seed replay exactly (AC8).

    roster: {player_id: group}, the eligible players only (the snapshot's active roster), group one of QB RB FB TE WR OL.
    entry_weight: {player_id: weight > 0}, how likely a bench player is to be sent in for his slot. Missing players get
        floor_weight, never zero, so a player with no history can still enter.
    leave_hazard: f(player_id, group, stint) -> probability he leaves after a snap of `stint` consecutive snaps. Defaults to 0.
    """

    def __init__(self, roster, rng, entry_weight=None, leave_hazard=None, floor_weight=0.01):
        unknown = sorted({g for g in roster.values() if g not in SLOT_OF})
        if unknown:
            raise ValueError(f'roster groups not offensive: {unknown}')
        if floor_weight <= 0:
            raise ValueError('floor_weight must be positive')
        self.roster = dict(roster)
        self.rng = rng
        self.entry_weight = dict(entry_weight or {})
        self.leave_hazard = leave_hazard or (lambda player_id, group, stint: 0.0)
        self.floor_weight = floor_weight
        self.on_field = []
        self.stint = {}
        self.ledger = Ledger()

    def _slot(self, player_id):
        return SLOT_OF[self.roster[player_id]]

    def _weight(self, player_id):
        return self.entry_weight.get(player_id, self.floor_weight)

    def _draw(self, candidates, weights, k):
        """k distinct players, weighted, without replacement."""
        pool, chosen = list(candidates), []
        for _ in range(k):
            pick = self.rng.choices(range(len(pool)), weights=[weights(p) for p in pool])[0]
            chosen.append(pool.pop(pick))
        return chosen

    def advance(self, code):
        """Build the lineup for the next snap and return (entered, left). The snap is counted for every player on the field."""
        need = package(code)
        voluntary = [p for p in self.on_field
                     if self.rng.random() < self.leave_hazard(p, self.roster[p], self.stint[p])]
        staying = [p for p in self.on_field if p not in voluntary]
        lineup, entered = [], []
        for slot in SLOTS:
            incumbents = [p for p in staying if self._slot(p) == slot]
            if len(incumbents) > need[slot]:
                # The package has fewer of this group: the lowest entry weights go off (the third WR in 11 to 12).
                incumbents.sort(key=lambda p: (-self._weight(p), p))
                incumbents = incumbents[:need[slot]]
            deficit = need[slot] - len(incumbents)
            on = set(self.on_field)
            bench = sorted(p for p, g in self.roster.items() if SLOT_OF[g] == slot and p not in on)
            leavers = [p for p in voluntary if self._slot(p) == slot]
            if deficit > len(bench):
                # Nobody to replace him: a voluntary leaver stays on rather than leave the slot empty.
                kept = leavers[:deficit - len(bench)]
                incumbents += kept
                deficit -= len(kept)
            if deficit > len(bench):
                raise ShortRoster(f'{code}: needs {need[slot]} {slot}, {len(incumbents)} on the field and '
                                  f'{len(bench)} eligible on the bench')
            new = self._draw(bench, self._weight, deficit)
            lineup += incumbents + new
            entered += new
        left = [p for p in self.on_field if p not in lineup]
        for p in left:
            del self.stint[p]
            Ledger._add(self.ledger.exits, p)
        for p in lineup:
            self.stint[p] = self.stint.get(p, 0) + 1
            Ledger._add(self.ledger.snaps, p)
        for p in entered:
            Ledger._add(self.ledger.entries, p)
        self.on_field = lineup
        self.ledger.team_snaps += 1
        return entered, left

    def _choose(self, slots, usage_weight):
        candidates = [p for p in self.on_field if self._slot(p) in slots]
        if not candidates:
            raise ShortRoster(f'no player on the field in {slots}')
        return self._draw(candidates, lambda p: usage_weight.get(p, self.floor_weight), 1)[0]

    def carry(self, usage_weight):
        """A designed run: the carrier is drawn from the players on the field (AC6), a QB included."""
        player_id = self._choose(CARRIER_SLOTS, usage_weight)
        Ledger._add(self.ledger.carries, player_id)
        if self._slot(player_id) == 'QB':
            Ledger._add(self.ledger.qb_designed_runs, player_id)
        return player_id

    def passer(self, usage_weight=None):
        """The passer is a QB on the field; a backup QB on the bench never throws (AC6)."""
        return self._choose(('QB',), usage_weight or {})

    def scramble(self, usage_weight=None):
        """A QB run on a pass call. Counted as a scramble, never as a designed carry (AC7)."""
        player_id = self._choose(('QB',), usage_weight or {})
        Ledger._add(self.ledger.scrambles, player_id)
        return player_id

    def target(self, usage_weight):
        """The target is drawn from the eligible receivers on the field (AC6)."""
        player_id = self._choose(TARGET_SLOTS, usage_weight)
        Ledger._add(self.ledger.targets, player_id)
        return player_id


def new_offense(roster, seed, **kwargs):
    return Offense(roster, random.Random(seed), **kwargs)
