"""Deterministic storyline candidates for one NBA game from the relationship graph.

Pure: no database, network, clock or model call. The same inputs always give the
same output, sorted by candidate id.

Inputs
  game               {"game_id", "date", "home", "away"} with team codes.
  graph              `sports_relationships.Graph`.
  roster             {team: [nba player id, ...]} as known at the cutoff.
  availability       {player id: status}; statuses below. A pregame call refuses
                     'played', because a result must never enter a pregame story.
  as_of              cutoff day (YYYY-MM-DD, not after the game day). Trades,
                     stints and meetings after it are ignored whatever the graph holds.
  prior_meetings     dates of earlier games between these two teams, or None if unknown.
  meetings_coverage_start  first day those meetings are complete from.
  appearance_history {"coverage_start": day, "games": {player id: [{"date","home"}]}}
                     of games the player appeared in, or None if unknown.

Kinds produced: former_team_matchup, reciprocal_trade_reunion,
first_team_meeting_after_trade, former_arena_return, first_return_to_former_arena,
former_teammates_now_opponents.

Kinds NOT produced here, because no source is loaded: playoff_series_rematch,
championship_or_franchise_milestone_connection, historical_rivalry,
first_actual_opponents_after_trade. The result lists them under `not_supported`.

Rules: a "first" needs a bounded history that provably covers the period; a player
named in a duel must be expected or confirmed to play; a scratched player's claims
move to `rejected` with a reason while a team-level trade angle stays.
"""
from __future__ import annotations

import datetime as dt

import sports_relationships as sr

STATUSES = {"scheduled", "expected_to_play", "active_confirmed", "played", "inactive", "unknown"}
PLAYING = {"expected_to_play", "active_confirmed"}
NOT_SUPPORTED = ["playoff_series_rematch", "championship_or_franchise_milestone_connection",
                 "historical_rivalry", "first_actual_opponents_after_trade"]


def _days(later: str, earlier: str):
    try:
        return (dt.date.fromisoformat(later) - dt.date.fromisoformat(earlier)).days
    except (TypeError, ValueError):
        return None


class _Run:
    def __init__(self, game, graph, roster, availability, as_of, prior_meetings,
                 meetings_coverage_start, appearance_history):
        for status in availability.values():
            if status == "played":
                raise ValueError("'played' cannot enter a pregame candidate run")
            if status not in STATUSES:
                raise ValueError("unknown availability status: %r" % (status,))
        if as_of > game["date"]:
            raise ValueError("as_of %s is after the game day %s" % (as_of, game["date"]))
        self.game, self.graph, self.roster = game, graph, roster
        self.avail, self.as_of = availability, as_of
        self.meetings, self.meetings_start = prior_meetings, meetings_coverage_start
        self.history = appearance_history
        self.candidates, self.rejected = [], []
        self.txn_of_evidence = {m.evidence_id: t for t in graph.transactions for m in t.movements}
        self.teams = sorted({game["home"], game["away"]})

    # ---- helpers ------------------------------------------------------
    def status(self, player):
        return self.avail.get(player, "unknown")

    def reject(self, cid, kind, reason):
        self.rejected.append({"candidate_id": cid, "kind": kind, "reason": reason})

    def add(self, cid, kind, players, event_id, scope, eligible, claims, evidence, features, reasons):
        self.candidates.append({
            "candidate_id": cid, "kind": kind,
            "entities": {"teams": list(self.teams), "players": sorted(players)},
            "event_id": event_id, "claim_scope": scope, "headline_eligible": bool(eligible),
            "as_of_utc": self.as_of, "claims": claims, "evidence_ids": sorted(set(evidence)),
            "coverage": {"transactions": "from " + str(self.graph.coverage_start),
                         "player_appearances": "partial" if self.history else "unknown"},
            "rank_features": features, "reasons": sorted(reasons)})

    def gate_player(self, player, cid, kind):
        """True if the player may be named. Scratched players are rejected."""
        if self.status(player) == "inactive":
            self.reject(cid, kind, "player_inactive")
            return False
        return True

    def reasons_for(self, players, extra=()):
        out = set(extra)
        if any(self.status(p) not in PLAYING for p in players):
            out.add("availability_unconfirmed")
        return out

    def former_stint(self, player, team):
        best = None
        for s in self.graph.stints(player):
            if s.team == team and s.end is not None and s.end <= self.as_of \
                    and (s.start is None or s.start <= self.as_of):
                if best is None or s.end > best.end:
                    best = s
        return best

    # ---- detectors ----------------------------------------------------
    def former_team_and_arena(self):
        home, away = self.game["home"], self.game["away"]
        for team, opp in ((home, away), (away, home)):
            for player in sorted(self.roster.get(team, [])):
                stint = self.former_stint(player, opp)
                if stint is None:
                    continue
                evidence = stint.start_evidence + stint.end_evidence
                txn = next((self.txn_of_evidence[e] for e in stint.end_evidence
                            if e in self.txn_of_evidence), None)
                claim = {"type": "former_team", "player": player, "current_team": team,
                         "former_team": opp, "left_on": stint.end,
                         "tenure_start": stint.start, "tenure_start_documented": stint.start_covered}
                feats = {"recency_days": _days(self.as_of, stint.end),
                         "multi_party_teams": len(txn.teams) if txn else None, "first_event": False}
                cid = "nba:%s:former_team_matchup:%s:%s" % (self.game["game_id"], player, opp)
                if self.gate_player(player, cid, "former_team_matchup"):
                    reasons = self.reasons_for([player], {"documented past tenure"})
                    self.add(cid, "former_team_matchup", [player], txn.id if txn else None,
                             "player_vs_former_team", self.status(player) in PLAYING,
                             [claim], evidence, feats, reasons)
                if opp == home:
                    self.arena_return(player, team, opp, stint, claim, evidence, feats, txn)

    def first_established(self, player, left_on):
        h = self.history
        if not h or h.get("coverage_start") is None or h["coverage_start"] > left_on:
            return False
        games = h.get("games", {}).get(player)
        if games is None:
            return False
        return not any(g["home"] == self.game["home"] and left_on < g["date"] < self.game["date"]
                       for g in games)

    def arena_return(self, player, team, former, stint, claim, evidence, feats, txn):
        first = self.first_established(player, stint.end)
        kind = "first_return_to_former_arena" if first else "former_arena_return"
        cid = "nba:%s:%s:%s:%s" % (self.game["game_id"], kind, player, former)
        if not self.gate_player(player, cid, kind):
            return
        claim = dict(claim, type=kind, arena_of=former, first_return=first)
        reasons = self.reasons_for([player])
        if not first:
            reasons.add("first_return_not_established")
        self.add(cid, kind, [player], txn.id if txn else None, "player_at_former_arena",
                 self.status(player) in PLAYING, [claim], evidence, dict(feats, first_event=first), reasons)

    def trades_between(self):
        a, b = self.teams
        for txn in self.graph.transactions:
            if txn.effective_date > self.as_of:
                continue
            direct = [m for m in txn.movements if {m.from_team, m.to_team} == {a, b}]
            if not direct:
                continue
            yield txn, direct

    def reciprocal(self):
        a, b = self.teams
        for txn, direct in self.trades_between():
            pair = sr.reciprocal_players(txn, a, b)
            if pair is None:
                continue
            players = [m.player_key for m in direct]
            claims = [{"type": "moved", "player": m.player_key, "from": m.from_team, "to": m.to_team,
                       "date": m.date} for m in sorted(direct, key=lambda m: (m.to_team, m.player_key))]
            claims.append({"type": "transaction", "teams_in_deal": sorted(txn.teams),
                           "effective_date": txn.effective_date})
            self.add("nba:%s:reciprocal_trade_reunion:%s" % (self.game["game_id"], txn.id),
                     "reciprocal_trade_reunion", players, txn.id, "scheduled_team_matchup", True,
                     claims, [m.evidence_id for m in direct],
                     {"recency_days": _days(self.as_of, txn.effective_date),
                      "multi_party_teams": len(txn.teams), "first_event": False},
                     {"team-level claim; availability not required"})

    def first_meeting(self):
        for txn, direct in self.trades_between():
            cid = "nba:%s:first_team_meeting_after_trade:%s" % (self.game["game_id"], txn.id)
            kind = "first_team_meeting_after_trade"
            if self.meetings is None or self.meetings_start is None:
                self.reject(cid, kind, "meeting_history_unknown")
            elif self.meetings_start > txn.effective_date:
                self.reject(cid, kind, "meeting_history_incomplete")
            elif any(txn.effective_date <= d < self.game["date"] for d in self.meetings):
                self.reject(cid, kind, "prior_meeting_exists")
            else:
                self.add(cid, kind, [], txn.id, "scheduled_team_matchup", True,
                         [{"type": "first_team_meeting", "trade_date": txn.effective_date,
                           "meetings_checked_from": self.meetings_start,
                           "moves": [{"player": m.player_key, "from": m.from_team, "to": m.to_team}
                                     for m in sorted(direct, key=lambda m: (m.to_team, m.player_key))]}],
                         [m.evidence_id for m in direct],
                         {"recency_days": _days(self.as_of, txn.effective_date),
                          "multi_party_teams": len(txn.teams), "first_event": True},
                         {"team meeting only; says nothing about who plays"})

    def teammates(self):
        home, away = self.game["home"], self.game["away"]
        for p1 in sorted(self.roster.get(home, [])):
            for p2 in sorted(self.roster.get(away, [])):
                shared = [s for s in self.graph.shared_tenure(p1, p2)
                          if s.end is not None and s.end <= self.as_of]
                if not shared:
                    continue
                cid = "nba:%s:former_teammates_now_opponents:%s:%s" % (self.game["game_id"], p1, p2)
                kind = "former_teammates_now_opponents"
                if not (self.gate_player(p1, cid, kind) and self.gate_player(p2, cid, kind)):
                    continue
                complete = any(s.complete for s in shared)
                claims = [{"type": "shared_tenure", "team": s.team, "start": s.start, "end": s.end,
                           "complete": s.complete} for s in shared]
                reasons = self.reasons_for([p1, p2], set() if complete else {"shared_tenure_incomplete"})
                days = [_days(s.end, s.start) for s in shared if s.start]
                self.add(cid, kind, [p1, p2], None, "player_vs_player",
                         complete and all(self.status(p) in PLAYING for p in (p1, p2)),
                         claims, [e for s in shared for e in s.evidence],
                         {"recency_days": _days(self.as_of, max(s.end for s in shared)),
                          "multi_party_teams": None, "first_event": False,
                          "shared_days": max(days) if days else None}, reasons)


def detect(game, graph, roster, availability, *, as_of, prior_meetings=None,
           meetings_coverage_start=None, appearance_history=None):
    run = _Run(game, graph, roster, availability, as_of, prior_meetings,
               meetings_coverage_start, appearance_history)
    run.former_team_and_arena()
    run.reciprocal()
    run.first_meeting()
    run.teammates()
    run.candidates.sort(key=lambda c: c["candidate_id"])
    run.rejected.sort(key=lambda r: (r["candidate_id"], r["reason"]))
    return {"game_id": game["game_id"], "as_of": as_of, "candidates": run.candidates,
            "rejected": run.rejected, "not_supported": list(NOT_SUPPORTED),
            "coverage": {"transactions_from": graph.coverage_start,
                         "appearances": "partial" if appearance_history else "unknown",
                         "meetings": "unknown" if prior_meetings is None else "from " + str(meetings_coverage_start)}}
