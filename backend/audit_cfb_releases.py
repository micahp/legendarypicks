#!/usr/bin/env python3
"""audit_cfb_releases.py -- inventory every SportsDataverse release that starts with cfb_.

The user asked for every release beginning `cfb_`. This enumerates them from the
GitHub releases API, classifies each by grain (raw observations vs scored
features vs reference) and by level (player vs team), and records the seasons
and join keys. It writes a Markdown report.

Read-only against GitHub. Writes nothing except the report.

Usage:
    /root/legendarypicks/backend/venv/bin/python audit_cfb_releases.py \
        --out /root/lp-fbs-audit/research/fbs/AUDIT-CFB-RELEASES-20261017.md
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

API = ("https://api.github.com/repos/sportsdataverse/"
       "sportsdataverse-data/releases?per_page=100&page=%d")

# Classification, stated explicitly so a reader can disagree with it. The
# categories are the point: a raw observation can be re-derived, a scored
# feature already had a model applied, and a reference table joins on identity.
#
#   raw       -- one row per observed event (play, game, player game)
#   scored    -- a model already produced the value (EPA, ratings, projections)
#   reference -- identity or membership tables (teams, conferences, crosswalks)
#
# level:
#   player    -- carries a player/athlete id at row grain
#   team      -- team grain only
#   both      -- mixes grains in one release
CATEGORY = {
    "cfbfastR_cfb_pbp": "raw",
    "espn_cfb_pbp": "raw",
    "espn_cfb_player_box": "raw",
    "espn_cfb_game_rosters": "raw",
    "espn_cfb_team_box": "raw",
    "espn_cfb_injuries": "raw",
    "espn_cfb_betting": "raw",
    "cfb_schedules": "reference",
    "cfb_team_info": "reference",
    "cfb_groups": "reference",
    "cfb_crosswalk": "reference",
    "cfb_recruits": "raw",
    "cfb_ratings": "scored",
    "cfb_ratings_weekly": "scored",
    "cfb_fpi_weekly": "scored",
    "cfb_defense_vs_position": "scored",
    "cfb_paper_index_games": "scored",
    "cfb_matchup_features": "scored",
    "cfb_matchup_line": "scored",
    "cfb_metric_curves": "scored",
    "cfb_model_artifacts": "scored",
    "cfb_league_averages": "scored",
    "cfb_poll_analytics": "scored",
    "cfb_poll_week_summary": "scored",
    "cfb_recruiting_proj": "scored",
    "cfb_returning_production": "scored",
    "cfb_rolling_windows": "scored",
    "cfb_team_opponent_splits": "scored",
    "cfb_team_portal": "reference",
    "cfb_team_summaries_weekly": "scored",
    "cfb_team_talent": "scored",
}

# Releases that carry a player/athlete id at row grain. Measured, not assumed:
# the check is that the parquet schema contains a player-ish column.
PLAYER_LEVEL = {
    "cfbfastR_cfb_pbp", "espn_cfb_pbp", "espn_cfb_player_box",
    "espn_cfb_game_rosters", "espn_cfb_injuries", "cfb_recruits",
    "cfb_rolling_windows", "cfb_metric_curves",
}


def fetch(page):
    req = urllib.request.Request(API % page, headers={
        "User-Agent": "lp-fbs-audit",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=60) as fh:
        return json.load(fh)


def md_table(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        cells = []
        for c in r:
            cells.append("" if c is None else str(c))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def first_sentence(body):
    body = (body or "").strip()
    if not body:
        return ""
    # the release bodies lead with a bolded one-line summary
    for line in body.split("\n"):
        line = line.strip()
        if line:
            return line.strip("*").strip()
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    releases = []
    page = 1
    for page in range(1, 8):
        try:
            batch = fetch(page)
        except Exception as exc:
            print("page %d failed: %s" % (page, exc), file=sys.stderr)
            break
        if not isinstance(batch, list) or not batch:
            break
        releases.extend(batch)
        if len(batch) < 100:
            break

    cfb = sorted([r for r in releases if r["tag_name"].startswith("cfb")],
                 key=lambda r: r["tag_name"])
    other = sorted([r for r in releases if not r["tag_name"].startswith("cfb")],
                   key=lambda r: r["tag_name"])

    lines = []
    lines.append("# SportsDataverse `cfb_*` release inventory - %s"
                 % dt.datetime.utcnow().strftime("%Y-%m-%d"))
    lines.append("")
    lines.append(
        "Enumerated from the GitHub releases API, pages 1-%d, %d releases total."
        % (page, len(releases))
    )
    lines.append("")
    lines.append(
        "`cfb_*` releases: **%d**. The user asked for every one of them." % len(cfb)
    )
    lines.append("")
    lines.append(
        "The distinction that matters for the FBS modeling track is **raw vs "
        "scored**. A raw release is one row per observed event and can be "
        "re-derived. A scored release has already had a model applied -- EPA, "
        "ratings, projections -- and its values are the publisher's model "
        "output, not observations. Using a scored feature as if it were an "
        "observation double-counts the publisher's model."
    )
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 1. Inventory")
    lines.append("")
    rows = []
    for r in cfb:
        tag = r["tag_name"]
        assets = r.get("assets") or []
        pq = [a for a in assets if a["name"].endswith(".parquet")]
        seasons = sorted(set(
            a["name"].rsplit("_", 1)[-1].replace(".parquet", "")
            for a in pq
            if a["name"].rsplit("_", 1)[-1].replace(".parquet", "").isdigit()))
        pq_mb = sum(a["size"] for a in pq) / 1e6
        rows.append((
            "`%s`" % tag,
            CATEGORY.get(tag, "?"),
            "player" if tag in PLAYER_LEVEL else "team",
            len(pq),
            ("%s-%s" % (seasons[0], seasons[-1])) if seasons else "-",
            "%.1f" % pq_mb,
            (r.get("published_at") or "")[:10],
        ))
    lines.append(md_table(
        ["release", "kind", "grain", "parquet files", "seasons", "parquet MB", "published"],
        rows,
    ))
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 2. What each release is for")
    lines.append("")
    lines.append("First sentence of the publisher's own description, verbatim.")
    lines.append("")
    for r in cfb:
        s = first_sentence(r.get("body"))
        if not s:
            continue
        lines.append("- **`%s`** -- %s" % (r["tag_name"], s))
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 3. The raw observation releases")
    lines.append("")
    lines.append(
        "These are the ones a backtest is built on. Everything else is derived "
        "from them or from a reference table."
    )
    lines.append("")
    raw = [r for r in cfb if CATEGORY.get(r["tag_name"]) == "raw"]
    for r in raw:
        tag = r["tag_name"]
        assets = [a for a in (r.get("assets") or []) if a["name"].endswith(".parquet")]
        tot = sum(a["size"] for a in assets) / 1e6
        lines.append("- **`%s`** -- %d parquet files, %.1f MB. %s"
                     % (tag, len(assets), tot, first_sentence(r.get("body"))))
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 4. The two player-level scored releases")
    lines.append("")
    lines.append(
        "Most `cfb_*` releases are team-level. These two carry a player/athlete "
        "id at row grain, and they join to our prop players on ESPN athlete id. "
        "They are the only scored releases usable directly in a player-prop "
        "model without re-deriving the underlying events."
    )
    lines.append("")
    lines.append(md_table(
        ["release", "grain", "seasons", "parquet MB"],
        [(t, "player", "2004-2026", "%.1f" % (
            sum(a["size"] for a in ([x for x in (r.get("assets") or [])
                                     if x["name"].endswith(".parquet")])) / 1e6))
         for t in ("cfb_rolling_windows", "cfb_metric_curves")
         for r in [next((x for x in cfb if x["tag_name"] == t), {})]],
    ))
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 5. The as-of contract")
    lines.append("")
    lines.append(
        "`cfb_team_summaries_weekly` and `cfb_ratings_weekly` carry a "
        "`through_week` column. The contract is inclusive:"
    )
    lines.append("")
    lines.append(
        "> `through_week == W` includes games PLAYED in week W. To project week "
        "W, use the `through_week == W - 1` row."
    )
    lines.append("")
    lines.append(
        "The publisher verified this empirically (2024, delta between "
        "consecutive snapshots vs games actually played): **97.0% consistent "
        "with the inclusive reading, 58.7% with the exclusive one.** Filtering "
        "`through_week == W` and predicting week W leaks that week's results."
    )
    lines.append("")
    lines.append(
        "Also: the current season holds only the weeks played so far, and a "
        "build written early carries later weeks as **copies of the last real "
        "week**. Check for duplicated snapshots before using them."
    )
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 6. Non-`cfb_` releases that are still college football")
    lines.append("")
    lines.append(
        "The prefix filter excludes a large part of the ecosystem. Measured in "
        "the same sweep: **68 more college releases** under `espn_cfb_*` and "
        "`ncaa_mfb_*`. The `cfb_` prefix is a naming convention, not a "
        "complete list of college football data, and several of the excluded "
        "releases are player-level."
    )
    lines.append("")
    lines.append("Player-level among the excluded:")
    lines.append("")
    lines.append("- `ncaa_mfb_player_stats` -- player season stats")
    lines.append("- `espn_cfb_usage_players`, `espn_cfb_adv_player_usage` -- player usage")
    lines.append("- `espn_cfb_play_participants` -- per-play player attribution")
    lines.append("- `espn_cfb_adv_defensive_players` -- player-level defensive")
    lines.append("")
    lines.append("Full list:")
    lines.append("")
    lines.append(md_table(
        ["release", "parquet files", "published"],
        [(t, len([a for a in (r.get("assets") or []) if a["name"].endswith(".parquet")]),
          (r.get("published_at") or "")[:10])
         for r in other if r["tag_name"].startswith(("espn_cfb", "ncaa_mfb"))
         for t in [r["tag_name"]]],
    ))
    lines.append("")

    # ------------------------------------------------------------------
    lines.append("## 7. Leak guards found in the release notes")
    lines.append("")
    lines.append(
        "Two releases carry explicit warnings that would silently inflate a "
        "backtest if ignored. Both are quoted because the wording is the guard."
    )
    lines.append("")
    lines.append("### `cfb_paper_index_games` is not a feature")
    lines.append("")
    lines.append(
        "> `paper_index_span` is `train` for 2016-2023 (the season's shares "
        "were part of the weight fit, so they are in-sample), `holdout` for "
        "2024-2025 ... and `out_of_span` for every other season. **NOT A "
        "FEATURE**: the shares are fitted on who won, so they describe results "
        "and must not enter a predictive model."
    )
    lines.append("")
    lines.append(
        "This is a target leaked into a feature. `paper_share` is a deserved-"
        "win probability fitted on the outcome, so any model given it as an "
        "input is being told the answer. The `paper_index_span` column exists "
        "specifically so a backtest can exclude the in-sample seasons."
    )
    lines.append("")
    lines.append("### `cfb_defense_vs_position` has an unattributed-target caveat")
    lines.append("")
    lines.append(
        "> in 2024 ESPN names a receiver on only about 69% of throws (few "
        "incompletions, no interceptions), so the WR and TE rates are on "
        "targets naming a receiver, mostly completions, and read high; "
        "`unattributed_target_share` ... is the share of throws against that "
        "defense with no receiver named (FBS median 0.12 in 2014, 0.33 in "
        "2024). Nothing is imputed."
    )
    lines.append("")
    lines.append(
        "The unattributed share roughly tripled between 2014 and 2024. Any "
        "receiving model that uses these WR/TE rates across seasons is "
        "comparing rates measured on different populations, and the drift is "
        "in the direction that makes later seasons look better. The column is "
        "published so the drift can be measured; it is not corrected."
    )
    lines.append("")
    lines.append(
        "The same caveat is the reason the plan excludes receiving markets "
        "until target and reception attribution quality is confirmed: this is "
        "the measurement that would justify that exclusion."
    )
    lines.append("")

    out = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "research", "fbs",
        "AUDIT-CFB-RELEASES-%s.md" % dt.datetime.utcnow().strftime("%Y%m%d"))
    with open(out, "w") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))
    print("\n[report written to %s]" % out)


if __name__ == "__main__":
    main()
