"""Editorial ranking of storyline candidates against the existing story angle.

Pure and deterministic. It ranks EDITORIAL importance only. It says nothing about
who wins, betting value or any "revenge advantage".

Score = importance x certainty x prior-use factor.
  importance  = weighted sum of strength, prominence, recency, novelty, stakes (0..1).
  certainty   = availability_certainty x evidence_quality (0..1 each).
  prior-use   = 1 - min(step x times the event was used lately, cap).

The numbers in RUBRIC are STARTING VALUES. They are not calibrated against blinded
human review yet. The version string says so. Every score is logged with its parts,
so a reviewer can see why an angle led or lost.

Existing angles come from `story_engine.select_story_angle`, which is a rule ladder
with no scores. Each existing kind is given a fixed score here so a relationship
angle can be compared with it. That table is an editorial choice, not a measurement.

One lead only. A candidate that shares the lead's event becomes a context card, not
a second headline. A candidate that is not headline eligible never leads.
"""
from __future__ import annotations

RUBRIC = {
    "version": "v0-unvalidated",
    "weights": {"strength": 0.15, "prominence": 0.20, "recency": 0.35, "novelty": 0.20, "stakes": 0.10},
    "half_life_days": 120,
    "strength_full_days": 1095,        # three years together or on a team counts as full strength
    "undocumented_strength": 0.2,      # tenure start not in the data: little credit
    "kind_prominence": {"reciprocal_trade_reunion": 0.7, "first_team_meeting_after_trade": 0.6,
                        "first_return_to_former_arena": 0.5, "former_arena_return": 0.5,
                        "former_team_matchup": 0.4, "former_teammates_now_opponents": 0.3},
    "multi_party_step": 0.1, "multi_party_cap": 0.3,
    "novelty_first": 1.0, "novelty_repeat": 0.15,
    "unconfirmed_availability": 0.4, "incomplete_evidence": 0.5,
    "prior_use_step": 0.25, "prior_use_cap": 0.75,
    "existing": {"undefeated": 0.85, "winless_last": 0.80, "top_four": 0.60, "rematch_performance": 0.55,
                 "streak_clash": 0.50, "winning_streak": 0.40, "losing_streak": 0.40, "records": 0.20},
    "max_secondary": 3, "max_context": 3,
}


def _strength(c, r):
    kind, claims = c["kind"], c.get("claims", [])
    if kind == "reciprocal_trade_reunion":
        return min(0.5 + 0.1 * len(c["entities"]["players"]), 1.0)
    if kind == "first_team_meeting_after_trade":
        return 0.5
    if kind == "former_teammates_now_opponents":
        days = c["rank_features"].get("shared_days")
        complete = any(x.get("complete") for x in claims)
        return min(days / r["strength_full_days"], 1.0) if days and complete else r["undocumented_strength"]
    claim = claims[0] if claims else {}
    start, left = claim.get("tenure_start"), claim.get("left_on")
    if claim.get("tenure_start_documented") and start and left:
        import datetime as dt
        days = (dt.date.fromisoformat(left) - dt.date.fromisoformat(start)).days
        return min(max(days, 0) / r["strength_full_days"], 1.0)
    return r["undocumented_strength"]


def _prominence(c, r):
    base = r["kind_prominence"].get(c["kind"], 0.0)
    teams = c["rank_features"].get("multi_party_teams")
    extra = min(r["multi_party_step"] * max((teams or 2) - 2, 0), r["multi_party_cap"])
    return min(base + extra, 1.0)


def _recency(c, r):
    days = c["rank_features"].get("recency_days")
    return 0.0 if days is None else 0.5 ** (max(days, 0) / r["half_life_days"])


def _evidence(c, r):
    for claim in c.get("claims", []):
        if claim.get("complete") is False or claim.get("tenure_start_documented") is False:
            return r["incomplete_evidence"]
    return 1.0


def _prior_key(c):
    return c["event_id"] if c.get("event_id") else c["kind"] + ":" + ",".join(c["entities"]["players"])


def _score_candidate(c, r, stakes, prior_use):
    features = {"strength": _strength(c, r), "prominence": _prominence(c, r), "recency": _recency(c, r),
                "novelty": r["novelty_first"] if c["rank_features"].get("first_event") else r["novelty_repeat"],
                "stakes": stakes}
    importance = sum(r["weights"][k] * features[k] for k in r["weights"])
    certainty = {"availability_certainty": r["unconfirmed_availability"]
                 if "availability_unconfirmed" in c.get("reasons", []) else 1.0,
                 "evidence_quality": _evidence(c, r)}
    used = prior_use.get(_prior_key(c), 0)
    factor = 1.0 - min(r["prior_use_step"] * used, r["prior_use_cap"])
    score = importance * certainty["availability_certainty"] * certainty["evidence_quality"] * factor
    return round(score, 9), features, dict(certainty, prior_use_factor=factor)


def rank(candidates, *, existing_angle=None, rejected=(), prior_use=None, stakes=0.0, rubric=RUBRIC,
         max_secondary=None, max_context=None):
    r, prior_use = rubric, prior_use or {}
    max_secondary = r["max_secondary"] if max_secondary is None else max_secondary
    max_context = r["max_context"] if max_context is None else max_context
    rows = []
    for c in candidates:
        score, features, mult = _score_candidate(c, r, stakes, prior_use)
        rows.append({"candidate_id": c["candidate_id"], "kind": c["kind"], "score": score,
                     "features": features, "multipliers": mult, "eligible": bool(c["headline_eligible"]),
                     "event_id": c.get("event_id"), "players": tuple(c["entities"]["players"]),
                     "recency_days": c["rank_features"].get("recency_days"), "existing": False})
    if existing_angle is not None:
        kind = existing_angle["kind"]
        if kind not in r["existing"]:
            raise ValueError("no editorial score for existing angle kind %r" % (kind,))
        rows.append({"candidate_id": "existing:" + kind, "kind": "existing:" + kind,
                     "score": r["existing"][kind], "features": {}, "multipliers": {}, "eligible": True,
                     "event_id": None, "players": (), "recency_days": None, "existing": True})

    def order(row):
        evidence = row["multipliers"].get("evidence_quality", 1.0)
        days = row["recency_days"] if row["recency_days"] is not None else 10 ** 9
        return (-row["score"], -evidence, days, row["candidate_id"])

    rows.sort(key=order)
    lead, seen, log = None, {}, []
    for row in rows:
        key = (row["event_id"], row["players"]) if row["event_id"] and not row["existing"] else None
        if key is not None and key in seen:
            row.update(role="omitted", reason="duplicate_of:" + seen[key])
        else:
            if key is not None:
                seen[key] = row["candidate_id"]
            if lead is None and row["eligible"]:
                lead = row
                row.update(role="lead", reason="highest eligible score")
            elif lead is not None and row["event_id"] and row["event_id"] == lead["event_id"]:
                row.update(role="context", reason="same_event_as_lead")
            elif not row["eligible"]:
                row.update(role="context", reason="not_headline_eligible")
            else:
                row.update(role="secondary", reason="eligible")
        log.append(row)
    counts = {"secondary": 0, "context": 0}
    caps = {"secondary": max_secondary, "context": max_context}
    for row in log:
        if row["role"] in counts:
            if counts[row["role"]] >= caps[row["role"]]:
                row.update(role="omitted", reason="below_%s_cap" % row["role"])
            else:
                counts[row["role"]] += 1
    for item in rejected:
        log.append({"candidate_id": item["candidate_id"], "kind": item["kind"], "score": None,
                    "features": {}, "multipliers": {}, "role": "rejected_by_detector",
                    "reason": item["reason"], "eligible": False, "event_id": None, "players": (),
                    "recency_days": None, "existing": False})
    clean = [{k: (list(v) if k == "players" else v) for k, v in row.items()
              if k not in ("recency_days", "existing")} for row in log]
    pick = lambda role: [e for e in clean if e["role"] == role]
    return {"rubric_version": r["version"], "lead": pick("lead")[0] if pick("lead") else None,
            "secondary": pick("secondary"), "context": pick("context"), "omitted": pick("omitted"),
            "log": clean}
