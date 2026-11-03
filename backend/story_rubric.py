"""Deterministic, CPU-only editorial-proxy grader for Legendary Picks previews.

This module NEVER writes to the Legendary Picks database, calls a model, or uses
network access. Its scores are rule-based *proxies*, not human editorial judgments.

Input: story_engine.generate_story result merged with its original input facts
and, ideally, a separate mechanical/statistical claim audit.

    grade_record({"story": result["story"], "manifest": result["manifest"],
                  "angle": result["angle"], "input_facts": facts,
                  "mechanical_audit": independently_recomputed_checks})

Batch: python story_rubric.py grade --input heldout_final_results.jsonl \
             --output graded.jsonl --html story_grades.html
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

VERSION = "lp-story-quality-v1.0.0"
WEIGHTS = {
    "grounding": 25,
    "headline": 20,
    "players": 20,
    "fan_voice": 15,
    "freshness": 10,
    "flow": 10,
}
PASTELS = {
    "grounding": "#CBB8F2",  # lavender
    "headline": "#FFD0B2",  # apricot
    "players": "#B9E6D3",  # mint
    "fan_voice": "#BFDDF6",  # sky
    "freshness": "#F4E5A7",  # butter
    "flow": "#F4C7D7",  # blush
}
LABELS = {
    "grounding": "Facts & evidence",
    "headline": "Story angle",
    "players": "Player relevance",
    "fan_voice": "Fan language",
    "freshness": "Pregame timing",
    "flow": "Flow & variety",
}
JARGON = re.compile(
    r"verified evidence|supplied (?:evidence|deltas)|relationship gate|metric alignment|"
    r"no eligible preview|source rows|no relationship cleared|evidence gate|"
    r"opposite directions for this metric|independent recomputation|"
    r"statistically significant relationship|selected evidence|cutoff-safe",
    re.I,
)
SPORTS_TERMS = re.compile(
    r"undefeated|winless|dead last|on a tear|on a roll|riding|"
    r"won|lost|dropped|straight|streak|scored|topped|averaging|"
    r"touchdowns?|rushing|receiving|assists?|rebounds?|hosts?|brings|"
    r"leads?|puts .{0,25} on the line",
    re.I,
)
RECORD_RE = re.compile(r"(?<!\d)\d{1,2}-\d{1,2}(?:-\d{1,2})?(?!\d)")
REPETITIVE_PHRASE = re.compile(r"100 rushing yards in one of (?:his|her|their) last four", re.I)
COMMA_LIST = re.compile(r"(?:\d+,\s*){3,}\d+")
STORY_WORDS_MIN = 28
STORY_WORDS_MAX = 98
MECHANICAL_CHECKS = (
    "nonempty_story",
    "selected_facts_have_linked_source_rows",
    "team_record_and_streak_claims_recompute",
    "head_to_head_claims_recompute",
    "league_rank_claims_recompute",
    "player_stat_claims_recompute",
    "player_team_attribution_matches_prose",
    "all_input_evidence_is_cutoff_safe",
    "target_game_absent_from_prior_evidence",
    "player_team_codes_match_matchup",
)


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _metric(score: int | None, notes: list[str], checks: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"score": None if score is None else max(0, min(100, int(round(score)))),
            "applicable": score is not None, "notes": notes, "checks": checks or {}}


def _evidence_checks(story: str, facts: dict, manifest: dict, audit: dict | None) -> tuple[dict, list[str], bool]:
    notes: list[str] = []
    failures: list[str] = []
    selected = (manifest or {}).get("selected_facts") or []
    as_of = _parse_timestamp(facts.get("as_of"))
    kickoff = _parse_timestamp(facts.get("start_utc"))
    if not as_of or not kickoff or as_of >= kickoff:
        failures.append("Missing or invalid pregame cutoff")
    if not story.strip():
        failures.append("Empty story")
    if not selected:
        failures.append("No selected evidence for story")
    teams = {str(facts.get("away") or ""), str(facts.get("home") or "")}
    provenance_ok = True
    for fact in selected:
        evid = fact.get("evidence") or []
        ids = set(map(str, fact.get("evidence_ids") or []))
        if not evid or not ids or ids != {str(x.get("id")) for x in evid}:
            provenance_ok = False
            failures.append(f"Unsupported evidence link: {fact.get('id', '?')}")
        for item in evid:
            available = _parse_timestamp(item.get("available_at"))
            if not available or not as_of or available > as_of:
                provenance_ok = False
                failures.append(f"Unavailable supporting record: {fact.get('id', '?')}")
                break
        if fact.get("kind") == "player_form":
            if fact.get("team") not in teams:
                failures.append(f"Player team outside matchup: {fact.get('player', '?')}")
            if fact.get("player") and str(fact["player"]).lower() not in story.lower():
                failures.append(f"Selected player omitted from story: {fact['player']}")
    if audit:
        false_checks = [key for key in MECHANICAL_CHECKS if audit.get(key) is False]
        missing_checks = [key for key in MECHANICAL_CHECKS if not isinstance(audit.get(key), bool)]
        if false_checks:
            failures.extend(f"Independent audit failed: {key}" for key in false_checks)
        if missing_checks:
            notes.append("Independent claim audit incomplete: " + ", ".join(missing_checks))
        independently_audited = not (false_checks or missing_checks)
    else:
        independently_audited = False
        notes.append("No independent numeric/semantic claim audit supplied; evidence links alone cannot prove prose accuracy")
    if failures:
        score = 0
    elif independently_audited:
        score = 100
        notes.append("Evidence links, timestamps, and supplied independent mechanical checks pass")
    else:
        score = 60
        notes.append("Source-backed, but independent claim recomputation is required before marking fully verified")
    return (_metric(score, notes, {"selected_fact_count": len(selected),
                                   "provenance_links_valid": provenance_ok,
                                   "independent_mechanical_audit": independently_audited,
                                   "failed_checks": failures}), failures, independently_audited)


def _first_sentence(story: str) -> str:
    # Protect common abbreviations, such as Jr., C.J., and Oct.
    protected = re.sub(r"\b(Jr|Sr|Mr|Dr|Oct|Nov|Dec)\.", r"\1<DOT>", story)
    protected = re.sub(r"\b([A-Z])\.([A-Z])\.", r"\1<DOT>\2<DOT>", protected)
    first = re.split(r"(?<=[.!?])\s+", protected.strip(), maxsplit=1)[0]
    return first.replace("<DOT>", ".")


def _lead_score(story: str, facts: dict, angle: dict) -> dict:
    first = _first_sentence(story).lower()
    kind = str(angle.get("kind") or "")
    notes = []
    checks = {"declared_angle": kind, "first_sentence": _first_sentence(story)}
    score = 65
    must_see = {
        "undefeated": r"undefeated|perfect",
        "winless_last": r"winless|dead last",
        "top_four": r"top four|top[- ]ranked|league's best|two of the",
        "streak_clash": r"won|lost|dropped|straight|streak",
        "winning_streak": r"won|winning streak|straight|riding",
        "records": r"\d+-\d+",
        "star_performance": r"scored|yards|rebounds|assists|touchdowns|on a tear",
        "available_player_facts": r"hosts?|scored|yards|rebounds|assists|touchdowns",
    }
    pattern = must_see.get(kind, r"\d+-\d+|hosts?|visit")
    if re.search(pattern, first, re.I):
        score += 25
        notes.append(f"Lead communicates the selected {kind or 'matchup'} angle")
    else:
        score -= 35
        notes.append(f"First sentence does not clearly establish the selected {kind or 'matchup'} angle")
    if RECORD_RE.search(first) or kind in {"star_performance", "available_player_facts"}:
        score += 10
    # Catch obvious missed marquee team angles in verified team rows.
    teams = facts.get("teams") or {}
    for code in (facts.get("away"), facts.get("home")):
        row = teams.get(code) or {}
        n = int(row.get("games") or 0)
        wins = int(row.get("wins") or 0)
        losses = int(row.get("losses") or 0)
        if row.get("record_verified") is False or n < 4:
            continue
        if wins == n and losses == 0 and "undefeated" not in first and "perfect" not in first:
            score -= 25
            notes.append("An undefeated team was available but not named in the lead")
        if wins == 0 and losses >= 4 and "winless" not in first and "dead last" not in first:
            score -= 20
            notes.append("Winless team was available but not named in the lead")
    return _metric(score, notes, checks)


def _latest_stats(player: dict, as_of: Any) -> dict[str, list[float]]:
    cutoff = _parse_timestamp(as_of)
    rows = []
    for row in player.get("evidence") or []:
        dt = _parse_timestamp(row.get("available_at"))
        if dt and cutoff and dt <= cutoff:
            rows.append(row)
    rows.sort(key=lambda x: (str(x.get("date") or ""), str(x.get("id") or "")), reverse=True)
    rows = rows[:5]
    mapping = {"points": ("PTS", "points"), "assists": ("AST", "assists"),
               "rebounds": ("REB", "rebounds"),
               "rec": ("rec_yds", "receiving_yards"),
               "rush": ("rush_yds", "rushing_yards"),
               "pass": ("pass_yds", "passing_yards")}
    out: dict[str, list[float]] = {}
    for stat, keys in mapping.items():
        values = []
        for row in rows:
            stats = row.get("stats") or {}
            val = next((stats.get(key) for key in keys if stats.get(key) is not None), None)
            if isinstance(val, (float, int)) and not isinstance(val, bool):
                values.append(float(val))
        out[stat] = values
    return out


def _impact(player: dict, as_of: Any, league: str) -> int:
    stats = _latest_stats(player, as_of)
    p, a, r = stats["points"], stats["assists"], stats["rebounds"]
    rec, rush, passing = stats["rec"], stats["rush"], stats["pass"]
    if league == "nba":
        if len(p) >= 4 and (sum(x >= 30 for x in p) >= 2 or sum(x >= 23 for x in p) >= 4):
            return 3
        if len(p) >= 3 and max(p) >= 38 and sum(p) / len(p) >= 22:
            return 3
        if len(a) >= 4 and sum(a) / len(a) >= 9:
            return 2
        if len(r) >= 4 and sum(r) / len(r) >= 12:
            return 2
        if len(p) >= 3 and sum(p) / len(p) >= 23:
            return 2
        return 0
    if len(rec) >= 4 and sum(x >= 100 for x in rec) >= 3:
        return 3
    if len(rush) >= 4 and sum(x >= 100 for x in rush) >= 2:
        return 3
    if len(passing) >= 4 and sum(x >= 300 for x in passing) >= 2:
        return 3
    if player.get("season_totals_complete"):
        logs = [row for row in (player.get("season_logs") or [])
                if (_parse_timestamp(row.get("available_at")) or datetime.max.replace(tzinfo=timezone.utc))
                <= (_parse_timestamp(as_of) or datetime.min.replace(tzinfo=timezone.utc))]
        rush_yards = sum((row.get("stats") or {}).get("rush_yds", 0) or 0 for row in logs)
        rush_tds = sum((row.get("stats") or {}).get("rush_td", 0) or 0 for row in logs)
        if rush_yards >= 350 and rush_tds >= 4:
            return 3
    if len(rush) >= 3 and sum(rush) / len(rush) >= 80:
        return 2
    if len(rec) >= 3 and sum(rec) / len(rec) >= 75:
        return 2
    if len(passing) >= 3 and sum(passing) / len(passing) >= 250:
        return 2
    return 0


def _player_score(story: str, facts: dict, manifest: dict) -> dict:
    league = str(facts.get("league") or "").lower()
    selected = [f for f in (manifest or {}).get("selected_facts") or [] if f.get("kind") == "player_form"]
    available = {str(p.get("player_id", p.get("name"))): p for p in facts.get("players") or []}
    eligible = [p for p in available.values() if _impact(p, facts.get("as_of"), league) >= 2
                and p.get("team") in {facts.get("away"), facts.get("home")}]
    notes: list[str] = []
    if not eligible and not selected:
        return _metric(None, ["No significant player form available; no filler required"],
                       {"selected_players": [], "significant_candidates": 0})
    if not selected:
        return _metric(20, [f"Omitted {len(eligible)} potentially relevant player(s)"],
                       {"selected_players": [], "significant_candidates": len(eligible)})
    impacts = []
    names = []
    for fact in selected:
        name = str(fact.get("player") or "")
        names.append(name)
        player = next((p for p in available.values() if p.get("name") == name and p.get("team") == fact.get("team")), None)
        impacts.append(_impact(player, facts.get("as_of"), league) if player else 0)
    score = 100
    for name, impact in zip(names, impacts):
        if name.lower() not in story.lower():
            score -= 35
            notes.append(f"Selected player absent from prose: {name}")
        if impact == 0:
            score -= 35
            notes.append(f"Low-impact player stat may be filler: {name}")
        elif impact == 2:
            score -= 8
    if REPETITIVE_PHRASE.search(story):
        score -= 20
        notes.append("Single 100-yard rushing outing in four games is not a compelling standalone hook")
    if eligible and max(impacts, default=0) < 3 and any(_impact(p, facts.get("as_of"), league) == 3 for p in eligible):
        score -= 20
        notes.append("A strong player performance was available but not selected")
    if not notes:
        notes.append("Selected player(s) have sustained or standout recent performances")
    return _metric(score, notes, {"selected_players": names, "impact_tiers": impacts,
                                  "significant_candidates": len(eligible)})


def _fan_voice_score(story: str, facts: dict) -> tuple[dict, bool]:
    notes: list[str] = []
    lower = story.lower()
    banned = JARGON.findall(story)
    score = 85
    if SPORTS_TERMS.search(story):
        score += 10
    else:
        score -= 20
        notes.append("Generic language without a recognizable sports angle")
    if banned:
        score = 0
        notes.append("Internal research jargon in published copy: " + ", ".join(sorted(set(banned))))
    if "run differential" in lower and facts.get("league") == "nba":
        score -= 25
        notes.append("Use point differential, never run differential, for basketball")
    if "home turf" in lower and facts.get("league") == "nba":
        score -= 20
        notes.append("Home-turf language is unnatural for basketball")
    if "home court" in lower and facts.get("league") == "nfl":
        score -= 20
        notes.append("Home-court language is unnatural for football")
    if "look to protect home turf" in lower:
        score -= 12
        notes.append("Generic home-turf filler")
    if REPETITIVE_PHRASE.search(story):
        score -= 14
        notes.append("Weak player accomplishment described as noteworthy")
    if re.search(r"\b(?:deltas?|metrics?|per scrimmage play)\b", lower):
        score -= 15
        notes.append("Analyst terminology competing with the story")
    if not notes:
        notes.append("Fan-facing phrasing without internal data terminology")
    return _metric(score, notes, {"banned_phrases": banned}), bool(banned)


def _freshness_score(facts: dict) -> dict:
    as_of = _parse_timestamp(facts.get("as_of"))
    start = _parse_timestamp(facts.get("start_utc"))
    if not as_of or not start:
        return _metric(None, ["Kickoff or as-of timestamp not available"])
    start_basis = str(facts.get("source", {}).get("target_start_basis") or facts.get("start_utc_basis") or "")
    if "midnight_utc_boundary" in start_basis:
        return _metric(None, ["NFL date-only kickoff placeholder; exact pregame freshness cannot be scored"])
    hours = round((start - as_of).total_seconds() / 3600, 2)
    if hours <= 0:
        return _metric(0, ["As-of cutoff is at or after kickoff"], {"hours_to_kickoff": hours})
    if hours <= 48:
        return _metric(100, ["Generated within the 48-hour pregame window"], {"hours_to_kickoff": hours})
    if hours <= 168:
        return _metric(55, ["Early preview: team and player form may change before kickoff"],
                       {"hours_to_kickoff": hours})
    return _metric(15, ["Long-range preview: standings and player form will likely become stale"],
                   {"hours_to_kickoff": hours})


def normalize_pattern(story: str, facts: dict) -> str:
    """Normalize names and numbers for deterministic template-repetition checks."""
    text = story.lower()
    names: set[str] = set()
    for row in (facts.get("teams") or {}).values():
        name = str(row.get("name") or "")
        if name:
            names.add(name)
            names.add(name.split()[-1])
        code = str(row.get("code") or "")
        if code:
            names.add(code)
    for player in facts.get("players") or []:
        if player.get("name"):
            names.add(str(player["name"]))
    for name in sorted((n for n in names if n), key=len, reverse=True):
        text = re.sub(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", "[entity]", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "#", text)
    text = re.sub(r"[^\w\[\]# ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _flow_score(story: str, facts: dict, prior_patterns: list[str]) -> tuple[dict, str]:
    first = _first_sentence(story)
    protected = re.sub(r"\b(Jr|Sr|Mr|Dr|Oct|Nov|Dec)\.", r"\1<DOT>", story)
    protected = re.sub(r"\b([A-Z])\.([A-Z])\.", r"\1<DOT>\2<DOT>", protected)
    sentence_count = len(re.findall(r"[.!?](?:\s+|$)", protected))
    word_count = len(story.split())
    pattern = normalize_pattern(story, facts)
    notes: list[str] = []
    score = 100
    if not 1 <= sentence_count <= 3:
        score -= 35
        notes.append(f"Unexpected sentence count: {sentence_count}")
    if word_count < STORY_WORDS_MIN:
        score -= 15
        notes.append(f"Preview may be too thin ({word_count} words)")
    elif word_count > STORY_WORDS_MAX:
        score -= 15
        notes.append(f"Preview may be padded ({word_count} words)")
    if REPETITIVE_PHRASE.search(story):
        score -= 15
        notes.append("Mechanical low-impact player-stat construction")
    if len(re.findall(r"\bhas topped 100 rushing yards\b", story, re.I)) >= 2:
        score -= 30
        notes.append("Same weak player-stat sentence repeated for both teams")
    if len(re.findall(r"\b(?:while|counters with)\b", story, re.I)) > 2:
        score -= 12
        notes.append("Too many contrast connectors in a short preview")
    if COMMA_LIST.search(story):
        score -= 8
        notes.append("Dense comma-separated statistic list")
    if pattern and prior_patterns:
        seen = prior_patterns.count(pattern)
        if seen:
            score -= min(25, 15 + 5 * seen)
            notes.append(f"Exact normalized sentence pattern previously observed {seen} time(s)")
    if first and first.endswith(".") and len(first.split()) < 6:
        score -= 10
        notes.append("Headline sentence may be too generic")
    if not notes:
        notes.append("Concise sentence construction without obvious repetitions")
    return _metric(score, notes, {"word_count": word_count, "sentence_count": sentence_count,
                                  "prior_exact_pattern_matches": prior_patterns.count(pattern)}), pattern


def grade_record(row: dict[str, Any], *, prior_patterns: list[str] | None = None) -> dict[str, Any]:
    """Grade one story using evidence in `row`; no I/O, models, or nondeterminism."""
    story = str(row.get("story") or "")
    facts = row.get("input_facts") or row.get("facts") or {}
    if not facts:
        # Permit direct invocation with a story_engine bundle embedded as `bundle`.
        facts = row.get("bundle") or {}
    manifest = row.get("manifest") or {}
    audit = row.get("mechanical_audit")
    grounding, failures, audited = _evidence_checks(story, facts, manifest, audit)
    headline = _lead_score(story, facts, row.get("angle") or {})
    players = _player_score(story, facts, manifest)
    voice, jargon = _fan_voice_score(story, facts)
    freshness = _freshness_score({**facts, "start_utc_basis": row.get("start_utc_basis") or facts.get("start_utc_basis")})
    flow, pattern = _flow_score(story, facts, prior_patterns or [])
    dimensions = {
        "grounding": grounding, "headline": headline, "players": players,
        "fan_voice": voice, "freshness": freshness, "flow": flow,
    }
    total_weight = sum(WEIGHTS[k] for k, val in dimensions.items() if val["applicable"])
    earned_weight = sum(WEIGHTS[k] * dimensions[k]["score"] / 100
                        for k in WEIGHTS if dimensions[k]["applicable"])
    score = round(100 * earned_weight / total_weight) if total_weight else None
    for key, dim in dimensions.items():
        dim["weight"] = WEIGHTS[key]
        dim["earned_points"] = round(WEIGHTS[key] * (dim["score"] or 0) / 100, 2) if dim["applicable"] else None
        dim["label"] = LABELS[key]
        dim["color"] = PASTELS[key]
    if failures:
        gate = "blocked"
    elif not audited:
        gate = "needs-audit"
    elif (jargon or score is None or score < 75 or headline["score"] < 55
          or voice["score"] < 70 or (players["applicable"] and players["score"] < 60)
          or (freshness["applicable"] and freshness["score"] < 70)):
        gate = "review"
    else:
        gate = "eligible"
    as_of = facts.get("as_of") or row.get("as_of") or ""
    story_id = hashlib.sha256((VERSION + "\n" + str(row.get("target_game_id") or facts.get("game_id"))
                               + "\n" + str(as_of) + "\n" + story).encode()).hexdigest()[:20]
    return {
        "rubric_version": VERSION,
        "story_id": story_id,
        "target_game_id": str(row.get("target_game_id") or facts.get("game_id") or ""),
        "league": str(row.get("league") or facts.get("league") or ""),
        "as_of": as_of,
        "score": score,
        "gate": gate,
        "dimensions": dimensions,
        "hard_failures": sorted(set(failures)),
        "independent_fact_audit_supplied": audited,
        "pattern": pattern,
        "story": story,
        "notes": ["Editorial scores are deterministic heuristics, not human fan ratings."],
    }


def grade_jsonl(input_path: Path, *, prior_history: list[str] | None = None) -> list[dict]:
    grades = []
    patterns = list(prior_history or [])
    for line_number, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
        grade = grade_record(row, prior_patterns=patterns[-50:])
        grades.append(grade)
        patterns.append(grade["pattern"])
    return grades




def append_ledger(grades: list[dict], path: Path) -> int:
    """Append unseen story/version scores to a local JSONL ledger (Linux, lock-safe).

    Never overwrites an existing grade. Re-grading with an updated rubric version
    produces a new story ID; the ledger therefore preserves score history.
    """
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            existing = set()
            for line in handle:
                if line.strip():
                    try:
                        existing.add(json.loads(line)["story_id"])
                    except (json.JSONDecodeError, KeyError) as exc:
                        raise ValueError("Malformed ledger row; refusing to append to avoid corruption") from exc
            handle.seek(0, 2)
            for grade in grades:
                if grade["story_id"] not in existing:
                    handle.write(json.dumps(grade, ensure_ascii=False, sort_keys=True) + "\n")
                    existing.add(grade["story_id"])
                    count += 1
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return count


def read_grades(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def write_html(grades: list[dict], path: Path) -> None:
    """Produce a self-contained HTML dashboard; no CDN, tracking, or network calls."""
    data = json.dumps(grades, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    path.write_text("""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Legendary Picks | Story Quality</title>
<style>
:root{--ink:#172236;--muted:#647088;--paper:#f8f7f4;--line:#e5e7ec;--good:#286451;--bad:#994957}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1080px;margin:0 auto;padding:30px 20px 70px}h1{font-size:27px;letter-spacing:-.8px;margin:0 0 5px}
.subtitle{color:var(--muted);margin:0 0 24px}.overview{display:flex;gap:12px;flex-wrap:wrap;margin:13px 0}.overview div{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px 14px;min-width:125px}.overview strong{font-size:20px;display:block}.overview small{color:var(--muted)}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 24px}
select,input{background:#fff;border:1px solid #d6dce5;border-radius:10px;padding:10px 12px;color:var(--ink);font:inherit}
input{flex:1;min-width:180px}.legend{display:flex;gap:12px 20px;flex-wrap:wrap;margin:22px 0 16px;color:#46516a;font-size:12px}
.swatch{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.card{background:#fff;border:1px solid var(--line);border-radius:15px;padding:20px;margin:12px 0;box-shadow:0 1px 3px #0b1a300b}
.cardhead{display:flex;align-items:baseline;justify-content:space-between;gap:15px}.meta{font-size:12px;color:var(--muted)}
.story{font-size:15px;margin:13px 0 17px;line-height:1.65}.score{font-size:20px;font-weight:750;white-space:nowrap}
.gate{font-size:11px;letter-spacing:.03em;text-transform:uppercase;font-weight:700;color:#566176}
.gate.blocked{color:var(--bad)}.gate.eligible{color:var(--good)}
.stack{height:19px;width:100%;display:flex;gap:3px;border-radius:5px;overflow:hidden;background:#f1f1f2}
.segment{height:100%;position:relative;background:#eceff1}.segment>.filled{height:100%;display:block;transition:width .25s}
.dimensions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:17px 0}
.dimtitle{display:flex;justify-content:space-between;gap:8px;font-size:12px;margin-bottom:4px}
.dimbar{background:#f2f2f3;height:7px;border-radius:4px;overflow:hidden}.dimbar>div{height:100%;border-radius:4px}
summary{cursor:pointer;color:#4b5d75;font-weight:600;font-size:12px;margin-top:12px}
.dimnote{font-size:12px;color:#697589;margin:3px 0 7px 0}.warning{color:#a54855;font-size:12px}
.footer{font-size:12px;color:#667086;margin-top:25px}@media(max-width:680px){.dimensions{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding:18px 13px}.card{padding:16px}}
</style></head><body><main>
<h1>Story quality rubric</h1><p class="subtitle">CPU-only, deterministic editorial proxies. The factual gate is separate from the style score.</p>
<div class="toolbar"><input id="search" placeholder="Search story or game ID"/><select id="league"><option value="">All leagues</option><option>nfl</option><option>nba</option></select><select id="gate"><option value="">All statuses</option><option>eligible</option><option>review</option><option>needs-audit</option><option>blocked</option></select><select id="order"><option value="low">Lowest scores first</option><option value="high">Highest scores first</option></select></div>
<div id="count" class="meta"></div><div id="overview" class="overview"></div><div id="legend" class="legend"></div><div id="cards"></div>
<div class="footer">Scores are deterministic checks and heuristics, not a measure of human preference. An “eligible” result means the supplied independent mechanical audit passed; it does not guarantee that a fan will like the writing. Rubric version: <span id="version"></span>.</div>
</main><script>
const rows = __DATA__;
const keys = ["grounding","headline","players","fan_voice","freshness","flow"];
const esc = (s) => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const color = k => rows[0]?.dimensions[k]?.color || '#ddd';
document.getElementById('legend').innerHTML = keys.map(k=>'<span><span class="swatch" style="background:'+color(k)+'"></span>'+esc(rows[0]?.dimensions[k]?.label||k)+'</span>').join('');
document.getElementById('version').textContent=rows[0]?.rubric_version||'unknown';
function render(){
let q=document.getElementById('search').value.toLowerCase(),lg=document.getElementById('league').value,g=document.getElementById('gate').value,order=document.getElementById('order').value;
let selected=rows.filter(r=>(!lg||r.league===lg)&&(!g||r.gate===g)&&(!q||(r.story+' '+r.target_game_id).toLowerCase().includes(q))).sort((a,b)=>order==='low'?(a.score??-1)-(b.score??-1):(b.score??-1)-(a.score??-1));
document.getElementById('count').textContent=selected.length+' of '+rows.length+' stories';
const numeric=selected.filter(r=>r.score!==null).map(r=>r.score), mean=numeric.length?Math.round(numeric.reduce((a,b)=>a+b,0)/numeric.length):'N/A';
document.getElementById('overview').innerHTML=[['Average score',mean=== 'N/A'?mean:mean+'/100'],['Eligible',selected.filter(r=>r.gate==='eligible').length],['Needs audit',selected.filter(r=>r.gate==='needs-audit').length],['Blocked',selected.filter(r=>r.gate==='blocked').length]].map(([label,value])=>'<div><strong>'+value+'</strong><small>'+label+'</small></div>').join('');
document.getElementById('cards').innerHTML=selected.map(r=>{
const dims=keys.map(k=>{const d=r.dimensions[k];return '<div><div class="dimtitle"><span>'+esc(d.label)+'</span><strong>'+esc(d.score===null?'N/A':d.score+'/100')+'</strong></div><div class="dimbar"><div style="width:'+(d.score??0)+'%;background:'+d.color+'"></div></div></div>'}).join('');
const bar=keys.map(k=>{const d=r.dimensions[k];return '<div class="segment" title="'+esc(d.label+': '+(d.score===null?'N/A':d.score+'/100'))+'" style="width:'+d.weight+'%;background:'+(d.score===null?'#f1f1f2':'#f7f7f7')+'"><span class="filled" style="width:'+(d.score??0)+'%;background:'+d.color+'"></span></div>'}).join('');
const warnings=[...r.hard_failures,...keys.flatMap(k=>(r.dimensions[k].notes||[]).filter(n=>k==='grounding'||r.dimensions[k].score!==null&&r.dimensions[k].score<75).map(n=>r.dimensions[k].label+': '+n))];
return '<article class="card"><div class="cardhead"><div><div class="meta">'+esc(r.league.toUpperCase()+' · '+r.target_game_id)+'</div><div class="gate '+esc(r.gate)+'">'+esc(r.gate)+'</div></div><div class="score">'+esc(r.score===null?'N/A':r.score+'/100')+'</div></div><p class="story">'+esc(r.story)+'</p><div class="stack" aria-label="Weighted multi-aspect quality bar">'+bar+'</div><div class="dimensions">'+dims+'</div><details><summary>Rationale & data checks ('+warnings.length+')</summary>'+((warnings.length)?'<ul>'+warnings.map(n=>'<li class="dimnote">'+esc(n)+'</li>').join('')+'</ul>':'<p class="dimnote">No review flags.</p>')+'</details></article>'}).join('');
}
for(const id of ['search','league','gate','order'])document.getElementById(id).addEventListener(id==='search'?'input':'change',render);
render();
</script></body></html>""".replace("__DATA__", data), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic, offline Legendary Picks story grader")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("grade", help="Grade saved story JSONL records")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--html", type=Path, help="Write a pastel-bar dashboard")
    p.add_argument("--ledger", type=Path, help="Append versioned grades to a separate local JSONL ledger")
    render = sub.add_parser("render", help="Rebuild dashboard from an accumulating grade ledger")
    render.add_argument("--input", type=Path, required=True)
    render.add_argument("--html", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "grade":
        grades = grade_jsonl(args.input)
        args.output.write_text("".join(json.dumps(g, ensure_ascii=False, sort_keys=True) + "\n" for g in grades),
                               encoding="utf-8")
        if args.html:
            write_html(grades, args.html)
        appended = append_ledger(grades, args.ledger) if args.ledger else None
        print(json.dumps({"rubric_version": VERSION, "stories": len(grades), "ledger_appended": appended,
                          "statuses": {status: sum(g["gate"] == status for g in grades)
                                       for status in ("eligible", "review", "needs-audit", "blocked")},
                          "output": str(args.output), "html": str(args.html) if args.html else None}))
    elif args.command == "render":
        grades = read_grades(args.input)
        write_html(grades, args.html)
        print(json.dumps({"stories": len(grades), "html": str(args.html)}))


if __name__ == "__main__":
    main()
