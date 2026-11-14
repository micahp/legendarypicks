"""Adapter: add relationship angles to a pregame story without changing story_engine.

`generate_story_with_relationships(bundle, None)` returns exactly what
`story_engine.generate_story(bundle)` returns. With inputs it also detects, ranks,
renders and audits relationship candidates. The relationship copy replaces the lead
only when all of these hold:

* the existing angle has an editorial score in the rubric (`storyline_ranking`),
* a relationship candidate outranks it and is headline eligible,
* the finished text passes `storyline_audit`.

Anything else keeps the existing story. An audit failure keeps the existing story and
is recorded in the manifest; `strict=True` raises instead. Pure apart from the
read-only collector `collect_relationship_inputs`. No network, no model, no write.

Cutoff rule: movement rows carry an effective DATE only, so the detector is given the
day before the cutoff day. A trade dated on the cutoff day is not used.
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
from pathlib import Path

import sports_relationships as sr
import storyline_audit as au
import storyline_candidates as sc
import storyline_ranking as rk
import storyline_templates as tp
import story_engine as se


class RelationshipDataMissing(RuntimeError):
    """The data needed to say anything about relationships is not there."""


def _cutoff_day(as_of) -> str:
    return (se._utc(as_of).date() - dt.timedelta(days=1)).isoformat()


def collect_relationship_inputs(db_path, game, *, as_of):
    """Read-only. Rosters come from a published snapshot captured at or before the cutoff."""
    if game["league"] != "nba":
        raise RelationshipDataMissing("relationships are built for nba only")
    path = Path(db_path).resolve()
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "nba_player_movement" not in have:
            raise RelationshipDataMissing("table nba_player_movement is missing")
        rows = [dict(r) for r in con.execute("SELECT * FROM nba_player_movement ORDER BY id")]
        if not rows:
            raise RelationshipDataMissing("nba_player_movement is empty")
        cutoff = se._utc(as_of)
        snaps = [r for r in con.execute(
            "SELECT id, captured_at, source FROM roster_snapshots WHERE league='nba' "
            "AND source LIKE 'nba.com%' ORDER BY captured_at DESC")
            if se._utc(r["captured_at"]) <= cutoff]
        if not snaps:
            raise RelationshipDataMissing("no nba.com roster snapshot captured at or before %s" % as_of)
        snap = snaps[0]
        roster, names = {}, {}
        for team in (game["away"], game["home"]):
            members = con.execute(
                "SELECT source_player_key, display_name FROM roster_memberships "
                "WHERE snapshot_id=? AND team=? AND roster_status='active'", (snap["id"], team)).fetchall()
            if not members:
                raise RelationshipDataMissing("snapshot %s has no active players for %s" % (snap["id"], team))
            roster[team] = sorted(str(m["source_player_key"]) for m in members)
            names.update({str(m["source_player_key"]): m["display_name"] for m in members})
        day = _cutoff_day(as_of)
        meetings = [r[0] for r in con.execute(
            "SELECT game_date FROM team_game_results WHERE league='nba' AND team=? AND opponent=? "
            "AND game_date<=? AND game_id<>? ORDER BY game_date",
            (game["away"], game["home"], day, str(game.get("game_id") or "")))]
        start = con.execute("SELECT MIN(game_date) FROM team_game_results WHERE league='nba' AND team=?",
                            (game["away"],)).fetchone()[0]
    finally:
        con.close()
    return {"rows": rows, "roster": roster, "names": names, "availability": {},
            "prior_meetings": meetings, "meetings_coverage_start": start,
            "roster_snapshot": {"id": snap["id"], "source": snap["source"], "captured_at": snap["captured_at"]},
            "notes": ["availability source: none, every player is 'unknown'",
                      "appearance history: not loaded, no 'first' claim about a player"]}


def _sentences(text):
    return [s for s in re.split(r"(?<=\.)\s+", text.strip()) if s]


def _compose(rendered):
    parts = [rendered["headline"]] + _sentences(rendered["body"])
    return " ".join(parts[:3])


def generate_story_with_relationships(bundle, inputs, *, strict=False, prior_use=None, stakes=0.0,
                                      rubric=rk.RUBRIC):
    base = se.generate_story(bundle)
    if inputs is None:
        return base
    game = {"game_id": str(bundle.get("game_id") or ""), "date": se._utc(bundle["start_utc"]).date().isoformat(),
            "home": bundle["home"], "away": bundle["away"]}
    day = _cutoff_day(bundle["as_of"])
    graph = sr.build_graph(inputs["rows"], as_of=day)
    det = sc.detect(game, graph, inputs["roster"], inputs.get("availability", {}), as_of=day,
                    prior_meetings=inputs.get("prior_meetings"),
                    meetings_coverage_start=inputs.get("meetings_coverage_start"),
                    appearance_history=inputs.get("appearance_history"))
    base_kind = base["angle"]["kind"]
    rankable = base_kind in rubric["existing"]
    ranked = rk.rank(det["candidates"], existing_angle=base["angle"] if rankable else None,
                     rejected=det["rejected"], prior_use=prior_use, stakes=stakes, rubric=rubric)
    info = {"rubric_version": ranked["rubric_version"], "status": "kept_existing_lead", "as_of_day": day,
            "base_angle": base["angle"], "coverage": det["coverage"], "not_supported": det["not_supported"],
            "lead": ranked["lead"], "secondary": ranked["secondary"], "context": ranked["context"],
            "omitted": ranked["omitted"], "log": ranked["log"], "notes": list(inputs.get("notes", [])),
            "roster_snapshot": inputs.get("roster_snapshot")}
    out = {"story": base["story"], "angle": base["angle"],
           "manifest": dict(base["manifest"], relationships=info)}
    lead = ranked["lead"]
    if not rankable:
        info["status"] = "base_angle_not_ranked"
        return out
    if lead is None or lead["kind"].startswith("existing:"):
        return out
    cand = next(c for c in det["candidates"] if c["candidate_id"] == lead["candidate_id"])
    rendered = tp.render(cand, inputs["names"])
    story = _compose(rendered)
    report = au.audit(cand, story, graph, as_of=day, names=inputs["names"])
    info["audit"] = report
    if not report["ok"]:
        info["status"] = "audit_failed"
        if strict:
            raise ValueError("relationship copy failed audit: %s" % report["failures"])
        return out
    if se.RESEARCH_JARGON.search(story) or not 1 <= len(_sentences(story)) <= 3:
        raise ValueError("relationship copy broke the story contract")
    info["status"] = "relationship_lead"
    fact = {"id": cand["candidate_id"], "kind": "relationship", "description": story,
            "evidence_ids": cand["evidence_ids"], "claims": cand["claims"]}
    displaced = [{"fact_id": f["id"], "reason": "displaced by relationship lead"}
                 for f in base["manifest"]["selected_facts"]]
    out["story"] = story
    out["angle"] = {"kind": "relationship:" + cand["kind"], "candidate_id": cand["candidate_id"],
                    "teams": [bundle["away"], bundle["home"]], "lead_team": None}
    out["manifest"] = {"selected_facts": [fact],
                       "omitted_facts": list(base["manifest"]["omitted_facts"]) + displaced,
                       "relationships": info}
    return out
