"""Count tables with backoff: the statistical baseline for nfl-seq v0.1.

Every table is a set of categorical histograms. A context (down, distance, field, score, quarter,
call, ...) selects a cell at the finest level that has at least ``min_n`` observations, and falls
back to coarser levels, ending at the unconditional cell. Sampling uses only the engine's own RNG
stream, so a fixed seed gives the same draws every time.

Variants differ only in which context each decision table conditions on:
- ``main``: call and pass-class tables condition on down, distance, field, score and quarter.
- ``state_transition``: the same decisions condition on down, distance and field only.
- ``frequency``: decisions ignore the situation. Physical tables (field goals, punts, kickoffs,
  clock) keep their conditioning in every variant, so only the decision layer differs.
"""
from __future__ import annotations

import bisect
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MODEL_SCHEMA = "nfl-seq-model/1"
DEFAULT_MIN_N = 200

Level = Tuple[str, ...]

FULL: List[Level] = [
    ("down", "dist", "field", "score", "qtr"),
    ("down", "dist", "field", "score"),
    ("down", "dist", "field"),
    ("down", "dist"),
    ("down",),
    (),
]
CLOCK_FULL: List[Level] = [
    ("down", "dist", "field", "score", "qtr", "late"),
    ("down", "dist", "field", "score", "late"),
    ("down", "dist", "field", "late"),
    ("down", "dist", "field"),
    ("down", "dist"),
    ("down",),
    (),
]
COARSE: List[Level] = [("down", "dist", "field"), ("down", "dist"), ("down",), ()]
YARDS_SITUATION: List[Level] = [("down", "dist", "field"), ("dist", "field"), ("field",), ()]
PASS_YARDS: List[Level] = [("dist", "field"), ("field",), ()]
FIELD_ONLY: List[Level] = [("field",), ()]
FLAT: List[Level] = [()]

PHYSICAL_LEVELS: Dict[str, List[Level]] = {
    "punt_gross": FIELD_ONLY,
    "punt_return": FLAT,
    "fg": [("fg",), ()],
    "xp": FLAT,
    "kickoff_touchback": FLAT,
    "kickoff_implied_return": FLAT,
    "elapsed": [("call", "sub"), ("call",), ()],
    "fumble": [("call",), ()],
}
VARIANT_LEVELS: Dict[str, Dict[str, List[Level]]] = {
    "clock": {
        "call": CLOCK_FULL,
        "pass_class": FULL,
        "run_yards": YARDS_SITUATION,
        "pass_yards": PASS_YARDS,
        "sack_yards": FIELD_ONLY,
        "scramble_yards": FIELD_ONLY,
    },
    "main": {
        "call": FULL,
        "pass_class": FULL,
        "run_yards": YARDS_SITUATION,
        "pass_yards": PASS_YARDS,
        "sack_yards": FIELD_ONLY,
        "scramble_yards": FIELD_ONLY,
    },
    "state_transition": {
        "call": COARSE,
        "pass_class": COARSE,
        "run_yards": YARDS_SITUATION,
        "pass_yards": PASS_YARDS,
        "sack_yards": FIELD_ONLY,
        "scramble_yards": FIELD_ONLY,
    },
    "frequency": {
        "call": FLAT,
        "pass_class": FLAT,
        "run_yards": FLAT,
        "pass_yards": FLAT,
        "sack_yards": FLAT,
        "scramble_yards": FLAT,
    },
}


LATE_PERIODS = (2, 4, 5)
LATE_WINDOW_SECONDS = 120


def clock_window(period: int, clock: int) -> str:
    """'late' in the last two minutes of the second half, the fourth quarter or overtime; else 'early'."""
    return "late" if period in LATE_PERIODS and clock <= LATE_WINDOW_SECONDS else "early"


def dist_bin(ydstogo: int) -> str:
    if ydstogo <= 2:
        return "1-2"
    if ydstogo <= 4:
        return "3-4"
    if ydstogo <= 7:
        return "5-7"
    if ydstogo <= 9:
        return "8-9"
    if ydstogo == 10:
        return "10"
    return "11+"


def field_bin(yardline_100: int) -> str:
    if yardline_100 <= 10:
        return "G10"
    if yardline_100 <= 19:
        return "11-19"
    if yardline_100 <= 34:
        return "20-34"
    if yardline_100 <= 49:
        return "35-49"
    if yardline_100 <= 64:
        return "50-64"
    if yardline_100 <= 79:
        return "65-79"
    return "80+"


def score_bin(diff: int) -> str:
    """``diff`` is offense minus defense before the play."""
    if diff <= -9:
        return "L9"
    if diff <= -1:
        return "L"
    if diff == 0:
        return "T"
    if diff <= 8:
        return "W"
    return "W9"


def qtr_bin(period: int) -> str:
    return "4+" if period >= 4 else str(period)


def fg_bin(distance: int) -> str:
    for limit, label in ((29, "<=29"), (34, "30-34"), (39, "35-39"), (44, "40-44"), (49, "45-49"), (54, "50-54")):
        if distance <= limit:
            return label
    return "55+"


def situation(down: int, ydstogo: int, yardline_100: int, period: int, diff: int) -> Dict[str, str]:
    """The decision context, in the same bins the training rows use."""
    return {
        "down": str(down),
        "dist": dist_bin(ydstogo),
        "field": field_bin(yardline_100),
        "score": score_bin(diff),
        "qtr": qtr_bin(period),
    }


def _key(level: Level, ctx: Mapping[str, str]) -> str:
    return "|".join(ctx[name] for name in level)


def _sort_key(value: str) -> Tuple[int, Any]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


class Sampler:
    """Cumulative counts for one cell. ``draw`` uses one uniform from the caller's RNG."""

    __slots__ = ("values", "cum", "total")

    def __init__(self, counts: Mapping[str, int]):
        self.values = sorted(counts, key=_sort_key)
        self.cum: List[int] = []
        running = 0
        for value in self.values:
            running += int(counts[value])
            self.cum.append(running)
        self.total = running

    def draw(self, rng) -> str:
        return self.values[bisect.bisect_right(self.cum, int(rng.random() * self.total))]

    def probabilities(self) -> Dict[str, float]:
        out = {}
        previous = 0
        for value, cum in zip(self.values, self.cum):
            out[value] = (cum - previous) / self.total
            previous = cum
        return out


class Table:
    def __init__(self, levels: Sequence[Level], cells: Sequence[Mapping[str, Mapping[str, int]]], min_n: int):
        if not levels or tuple(levels[-1]) != ():
            raise ValueError("levels must end with the unconditional level ()")
        if len(levels) != len(cells):
            raise ValueError("one cell mapping per level")
        self.levels = [tuple(level) for level in levels]
        self.min_n = min_n
        self._compiled: List[Dict[str, Sampler]] = []
        for level_cells in cells:
            compiled = {}
            for key, counts in level_cells.items():
                if sum(counts.values()) >= min_n or key == "":
                    compiled[key] = Sampler(counts)
            self._compiled.append(compiled)
        if "" not in self._compiled[-1]:
            raise ValueError("the unconditional cell is missing or empty")

    def sampler(self, ctx: Mapping[str, str]) -> Sampler:
        for index, level in enumerate(self.levels):
            sampler = self._compiled[index].get(_key(level, ctx))
            if sampler is not None:
                return sampler
        raise KeyError("no cell for context %r" % (dict(ctx),))

    def draw(self, ctx: Mapping[str, str], rng) -> str:
        return self.sampler(ctx).draw(rng)

    def draw_int(self, ctx: Mapping[str, str], rng) -> int:
        return int(self.draw(ctx, rng))

    def probabilities(self, ctx: Mapping[str, str]) -> Dict[str, float]:
        return self.sampler(ctx).probabilities()


class StatModel:
    def __init__(self, variant: str, min_n: int, tables: Mapping[str, Table], manifest: Mapping[str, Any]):
        self.variant = variant
        self.min_n = min_n
        self.tables = dict(tables)
        self.manifest = dict(manifest)

    def __getitem__(self, name: str) -> Table:
        return self.tables[name]

    def to_dict(self) -> Dict[str, Any]:
        tables = {}
        for name, table in self.tables.items():
            tables[name] = {
                "levels": [list(level) for level in table.levels],
                "cells": [
                    {key: dict(zip(s.values, _counts(s))) for key, s in compiled.items()}
                    for compiled in table._compiled
                ],
            }

        return {
            "schema": MODEL_SCHEMA,
            "model_version": "nfl-seq-v0.1",
            "variant": self.variant,
            "min_n": self.min_n,
            "manifest": self.manifest,
            "tables": tables,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StatModel":
        if data.get("schema") != MODEL_SCHEMA:
            raise ValueError("unknown model schema %r" % (data.get("schema"),))
        tables = {}
        for name, raw in data["tables"].items():
            tables[name] = Table(raw["levels"], raw["cells"], data["min_n"])
        return cls(data["variant"], data["min_n"], tables, data["manifest"])

    @classmethod
    def load(cls, path: str) -> "StatModel":
        with open(path) as handle:
            return cls.from_dict(json.load(handle))

    def save(self, path: str) -> None:
        with open(path, "w") as handle:
            json.dump(self.to_dict(), handle, sort_keys=True, separators=(",", ":"))


def _counts(sampler: Sampler) -> List[int]:
    counts = []
    previous = 0
    for cum in sampler.cum:
        counts.append(cum - previous)
        previous = cum
    return counts


class CountBuilder:
    """Accumulates (context, value) observations for every table of one variant."""

    def __init__(self, variant: str, min_n: int = DEFAULT_MIN_N):
        if variant not in VARIANT_LEVELS:
            raise ValueError("unknown variant %r" % (variant,))
        self.variant = variant
        self.min_n = min_n
        self._levels: Dict[str, List[Level]] = dict(VARIANT_LEVELS[variant])
        self._levels.update(PHYSICAL_LEVELS)
        self._cells: Dict[str, List[Dict[str, Dict[str, int]]]] = {
            name: [dict() for _ in levels] for name, levels in self._levels.items()
        }

    def add(self, name: str, ctx: Mapping[str, str], value: str) -> None:
        for index, level in enumerate(self._levels[name]):
            cells = self._cells[name][index]
            counts = cells.get(_key(level, ctx))
            if counts is None:
                counts = cells[_key(level, ctx)] = {}
            counts[value] = counts.get(value, 0) + 1

    def build(self, manifest: Mapping[str, Any]) -> StatModel:
        tables = {}
        for name, levels in self._levels.items():
            if not self._cells[name][-1].get(""):
                raise ValueError("table %s has no observations" % name)
            tables[name] = Table(levels, self._cells[name], self.min_n)
        return StatModel(self.variant, self.min_n, tables, manifest)


def weighted(dist: Mapping[str, float], weights: Mapping[str, float]) -> Optional[Dict[str, float]]:
    """Multiply a baseline distribution by playbook weights and renormalise. None if all zero."""
    scaled = {value: prob * weights.get(value, 1.0) for value, prob in dist.items()}
    total = sum(scaled.values())
    if total <= 0:
        return None
    return {value: prob / total for value, prob in scaled.items()}
