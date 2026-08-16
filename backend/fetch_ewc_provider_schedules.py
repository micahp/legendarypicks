#!/usr/bin/env python3
"""Operator-run, published-first EWC 2026 per-title schedule acquisition from the
verified machine-readable providers (PandaScore + Lichess official broadcasts).

Liquipedia ``action=parse`` is HTTP 429 rate-limited from this host (probe transcript
/tmp/ewc-rocket-probe-20260810T0029Z.log), so this module is the CURRENT acquisition path.
It publishes into the SAME snapshot store + manifest as the Liquipedia fetcher
(``fetch_ewc_title_schedules.py``), preserving the single-writer atomic publication
contract (tmp + ``os.replace`` per snapshot, then the manifest; a failed candidate never
becomes readable).

Verified provider map (2026-08-10, live endpoint evidence):
  - PandaScore feeds (12 supported: valorant, csgo, dota2, r6siege, lol, kog, ow, codmw,
    fifa, mlbb, pubg, rl). EWC 2026 main-event series per title in
    ``PANDASCORE_SERIES`` (slug suffix ``-esports-world-cup-2026`` + year 2026, or the EWC
    catalog event league for OW / FC / HoK / MLBB which publish under their event league
    names). Qualifier series are excluded.
  - Lichess officially broadcasts EWC 2026 Chess (group ``esports-world-cup-2026``); the
    Play-in tour's published rounds are the schedule (LCQ tours are qualifiers, excluded).
  - GRID Open Access covers only CS2 (56 main-event series, cross-checked against
    PandaScore serie 10846) and Dota 2 (no EWC 2026 series found in the June-Aug window).
  - Official EWC API is Bearer-gated (401); the official site is Cloudflare-403; start.gg
    and FACEIT require tokens not present on this host. Titles without a verified
    machine-readable provider stay honestly ``unavailable`` (never fabricated).

Usage (cwd=backend/, venv interpreter):
    venv/bin/python fetch_ewc_provider_schedules.py                    # all coverable titles
    venv/bin/python fetch_ewc_provider_schedules.py --slug rocket-league
    venv/bin/python fetch_ewc_provider_schedules.py --dry-run
    venv/bin/python fetch_ewc_provider_schedules.py --refresh-final    # override frozen final
"""

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

import fetch_ewc_title_schedules as store

API_UA = ("LegendaryPicks/1.0 (EWC title schedule ingest; "
          "contact via github.com/legendarypicks)")
_PS_BASE = "https://api.pandascore.co"
_LICHESS_BASE = "https://lichess.org"

_OPENER = urllib.request.build_opener()


def _operator_log(message):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("[%s] %s" % (stamp, message), flush=True)


def _iso_to_ms(s):
    if not s:
        return None
    try:
        dt = _dt.datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _iso_date(s):
    ms = _iso_to_ms(s)
    if ms is None:
        return None
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc).strftime("%Y-%m-%d")


def _ps_key():
    return (os.environ.get("PANDASCORE_API_KEY") or "").strip()


def _ps_get(path, tries=4):
    """GET a PandaScore endpoint with bounded retries (no invented data on failure)."""
    key = _ps_key()
    if not key:
        raise store.ScheduleSourceError("PANDASCORE_API_KEY missing")
    for attempt in range(tries):
        req = urllib.request.Request(_PS_BASE + path, headers={
            "Authorization": "Bearer %s" % key, "Accept": "application/json",
            "User-Agent": API_UA})
        try:
            with _OPENER.open(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = 25 * (attempt + 1)
                _operator_log("pandascore 429 on %s; waiting %ds" % (path, wait))
                time.sleep(wait)
                continue
            raise store.ScheduleSourceError(
                "pandascore HTTP %s on %s" % (exc.code, path)) from exc
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            if attempt + 1 >= tries:
                raise store.ScheduleSourceError(
                    "pandascore transport failure on %s: %s" % (path, type(exc).__name__)) from exc
            time.sleep(10)
    raise store.ScheduleSourceError("pandascore request failed after retries: %s" % path)


def _fetch_serie_matches(serie):
    """Full population of a serie's matches (paginated; deterministic unique ids)."""
    page = 1
    out = []
    while True:
        data = _ps_get("/series/%d/matches?per_page=100&page=%d" % (serie["id"], page))
        if not isinstance(data, list):
            raise store.ScheduleSourceError(
                "unexpected pandascore response for serie %d" % serie["id"])
        out.extend(data)
        if len(data) < 100:
            break
        page += 1
        if page > 25:
            raise store.ScheduleSourceError(
                "pagination runaway for serie %d (>2500 matches)" % serie["id"])
    return out


def _ps_match_row(match):
    """Map a PandaScore match object onto the snapshot row contract (no invented values)."""
    opponents = match.get("opponents") or []
    sides = []
    for idx in (0, 1):
        op = (opponents[idx].get("opponent") or {}) if idx < len(opponents) else {}
        name = op.get("name")
        sides.append({
            "team": name,
            "slug": op.get("slug"),
            "pending": not name,
        })
    # Map results by team_id (PandaScore order is not guaranteed to match opponents).
    # Scores are published facts ONLY for finished matches; a not_started/running row
    # may carry a placeholder 0 in `results` (verified live: not_started match with
    # score 0 for its one known opponent) — never publish an invented zero.
    status = (match.get("status") or "").lower()
    finished = status == "finished"
    canceled = status == "canceled"
    if status not in ("not_started", "running", "finished", "canceled", "postponed"):
        raise store.ScheduleSourceError(
            "unsupported pandascore match status %r (match %s)" % (status, match.get("id")))
    score_by_team = {}
    if finished:
        for r in match.get("results") or []:
            tid = r.get("team_id")
            if tid is not None and r.get("score") is not None:
                score_by_team[tid] = r["score"]
    scores = []
    for idx in (0, 1):
        tid = None
        if idx < len(opponents):
            tid = (opponents[idx].get("opponent") or {}).get("id")
        scores.append(score_by_team.get(tid) if tid is not None else None)
    begin = match.get("begin_at")
    ms = _iso_to_ms(begin)
    return {
        "sourceMatchId": "pandascore:%s" % match.get("id"),
        "stage": (match.get("tournament") or {}).get("name"),
        "date": _iso_date(begin),
        "startTime": ms,
        "teamA": sides[0]["team"],
        "teamASlug": sides[0]["slug"],
        "teamAPending": sides[0]["pending"],
        "teamB": sides[1]["team"],
        "teamBSlug": sides[1]["slug"],
        "teamBPending": sides[1]["pending"],
        "scoreA": scores[0],
        "scoreB": scores[1],
        "finished": finished,
        "canceled": canceled,
    }


def build_pandascore_snapshot(slug, rows, series, fetched_at):
    """Build a validated snapshot for a PandaScore title.

    Lifecycle is derived from the PUBLISHED population (never from the current date):
      - final   : every row finished, every participant resolved, serie over
      - active  : any finished row exists (event in progress)
      - upcoming: no finished rows
    A completed event with an unresolved participant row is NOT final (honest).
    """
    revisions = [s["id"] for s in series]
    if not rows:
        raise store.ScheduleSourceError("no published matches for %s" % slug)
    resolved = [r for r in rows if r["finished"] or r["canceled"]]
    all_resolved = len(resolved) == len(rows)
    any_finished = any(r["finished"] for r in rows)
    all_resolved_participants = all(
        not (r["teamAPending"] or r["teamBPending"]) for r in resolved)
    # Serie end is a source-backed completion signal only when every serie ended.
    all_series_ended = all(s.get("endAtMs") and s["endAtMs"] < int(time.time() * 1000)
                           for s in series)
    lifecycle = "final" if (all_resolved and all_resolved_participants and all_series_ended) else (
        "active" if any_finished else "upcoming")
    finality = None
    if lifecycle == "final":
        finality = {
            "allMatchesResolved": all_resolved,
            "participantsComplete": all_resolved_participants,
            "sourceRevisionRecorded": bool(revisions),
        }
    return store.build_snapshot(
        slug, rows, revisions, fetched_at,
        lifecycle=lifecycle, finality=finality, provider="pandascore")


# ---------------------------------------------------------------------------
# Lichess official EWC Chess broadcast
# ---------------------------------------------------------------------------
def _lichess_get(path):
    req = urllib.request.Request(_LICHESS_BASE + path, headers={
        "Accept": "application/json", "User-Agent": API_UA})
    try:
        with _OPENER.open(req, timeout=45) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise store.ScheduleSourceError("lichess HTTP %s on %s" % (exc.code, path)) from exc
    except (urllib.error.URLError, ConnectionError, OSError) as exc:
        raise store.ScheduleSourceError(
            "lichess transport failure on %s: %s" % (path, type(exc).__name__)) from exc


def build_lichess_rows():
    """Rows from the EWC Chess Play-in tour's published rounds.

    A round with no published games is one honest schedule slot (pending participants);
    a round with published games yields one row per game with resolved players + result.
    """
    rows = []
    for tour in store.LICHESS_CHESS["tours"]:
        doc = _lichess_get("/api/broadcast/%s" % tour["id"])
        rounds = (doc.get("rounds") or [])
        if not rounds:
            raise store.ScheduleSourceError(
                "lichess tour %s published no rounds" % tour["id"])
        for rnd in rounds:
            ms = rnd.get("startsAt")
            rnd_id = rnd.get("id")
            round_name = rnd.get("name")
            iso_date = None
            if isinstance(ms, int):
                iso_date = _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc) \
                    .strftime("%Y-%m-%d")
            games = []
            try:
                rd = _lichess_get("/api/broadcast/%s/%s/%s" % (
                    tour["slug"], rnd.get("slug") or "-", rnd_id))
                games = rd.get("games") or []
            except store.ScheduleSourceError:
                games = []
            stage = ("%s · %s" % (tour["name"], round_name)
                     if round_name else tour["name"])
            if not games:
                rows.append({
                    "sourceMatchId": "lichess:%s" % rnd_id,
                    "stage": stage,
                    "date": iso_date,
                    "startTime": ms,
                    "teamA": None, "teamASlug": None, "teamAPending": True,
                    "teamB": None, "teamBSlug": None, "teamBPending": True,
                    "scoreA": None, "scoreB": None, "finished": False,
                })
                continue
            for game in games:
                players = game.get("players") or []
                white = players[0] if players else {}
                black = players[1] if len(players) > 1 else {}
                status = (game.get("status") or "").strip()
                finished = status in ("1-0", "0-1", "1/2-1/2")
                score_a = score_b = None
                if status == "1-0":
                    score_a, score_b = 1, 0
                elif status == "0-1":
                    score_a, score_b = 0, 1
                # "1/2-1/2" is a draw: a finished game with no decisive score; our
                # contract has no float half-points, so both scores stay null (honest
                # absence, never a fabricated 0-0).
                name_a = white.get("name")
                name_b = black.get("name")
                rows.append({
                    "sourceMatchId": "lichess:%s" % (game.get("id") or rnd_id),
                    "stage": stage,
                    "date": iso_date,
                    "startTime": ms,
                    "teamA": name_a, "teamASlug": None,
                    "teamAPending": not name_a,
                    "teamB": name_b, "teamBSlug": None,
                    "teamBPending": not name_b,
                    "scoreA": score_a, "scoreB": score_b,
                    "finished": finished,
                })
    if not rows:
        raise store.ScheduleSourceError("lichess chess published no rows")
    return rows


def build_lichess_snapshot(fetched_at):
    """Validated chess snapshot (provider=lichess, lifecycle derived from rows)."""
    rows = build_lichess_rows()
    revisions = [t["id"] for t in store.LICHESS_CHESS["tours"]]
    any_finished = any(r["finished"] for r in rows)
    lifecycle = "active" if any_finished else "upcoming"
    return store.build_snapshot(
        "chess", rows, revisions, fetched_at,
        lifecycle=lifecycle, finality=None, provider="lichess")


# ---------------------------------------------------------------------------
# Operator CLI (lifecycle-aware, atomic, nonzero exit on any failure)
# ---------------------------------------------------------------------------
def _serie_with_bounds(serie):
    doc = _ps_get("/series/%d" % serie["id"])
    serie = dict(serie)
    serie["endAtMs"] = _iso_to_ms((doc or {}).get("end_at"))
    return serie


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="only acquire this title slug")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch + validate, print summary, no writes")
    ap.add_argument("--refresh-final", action="store_true",
                    help="explicitly allow a frozen final title to be acquired again")
    args = ap.parse_args(argv)

    pandascore_slugs = sorted(store.PANDASCORE_SERIES)
    if args.slug:
        if args.slug not in store.PANDASCORE_SERIES and args.slug != "chess":
            ap.error("unknown coverable EWC title slug: %s" % args.slug)
        if args.slug == "chess":
            pandascore_slugs = []
        else:
            pandascore_slugs = [args.slug]

    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    summary = {}
    failures = 0

    for slug in pandascore_slugs:
        try:
            manifest = store.read_manifest()
            prior = ((manifest or {}).get("titles") or {}).get(slug) or {}
            if prior.get("lifecycle") == "final" and not args.refresh_final:
                summary[slug] = {"status": "skipped-final"}
                print("SKIPPED   %-32s frozen final snapshot" % slug)
                continue
            series = [_serie_with_bounds(s) for s in store.PANDASCORE_SERIES[slug]]
            rows = []
            for s in series:
                matches = _fetch_serie_matches(s)
                if not matches:
                    raise store.ScheduleSourceError(
                        "serie %d published no matches" % s["id"])
                rows.extend(_ps_match_row(m) for m in matches)
            snapshot = build_pandascore_snapshot(slug, rows, series, fetched_at)
            if args.dry_run:
                print("[dry-run] %-32s series=%s rows=%d lifecycle=%s" % (
                    slug, [s["id"] for s in series], len(rows), snapshot["lifecycle"]))
                summary[slug] = {"status": "dry-run", "rows": len(rows)}
                continue
            path = store.publish(slug, snapshot)
            print("published %-32s -> %s (series=%s rows=%d lifecycle=%s dates=%s..%s)" % (
                slug, path, [s["id"] for s in series], len(rows),
                snapshot["lifecycle"], snapshot["schedule"]["firstDate"],
                snapshot["schedule"]["lastDate"]))
            summary[slug] = {"status": "published", "rows": len(rows),
                             "lifecycle": snapshot["lifecycle"]}
        except Exception as exc:  # noqa: BLE001 — operator-facing
            failures += 1
            summary[slug] = {"error": str(exc)[:160]}
            print("FAILED    %-32s %s" % (slug, exc))

    if not args.slug or args.slug == "chess":
        try:
            manifest = store.read_manifest()
            prior = ((manifest or {}).get("titles") or {}).get("chess") or {}
            if prior.get("lifecycle") == "final" and not args.refresh_final:
                summary["chess"] = {"status": "skipped-final"}
                print("SKIPPED   %-32s frozen final snapshot" % "chess")
            else:
                snapshot = build_lichess_snapshot(fetched_at)
                if args.dry_run:
                    print("[dry-run] %-32s rows=%d lifecycle=%s" % (
                        "chess", len(snapshot["matches"]), snapshot["lifecycle"]))
                    summary["chess"] = {"status": "dry-run", "rows": len(snapshot["matches"])}
                else:
                    path = store.publish("chess", snapshot)
                    print("published %-32s -> %s (rows=%d lifecycle=%s dates=%s..%s)" % (
                        "chess", path, len(snapshot["matches"]), snapshot["lifecycle"],
                        snapshot["schedule"]["firstDate"], snapshot["schedule"]["lastDate"]))
                    summary["chess"] = {"status": "published",
                                        "rows": len(snapshot["matches"]),
                                        "lifecycle": snapshot["lifecycle"]}
        except Exception as exc:  # noqa: BLE001 — operator-facing
            failures += 1
            summary["chess"] = {"error": str(exc)[:160]}
            print("FAILED    %-32s %s" % ("chess", exc))

    succeeded = sum(1 for item in summary.values() if "error" not in item)
    print("summary: requested=%d succeeded-or-skipped=%d failed=%d" % (
        len(summary), succeeded, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
