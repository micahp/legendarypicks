#!/usr/bin/env python3
"""nfl_player_projections_job.py -- write one week of player projections (Spec B sections 4 and 6).

For every unplayed regular-season game of the week, every RB/WR/TE who logged for the team in its last 3
games, has 3+ games earlier this season and is not Out or Doubtful on the final injury report: the
version 2 receiving line (targets, receptions, receiving yards, receiving TDs) with p10, median and p90,
beside Marcel-lite for the same player-game. Rushing is NOT published: v2 did not beat Marcel-lite on
carries (docs/RESULTS-player-projection-v2-2026-10-12.md).

Scenarios (Spec B 4.4). A Questionable teammate who is a candidate plays with probability P_PLAYS_QUESTIONABLE.
  if_plays  every Questionable teammate plays;  if_out  every Questionable teammate is out;
  base      the mixture of the two with weight P^k on if_plays, k = number of Questionable teammates.
Players with no Questionable teammate get identical rows in all three scenarios, written once as 'base'.
p_plays on a row is the player's own chance of playing (1.0, or P_PLAYS_QUESTIONABLE if he is Questionable);
the mean and quantiles are conditional on playing.

Quarterbacks (Spec B 4.5, gate passed 2026-10-13, docs/RESULTS-player-projection-v2-2026-10-12.md): one per team,
the passer the team is expected to start, PRE-REGISTERED 2026-10-13: the team's attempt leader in its most recent
game if he is not Out or Doubtful, otherwise the not-removed QB with the most attempts over the team's last 3
games. Attempts, completions, passing yards and passing TDs, base scenario only, conditional on him playing as the
passer; p_plays is his own designation's rate.

A game that already has a final score is skipped and counted: a projection written after the result is not
a projection. Every run appends rows under a new run_id; grading picks the last run before kickoff
(grade_nfl_player_projections.py), so reruns on Friday and Sunday refine and never overwrite.

Usage: LP_DB_PATH=... python3 nfl_player_projections_job.py --season 2026 --week 6 [--dry-run]
"""
import argparse
import contextlib
import datetime as dt
import json
import os
import sqlite3
import sys
import zlib

import nfl_player_projection_v2 as eng

MODEL_VERSION = "v2"
MARCEL_VERSION = "marcel-lite"
# Spec B 4.4, P(plays | final injury report designation). PRE-REGISTERED 2026-10-13 before it was run:
#   rate = played / (played known) over player_game_availability rows of REG games in 2024 and 2025 whose
#   report_status is the designation, offensive skill positions (QB, RB, FB, WR, TE) per `players`. Rows
#   with played NULL (no complete snap file) are counted and excluded. Frozen into P_PLAYS by hand from
#   `--fit-p-plays`. Out-of-sample check, reported and not a gate: the same rate fitted on 2024 alone, scored
#   by Brier on 2025 Questionable rows against the flat 0.70 used until now.
# Doubtful and Out stay removed from the engine's candidates (OUT_STATUSES); their rates are reported.
# Frozen 2026-10-13 from --fit-p-plays on the dev DB: Questionable 493 of 723 (57 unknown), Doubtful 0 of 84
# (18 unknown), Out 0 of 602 (138 unknown). 2024 alone 0.671, 2025 alone 0.694.
P_PLAYS = {"Questionable": 0.682, "Doubtful": 0.0, "Out": 0.0}
P_PLAYS_QUESTIONABLE = P_PLAYS["Questionable"]
SKILL_POSITIONS = ("QB", "RB", "FB", "WR", "TE")


def fit_p_plays(con, seasons=(2024, 2025), positions=SKILL_POSITIONS):
    """{designation: (played, known, unknown)} for REG games of `seasons`."""
    marks = ",".join("?" * len(seasons))
    pmarks = ",".join("?" * len(positions))
    out = {}
    for status, played, n in con.execute(
            "SELECT a.report_status, a.played, COUNT(*) FROM player_game_availability a "
            "JOIN nfl_schedule s ON s.game_id = a.game_id AND s.game_type = 'REG' "
            "JOIN players p ON p.id = a.player_id "
            "WHERE a.league = 'nfl' AND a.season IN (%s) AND p.position IN (%s) "
            "AND a.report_status IN ('Questionable', 'Doubtful', 'Out') "
            "GROUP BY 1, 2" % (marks, pmarks), list(seasons) + list(positions)):
        cur = out.setdefault(status, [0, 0, 0])
        if played is None:
            cur[2] += n
        else:
            cur[1] += n
            cur[0] += n if played == 1 else 0
    return {k: tuple(v) for k, v in out.items()}


def brier(rate, played_flags):
    return sum((rate - y) ** 2 for y in played_flags) / len(played_flags) if played_flags else None
RECV_POS = ("RB", "WR", "TE")
MIN_EARLIER_GAMES = 3
STATS = ("tgt", "rec", "rec_yds", "rec_td")
QB_STATS = ("att", "cmp", "pass_yds", "pass_td")


@contextlib.contextmanager
def extra_out(hist, key, pids):
    """Treat `pids` as Out for the game `key` while projecting, then restore the report."""
    original = hist.status.get(key)
    patched = dict(original or {})
    for pid in pids:
        patched[pid] = ("Out", None)
    hist.status[key] = patched
    try:
        yield
    finally:
        if original is None:
            hist.status.pop(key, None)
        else:
            hist.status[key] = original


def _draws(line, n, seed):
    tgt = line["tgt"]
    if tgt <= 0:
        return None
    c = line["rec"] / tgt
    ypr = line["rec_yds"] / line["rec"] if line["rec"] > 0 else 0.0
    return eng.simulate(tgt, c, ypr, line["rec_td"] / tgt, n=n, seed=seed)


def _stat_rows(line, draws):
    """{stat: (mean, median, p10, p90)} for the four receiving stats."""
    idx = {"rec": 0, "rec_yds": 1, "rec_td": 2, "tgt": 3}
    out = {}
    for stat in STATS:
        if draws:
            s = eng.summarize(draws, idx[stat])
            out[stat] = (line[stat], s["median"], s["p10"], s["p90"])
        else:
            out[stat] = (line[stat], None, None, None)
    return out


def expected_passer(hist, season, team, week, removed):
    """The QB the team is expected to start (rule in the module docstring), or None."""
    weeks = sorted(w for w in hist.team_weeks[(season, team)] if w < week)
    if not weeks:
        return None
    last = [r for r in hist.by_team[(season, team)][weeks[-1]] if r.pos == "QB" and r.att > 0]
    if last:
        lead = max(last, key=lambda r: (r.att, -r.pid))
        if lead.pid not in removed:
            return lead.pid
    totals = {}
    for w in weeks[-3:]:
        for r in hist.by_team[(season, team)][w]:
            if r.pos == "QB" and r.pid not in removed:
                totals[r.pid] = totals.get(r.pid, 0.0) + r.att
    if not totals:
        return None
    return max(totals, key=lambda pid: (totals[pid], -pid))


def _qb_entry(hist, season, week, gid, team, opp, pid, report, n_sims):
    line = eng.project_qb(hist, season, week, pid, team, opp, gid)
    if line is None or line["att"] <= 0:
        return None
    seed = zlib.crc32(("%s|%d|qb" % (gid, pid)).encode()) & 0xffff
    draws = eng.simulate_qb(line["att"], line["cmp"] / line["att"],
                            line["pass_yds"] / line["cmp"] if line["cmp"] > 0 else 0.0,
                            line["pass_td"] / line["att"], n=n_sims, seed=seed)
    idx = {"cmp": 0, "pass_yds": 1, "pass_td": 2, "att": 3}
    rows = {}
    for stat in QB_STATS:
        q = eng.summarize(draws, idx[stat])
        rows[stat] = (line[stat], q["median"], q["p10"], q["p90"])
    rep = report.get(pid, (None, None))[0]
    entry = {"game_id": gid, "player_id": pid, "team": team, "pos": "QB",
             "p_plays": P_PLAYS.get(rep, 1.0),
             "scenarios": {"base": rows}, "marcel": {}, "rules": {"att": "expected_passer"}}
    for stat in QB_STATS:
        m = eng.marcel(hist, season, week, pid, stat)
        if m is not None:
            entry["marcel"][stat] = m
    return entry


def project_week(con, season, week, n_sims=1000, hist=None):
    """Yield dicts (one per player-game) and a summary; no database writes."""
    hist = hist or eng.History.load(con, [season - 1, season])
    games = con.execute(
        "SELECT game_id, away_team, home_team, home_score, away_score FROM nfl_schedule "
        "WHERE season=? AND week=? AND game_type='REG' ORDER BY game_id", (season, week)).fetchall()
    if not games:
        raise ValueError("no REG games for %d week %d" % (season, week))
    out = []
    skipped_final = 0
    for gid, away, home, hs, aws in games:
        if hs is not None and aws is not None:
            skipped_final += 1
            continue
        for team, opp in ((away, home), (home, away)):
            key = (season, gid, team)
            report = hist.status.get(key, {})
            outs = {p for p, (rep, _) in report.items() if rep in eng.OUT_STATUSES}
            questionable = {p for p, (rep, _) in report.items() if rep == "Questionable"}
            cands = hist.candidates(season, team, week)
            for pid, pos in sorted(cands.items()):
                if pos not in RECV_POS or pid in outs:
                    continue
                if sum(1 for r in hist.by_player.get((season, pid), []) if r.week < week) < MIN_EARLIER_GAMES:
                    continue
                plays = eng.project(hist, season, week, pid, pos, team, opp, gid)
                if plays is None or "tgt" not in plays:
                    continue
                mates = sorted(q for q in questionable if q != pid and q in cands)
                entry = {"game_id": gid, "player_id": pid, "team": team, "pos": pos,
                         "p_plays": P_PLAYS_QUESTIONABLE if pid in questionable else 1.0,
                         "scenarios": {}, "marcel": {}}
                seed = zlib.crc32(("%s|%d" % (gid, pid)).encode()) & 0xffff
                d_plays = _draws(plays, n_sims, seed)
                if mates:
                    with extra_out(hist, key, mates):
                        gone = eng.project(hist, season, week, pid, pos, team, opp, gid)
                    p_all = P_PLAYS_QUESTIONABLE ** len(mates)
                    gone = gone if gone is not None and "tgt" in gone else plays
                    d_gone = _draws(gone, n_sims, seed + 1)
                    k = int(round(n_sims * p_all))
                    mix = ((d_plays or [])[:k] + (d_gone or [])[:n_sims - k]) or None
                    base = {s: p_all * plays[s] + (1 - p_all) * gone[s] for s in ("tgt", "rec", "rec_yds", "rec_td")}
                    entry["scenarios"] = {"base": _stat_rows(base, mix),
                                          "if_plays": _stat_rows(plays, d_plays),
                                          "if_out": _stat_rows(gone, d_gone)}
                    entry["questionable_teammates"] = mates
                else:
                    entry["scenarios"] = {"base": _stat_rows(plays, d_plays)}
                for stat in STATS:
                    m = eng.marcel(hist, season, week, pid, stat)
                    if m is not None:
                        entry["marcel"][stat] = m
                entry["rules"] = plays["_rules"]
                out.append(entry)
            qb = expected_passer(hist, season, team, week, outs)
            if qb is not None and sum(1 for r in hist.by_player.get((season, qb), []) if r.week < week) >= MIN_EARLIER_GAMES:
                qe = _qb_entry(hist, season, week, gid, team, opp, qb, report, n_sims)
                if qe is not None:
                    out.append(qe)
    return out, {"games": len(games), "skipped_final": skipped_final, "player_games": len(out)}


def write_week(con, season, week, entries, as_of, params):
    run_id = "pp-%d-w%02d-%s" % (season, week, as_of.replace(":", "").replace("-", "")[:15])
    con.execute(
        "INSERT INTO model_runs (run_id, league, season, week, model, model_version, started_at, "
        " params_json, status) VALUES (?,?,?,?,?,?,?,?,?)",
        (run_id, "nfl", season, week, "nfl-player-v2", MODEL_VERSION, as_of,
         json.dumps(params, sort_keys=True), "running"))
    rows = []
    for e in entries:
        for scenario, stats in e["scenarios"].items():
            for stat, (mean, median, p10, p90) in stats.items():
                rows.append((run_id, "nfl", season, week, e["game_id"], e["player_id"], e["team"], stat,
                             mean, median, p10, p90, scenario, MODEL_VERSION, "lp", e["p_plays"], as_of))
        for stat, mean in e["marcel"].items():
            rows.append((run_id, "nfl", season, week, e["game_id"], e["player_id"], e["team"], stat,
                         mean, None, None, None, "base", MARCEL_VERSION, "lp", e["p_plays"], as_of))
    con.executemany(
        "INSERT INTO player_projections (run_id, league, season, week, game_id, player_id, team, stat, mean, "
        "median, p10, p90, scenario, model_version, source, p_plays, as_of) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute("UPDATE model_runs SET status='ok', finished_at=? WHERE run_id=?",
                (dt.datetime.now(dt.timezone.utc).isoformat(), run_id))
    con.commit()
    return run_id, len(rows)


def next_week(con, season):
    row = con.execute(
        "SELECT MIN(week) FROM nfl_schedule WHERE season=? AND game_type='REG' AND home_score IS NULL",
        (season,)).fetchone()
    return row[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sims", type=int, default=1000)
    ap.add_argument("--fit-p-plays", action="store_true", help="print the fitted P(plays | designation); no writes")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect(path, timeout=30)
    if a.fit_p_plays:
        for label, seasons, pos in (("2024+2025 skill", (2024, 2025), SKILL_POSITIONS),
                                    ("2024 skill", (2024,), SKILL_POSITIONS),
                                    ("2025 skill", (2025,), SKILL_POSITIONS)):
            for status, (played, known, unknown) in sorted(fit_p_plays(con, seasons, pos).items()):
                print("%-16s %-12s played %4d of %4d known = %.3f   unknown %d" % (
                    label, status, played, known, played / known if known else float("nan"), unknown))
        rate24 = fit_p_plays(con, (2024,))["Questionable"]
        q25 = [row[0] for row in con.execute(
            "SELECT a.played FROM player_game_availability a JOIN nfl_schedule s ON s.game_id = a.game_id "
            "AND s.game_type = 'REG' JOIN players p ON p.id = a.player_id WHERE a.league = 'nfl' "
            "AND a.season = 2025 AND a.report_status = 'Questionable' AND a.played IS NOT NULL "
            "AND p.position IN (%s)" % ",".join("?" * len(SKILL_POSITIONS)), SKILL_POSITIONS)]
        r24 = rate24[0] / rate24[1]
        print("2025 Questionable n=%d: Brier with the 2024 rate %.3f = %.4f, with flat 0.70 = %.4f" % (
            len(q25), r24, brier(r24, q25), brier(0.70, q25)))
        return
    week = a.week or next_week(con, a.season)
    if week is None:
        raise SystemExit("no unplayed regular-season week in %d" % a.season)
    entries, summary = project_week(con, a.season, week, n_sims=a.sims)
    print("season %d week %d: %s" % (a.season, week, summary))
    if a.dry_run:
        for e in entries[:5]:
            print(e["game_id"], e["player_id"], e["pos"], {k: round(v[0], 2) for k, v in e["scenarios"]["base"].items()})
        return
    as_of = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    run_id, n = write_week(con, a.season, week, entries, as_of, {"sims": a.sims, "p_plays_questionable": P_PLAYS_QUESTIONABLE,
                                                                 "constants": eng.DEFAULTS, "dist": eng.DIST})
    print("wrote %d rows under %s" % (n, run_id))


if __name__ == "__main__":
    main()
