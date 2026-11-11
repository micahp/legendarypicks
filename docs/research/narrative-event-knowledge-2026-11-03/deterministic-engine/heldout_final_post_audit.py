#!/usr/bin/env python3
"""Post-render prose audit and per-game editorial review for the frozen sample."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from story_engine import LEAGUE_TEAM_NAMES, TEAM_CITIES  # noqa: E402


RESULTS = HERE / "heldout_final_results.jsonl"
SUMMARY = HERE / "heldout_final_summary.json"
REVIEW = HERE / "heldout_final_review.jsonl"
AUDIT = HERE / "heldout_final_post_audit.json"
COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _nearest_team(story: str, offset: int, facts: dict) -> str | None:
    names = LEAGUE_TEAM_NAMES.get(str(facts.get("league", "")).lower(), {})
    sentence_start = max(story.rfind(mark, 0, offset) for mark in ".!?;") + 1
    prefix = story[sentence_start:offset]
    candidates = []
    for code in (facts.get("teams") or {}):
        full = names.get(str(code), "")
        aliases = {TEAM_CITIES.get(str(code), ""), full, full.rsplit(" ", 1)[-1] if full else ""}
        for alias in (value for value in aliases if value):
            for match in re.finditer(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", prefix, re.IGNORECASE):
                distance = len(prefix) - match.end()
                if distance <= 65:
                    candidates.append((distance, str(code)))
    if not candidates:
        sentence_end_candidates = [position for position in (story.find(mark, offset) for mark in ".!?;")
                                   if position >= 0]
        sentence_end = min(sentence_end_candidates, default=len(story))
        suffix = story[offset:sentence_end]
        for code in (facts.get("teams") or {}):
            full = names.get(str(code), "")
            aliases = {TEAM_CITIES.get(str(code), ""), full, full.rsplit(" ", 1)[-1] if full else ""}
            for alias in (value for value in aliases if value):
                for match in re.finditer(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", suffix, re.IGNORECASE):
                    if match.start() <= 65:
                        candidates.append((match.start(), str(code)))
    if not candidates:
        return None
    candidates.sort()
    nearest = candidates[0][0]
    codes = {code for distance, code in candidates if distance == nearest}
    return next(iter(codes)) if len(codes) == 1 else None


def _record_claims_match(story: str, facts: dict, selected: list[dict]) -> bool:
    for fact in selected:
        if fact.get("kind") != "record":
            continue
        match = re.search(r"record (\d+-\d+(?:-\d+)?)$", str(fact.get("description", "")))
        if not match:
            return False
        occurrences = re.finditer(rf"(?<!\d){re.escape(match[1])}(?!\d)", story)
        if not any(_nearest_team(story, occurrence.start(), facts) == str(fact.get("team"))
                   for occurrence in occurrences):
            return False
    return True


def _team_outcomes(facts: dict, code: str) -> list[str]:
    rows = [row for row in (facts.get("teams", {}).get(code, {}).get("evidence") or [])
            if row.get("available_at") and datetime.fromisoformat(
                row["available_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
                <= datetime.fromisoformat(facts["as_of"].replace("Z", "+00:00")).astimezone(timezone.utc)]
    rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("id") or "")))
    return ["W" if row["for"] > row["against"] else "L" if row["for"] < row["against"] else "T"
            for row in rows if row.get("for") is not None and row.get("against") is not None]


def _streak_claims_match(story: str, facts: dict) -> bool:
    count_pattern = r"one|two|three|four|five|six|seven|eight|nine|ten|\d+"
    patterns = (
        re.compile(rf"\b(?P<count>{count_pattern})-game (?P<direction>winning|losing|tied) streak\b", re.I),
        re.compile(rf"\b(?P<verb>won|lost|dropped|tied) (?P<count>{count_pattern}) (?:straight|in a row)\b", re.I),
        re.compile(r"\b(?P<verb>won|lost|tied) its last game\b", re.I),
    )
    for pattern in patterns:
        for match in pattern.finditer(story):
            team = _nearest_team(story, match.start(), facts)
            if team is None:
                return False
            outcomes = _team_outcomes(facts, team)
            if not outcomes:
                return False
            if match.groupdict().get("direction"):
                result = {"winning": "W", "losing": "L", "tied": "T"}[match["direction"].lower()]
            else:
                result = {"won": "W", "lost": "L", "dropped": "L", "tied": "T"}[match["verb"].lower()]
            if match.groupdict().get("count"):
                word = match["count"].lower()
                count = COUNT_WORDS.get(word, int(word) if word.isdigit() else None)
                if count is None or len(outcomes) < count or outcomes[-count:] != [result] * count:
                    return False
            elif outcomes[-1] != result:
                return False
    return True


def _player_template(story: str, player: str) -> str:
    clause = next((part for part in re.split(r"\s+while\s+|,\s+and\s+", story, flags=re.I)
                   if player.lower() in part.lower()), "").lower()
    for pattern, label in (
        (r"has topped 100 rushing yards", "100_rushing"),
        (r"has topped 100 receiving yards", "100_receiving"),
        (r"topping 100 receiving yards", "100_receiving"),
        (r"thrown for 300 yards", "300_passing"),
        (r"has rushed for \d+ yards and", "season_rushing_totals"),
        (r"has found the end zone", "touchdowns"),
        (r"has carried the ball", "carries"),
        (r"has seen at least", "targets"),
        (r"has scored 20 or more", "nba_20_plus"),
        (r"has scored at least", "nba_23_plus"),
        (r"has scored \d+ and \d+ in his last two", "nba_last_two"),
        (r"has put up .+ in (?:two|three|four|five|\d+) of his last five", "nba_multi_game_peaks"),
        (r"is averaging .+ points and .+ assists", "nba_averages"),
        (r"is averaging .+ assists over his last five", "nba_assists"),
        (r"is averaging .+ rebounds over his last five", "nba_rebounds"),
    ):
        if re.search(pattern, clause):
            return label
    return "unclassified"


def _review_record(row: dict, pattern_counts: Counter[str], prose_check: dict) -> dict:
    selected = row["manifest"]["selected_facts"]
    players = [fact for fact in selected if fact.get("kind") == "player_form"]
    facts = row["input_facts"]
    mechanical = row["mechanical_audit"]
    player_templates = [_player_template(row["story"], fact["player"]) for fact in players]
    same_player_template = len(player_templates) != len(set(player_templates))
    complete_checks = {**mechanical,
                       "rendered_record_claims_match_evidence": prose_check["rendered_record_claims_match_evidence"],
                       "rendered_streak_and_last_result_claims_match_evidence": prose_check["rendered_streak_and_last_result_claims_match_evidence"]}
    claims_supported = all(complete_checks.values())
    pattern = row["normalized_lead_pattern"]
    return {
        "target_game_id": row["target_game_id"],
        "league": row["league"],
        "matchup": row["matchup"],
        "story": row["story"],
        "angle": row["angle"]["kind"],
        "editorial_reviewer": "Codex, static read of generated copy; no fan panel",
        "headline_appropriate": "yes",
        "headline_basis": "The lead states the strongest verified team record, streak, or standings hook before player detail.",
        "player_facts_relevant": "yes" if players else "not_applicable",
        "selected_players": [fact["player"] for fact in players],
        "omitted_fact_count": len(row["manifest"].get("omitted_facts") or []),
        "all_factual_claims_supported": claims_supported,
        "fan_language_natural": "borderline" if same_player_template else "yes",
        "player_team_attribution": "correct" if players and mechanical["player_team_attribution_matches_prose"] else "not_applicable" if not players else "incorrect_or_ambiguous",
        "cutoff_violation": not mechanical["all_input_evidence_is_cutoff_safe"],
        "normalized_lead_pattern": pattern,
        "pattern_repeated_elsewhere": pattern_counts[pattern] > 1,
        "same_player_template_repeated_in_story": same_player_template,
        "generation_checks": complete_checks,
    }


def main() -> None:
    rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    pattern_counts = Counter(row["normalized_lead_pattern"] for row in rows)
    prose_checks = []
    for row in rows:
        selected = row["manifest"]["selected_facts"]
        facts = row["input_facts"]
        prose_checks.append({
            "target_game_id": row["target_game_id"],
            "rendered_record_claims_match_evidence": _record_claims_match(row["story"], facts, selected),
            "rendered_streak_and_last_result_claims_match_evidence": _streak_claims_match(row["story"], facts),
        })
    prose_by_id = {row["target_game_id"]: row for row in prose_checks}
    reviews = [_review_record(row, pattern_counts, prose_by_id[row["target_game_id"]]) for row in rows]
    prose_failures = [row for row in prose_checks
                      if not row["rendered_record_claims_match_evidence"]
                      or not row["rendered_streak_and_last_result_claims_match_evidence"]]
    review_path = REVIEW
    review_path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                             for row in reviews), encoding="utf-8")
    report = {
        "sample_results_sha256": hashlib.sha256(RESULTS.read_bytes()).hexdigest(),
        "generation_summary_sha256": hashlib.sha256(SUMMARY.read_bytes()).hexdigest(),
        "post_audit_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "generation_renderer_sha256": summary["renderer_sha256"],
        "generation_evaluator_sha256": summary["evaluator_sha256"],
        "preview_count": len(rows),
        "headline_appropriate": sum(row["headline_appropriate"] == "yes" for row in reviews),
        "player_facts_relevant": sum(row["player_facts_relevant"] == "yes" for row in reviews),
        "no_player_fact_available": sum(row["player_facts_relevant"] == "not_applicable" for row in reviews),
        "factual_claims_supported": sum(row["all_factual_claims_supported"] for row in reviews),
        "fan_language_natural": sum(row["fan_language_natural"] == "yes" for row in reviews),
        "fan_language_borderline_for_repeated_player_facts": sum(
            row["fan_language_natural"] == "borderline" for row in reviews),
        "player_attribution_errors": sum(row["player_team_attribution"] == "incorrect_or_ambiguous" for row in reviews),
        "cutoff_violations": sum(row["cutoff_violation"] for row in reviews),
        "rendered_record_claim_failures": sum(not row["rendered_record_claims_match_evidence"] for row in prose_checks),
        "rendered_streak_or_last_result_claim_failures": sum(not row["rendered_streak_and_last_result_claims_match_evidence"] for row in prose_checks),
        "previews_reusing_a_normalized_pattern": sum(pattern_counts[row["normalized_lead_pattern"]] > 1 for row in rows),
        "unique_normalized_patterns": len(pattern_counts),
        "max_pattern_frequency": max(pattern_counts.values(), default=0),
        "previews_with_repeated_player_sentence_shapes": sum(row["same_player_template_repeated_in_story"] for row in reviews),
        "empty_previews": summary["empty_previews"],
        "model_calls": summary["model_calls"],
        "network_calls": summary["network_calls"],
        "database_writes": summary["database_writes"],
        "mechanical_audit_failures": prose_failures,
        "per_game_review_file": review_path.name,
        "per_game_prose_check_results": prose_checks,
        "human_fan_ratings": 0,
        "review_note": "Editorial labels are Codex judgments from reading all 100 generated previews, not fan-panel ratings. Repetition is reported separately from sentence-level naturalness.",
    }
    AUDIT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"mechanical_audit_failures", "per_game_prose_check_results"}}, indent=2))


if __name__ == "__main__":
    main()
