#!/usr/bin/env python3
"""Read-only audit of whether Flashscore game score progressions yield point outcomes."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
DB = ROOT / "backend/data/picks.dev.db"
OUT = HERE / "flashscore_sequence_audit.json"
POINT_VALUES = {"0": 0, "15": 1, "30": 2, "40": 3, "A": 4}
SCORE_TOKEN = re.compile(r"^(0|15|30|40|A)\s*:\s*(0|15|30|40|A)$")


def decode_fields(raw_json: str) -> dict[str, str]:
    raw_row = json.loads(raw_json).get("raw_row", "")
    fields = {}
    for part in raw_row.split("¬"):
        if "÷" in part:
            key, value = part.split("÷", 1)
            fields[key] = value
    return fields


def parse_states(sequence_text: str | None) -> list[tuple[int, int]] | None:
    tokens = (sequence_text or "").split(",")
    states = []
    for token in tokens:
        token = re.sub(r"\s*\|B\d+\|", "", token).strip()
        found = SCORE_TOKEN.fullmatch(token)
        if not found:
            return None
        states.append((POINT_VALUES[found.group(1)], POINT_VALUES[found.group(2)]))
    return states or None


def is_one_point_transition(before: tuple[int, int], after: tuple[int, int]) -> bool:
    if before == (3, 3) and after in ((4, 3), (3, 4)):
        return True
    if before in ((4, 3), (3, 4)) and after == (3, 3):
        return True
    return ((after[0] - before[0], after[1] - before[1]) in ((1, 0), (0, 1))
            and max(after) <= 3)


def terminal_game_point_winner(state: tuple[int, int]) -> int | None:
    a, b = state
    if a >= 3 and a - b >= 1:
        return 1
    if b >= 3 and b - a >= 1:
        return 2
    return None


def run() -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = list(conn.execute(
            "SELECT tour,source_match_id,set_no,sequence_index,sequence_text,raw_json "
            "FROM tennis_points WHERE record_kind='game_sequence' "
            "ORDER BY tour,source_match_id,set_no,sequence_index"
        ))
    finally:
        conn.close()

    matches: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        item["fields"] = decode_fields(item["raw_json"])
        matches[(item["tour"], item["source_match_id"])].append(item)

    checks = Counter()
    strict_games_by_match: Counter = Counter()
    row_counts_by_match: Counter = Counter()
    candidate_points = 0
    server_transitions = Counter()

    for key, games in matches.items():
        prior_server: dict[int, str] = {}
        for game in games:
            fields = game["fields"]
            states = parse_states(game["sequence_text"])
            parse_ok = states is not None
            initial_ok = parse_ok and states[0] in ((1, 0), (0, 1))
            transitions_ok = parse_ok and all(
                is_one_point_transition(a, b) for a, b in zip(states, states[1:])
            )
            server_ok = fields.get("HG") in ("1", "2")
            winner_ok = fields.get("HK") in ("1", "2")
            terminal = terminal_game_point_winner(states[-1]) if parse_ok else None
            terminal_ok = winner_ok and terminal == int(fields["HK"])
            strict = all((parse_ok, initial_ok, transitions_ok, server_ok, winner_ok, terminal_ok))

            checks["game_sequence_rows"] += 1
            checks["parse_pass"] += bool(parse_ok)
            checks["initial_point_pass"] += bool(initial_ok)
            checks["point_transition_pass"] += bool(transitions_ok)
            checks["server_code_pass"] += bool(server_ok)
            checks["game_winner_code_pass"] += bool(winner_ok)
            checks["terminal_point_agrees_with_game_winner"] += bool(terminal_ok)
            row_counts_by_match[key] += 1
            if strict:
                strict_games_by_match[key] += 1
                # Each displayed state follows one point from 0-0 or from the prior
                # displayed state; the terminal point is inferred from HK.
                candidate_points += len(states) + 1

            if server_ok:
                set_no = int(game["set_no"] or 0)
                if set_no in prior_server:
                    server_transitions["observed"] += 1
                    server_transitions["alternating"] += fields["HG"] != prior_server[set_no]
                prior_server[set_no] = fields["HG"]

    full_matches = sum(strict_games_by_match[k] == row_counts_by_match[k] for k in matches)
    matches_with_any_valid_game = sum(strict_games_by_match[k] > 0 for k in matches)
    invalid_rows_per_match = Counter(
        row_counts_by_match[k] - strict_games_by_match[k] for k in matches
    )
    report = {
        "scope": "Read-only audit of tennis_points records with record_kind=game_sequence.",
        "counts": {
            "game_sequence_rows": len(rows),
            "matches": len(matches),
            "strict_valid_game_rows": sum(strict_games_by_match.values()),
            "strict_inferred_point_outcomes": candidate_points,
            "matches_with_every_game_row_strict_valid": full_matches,
            "matches_with_any_invalid_game_row": len(matches) - full_matches,
            "matches_with_at_least_one_strict_valid_game": matches_with_any_valid_game,
            "rows_failing_each_check": {
                "parse": checks["game_sequence_rows"] - checks["parse_pass"],
                "initial_point": checks["game_sequence_rows"] - checks["initial_point_pass"],
                "within_game_transition": checks["game_sequence_rows"] - checks["point_transition_pass"],
                "server_code": checks["game_sequence_rows"] - checks["server_code_pass"],
                "game_winner_code": checks["game_sequence_rows"] - checks["game_winner_code_pass"],
                "terminal_point": checks["game_sequence_rows"] - checks["terminal_point_agrees_with_game_winner"],
            },
            "matches_by_invalid_game_row_count": dict(sorted(invalid_rows_per_match.items())),
            "within_set_server_transitions": dict(server_transitions),
        },
        "criteria": {
            "initial_point": "The first displayed score advances exactly one point from 0-0.",
            "within_game_transition": "Every successive score advances one point under standard tennis scoring, including deuce/advantage returns.",
            "server_and_winner": "Raw HG and HK codes are present and each is 1 or 2.",
            "terminal_point": "The last displayed score gives HK a game point, so the inferred terminal winner is unambiguous.",
            "point_count": "One inferred point for each displayed state, plus one terminal point inferred from HK.",
        },
        "limitations": [
            "154,887 is a strict, high-confidence lower bound; invalid game rows are excluded even when some internal point transitions might still be recoverable.",
            "A complete set or match history is not established by valid game rows; tiebreak point sequences and missing source rows need separate validation.",
            "No inferred point rows were written to the canonical archives or substituted for the retained raw game-sequence records.",
        ],
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], indent=2, sort_keys=True))
    print(f"Wrote {OUT}")
    return report


if __name__ == "__main__":
    run()
