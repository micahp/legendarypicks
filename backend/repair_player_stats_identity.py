#!/usr/bin/env python3
"""Clear the data conditions that block the canonical `player_stats` key.

Why this exists
---------------
`player_stats` is still keyed `UNIQUE(name_norm, league, season, stat_type)` --
by the NAME. When the spine resolves `mlbam_680869` into `zack gelof` the key
changes underneath the row, so the next ingest cannot update it: it inserts, and
the stale snapshot survives forever beside its twin under the same `player_id`.
On prod 2026-08-03 that put Zack Gelof at 54 games next to his current 66, and
`/api/mlb/leaders` failed closed on it (503, "duplicate ownership"), which took
the whole MLB Stats tab down.

`migrate_player_stats.py` is the fix -- it rebuilds the table on
`UNIQUE(player_id, league, season, stat_type)` with `player_id NOT NULL`, after
which the stranding is not a bug that has been fixed but a row the schema cannot
hold. That migration is deliberately non-repairing: it reports the data
conditions and refuses to choose among them. This script is where the choosing
happens, one named rule at a time, so each deletion is a claim someone can read
and argue with rather than a hand-typed DELETE nobody can reconstruct.

Measured on prod 2026-08-03, `--check` reported five blocked conditions:

    null_canonical_fields=23  display_name_mismatches=78  invalid_stat_types=1262
    unowned_sources=1330      duplicate_canonical_keys=39

On prod, R1 and R2 alone clear all five: every `display_name_mismatch` and every
`duplicate_canonical_key` there lives on a row one of them removes, which is the
evidence that those two were never independent problems. Dev is the reason R5
and R6 exist anyway -- it carries 157 duplicate owners of a shape prod does not
have, and a repair that only fixes the database in front of it is a repair that
gets rewritten the next time.

The rules
---------
R1 `non_canonical_stat_type` -- the row's `stat_type` is not the league's only
   canonical type (`nfl/weekly`, `nba/batting`, `nhl/batting`). Every reader
   goes through `league_stats.canonical_population_sql`, which pins the
   canonical type, so no query can reach these rows. Their writers are gone:
   `derive_player_stats.py` raises on every call, and nothing writes
   `stat_type='weekly'` to this table any more.

R2 `non_owning_source` -- `source_owns_stats` says this source does not own
   (league, type, season). Same reasoning: the canonical predicate pins the
   owner, so the rows are unreachable. On prod these are 68 `mlb_statsapi`
   batting rows, and they are worse than dead -- one of them files Henry Bolte's
   season under Eiberson Castellano's `player_id`.

R3 `unowned_identity` -- `player_id IS NULL`. A stats row with no player is not
   a display row; it is an unresolved identity, and `unresolved_players` is
   where those already live. Each is queued there before it is deleted, because
   a missing row should read as `unknown`, not as `never happened`. These are
   the 21 fringe NHL skaters (CJ Suess, 2 games) that 503'd an entire league by
   collapsing into one NULL group under `GROUP BY player_id`.

R4 `legacy_season_vocabulary` -- an NHL row under nhle.com's 8-digit span
   (`20252026`) when the rest of the database keys that season the ESPN way
   (`2026`). This is the same defect as the name key wearing a different hat:
   `publish_player_stats` deletes by the NORMALIZED season, so it can never
   reach an 8-digit row, and `league_stats` resolves the live season with
   `MAX(season)` -- where `20252026` beats `2026`. Prod was serving 894 NHL rows
   that no ingest could refresh. A legacy row whose player already has a row
   under the ESPN key is deleted; one whose player does not (84 of them --
   Jonathan Toews' 82 games, James van Riemsdyk's 72) is re-keyed, never
   dropped.

R5 `duplicate_owner` -- what is left after R1-R4 and one player still owns two
   rows under the canonical key. The survivor is the row the CURRENT writer
   would produce: `name_norm == normalize_player_name(players.name)`. Two shapes
   made these, and that rule settles both -- a placeholder beside its resolution
   (`mlbam_669911` next to `michael toglia`) and two spellings of one normalizer
   (`h ctor rodr guez` next to `hector rodriguez`, from an NFKD/ascii-fold that
   changed underneath rows already written). A group where no row is what the
   writer would produce is a third shape nobody has measured, and it refuses.

R6 `stale_display_name` -- `player_name` drifted from `players.name`. This one
   repairs instead of deleting: the column is a denormalized copy that
   `publish_player_stats` rewrites on every publish, so the source of truth is
   not in question.

What it refuses to do
---------------------
Before writing anything it records every `(league, player_id)` reachable by the
canonical predicate at each league's live season, and it re-checks that set
afterwards. If a single identifiable player would stop being served, the
transaction rolls back. "These rows are unreachable" is a claim about the
readers, and this is the measurement that holds it to account.

    venv/bin/python repair_player_stats_identity.py --db data/picks.db --dry-run
    venv/bin/python repair_player_stats_identity.py --db data/picks.db --apply
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter

from league_stats import (
    LeagueStatContractError,
    canonical_population_sql,
    canonical_stat_type,
    normalize_player_name,
    queue_unresolved_player,
    source_owns_stats,
)
from season_keys import normalize_season

LEAGUES = ("mlb", "nba", "nfl", "nhl")
STAT_TYPES = {"mlb": ("batting", "pitching"), "nba": (None,), "nfl": (None,), "nhl": (None,)}

# nhle.com is the only publisher in this table that speaks a season vocabulary
# other than ESPN's. Naming it here keeps R4 from silently claiming authority
# over a league whose key convention nobody has measured.
LEGACY_SEASON_SOURCES = {("nhl", "nhle.com")}


def served_population(con: sqlite3.Connection) -> set[tuple[str, str, int]]:
    """Every `(league, stat_type, player_id)` a reader can currently reach.

    The live season is resolved the same way `league_stats` resolves it --
    `MAX(season)` over the canonical predicate -- so this measures what the API
    would return, not what the table happens to hold.
    """
    seen: set[tuple[str, str, int]] = set()
    for league in LEAGUES:
        for stat_type in STAT_TYPES[league]:
            try:
                clause, params = canonical_population_sql(league, stat_type)
            except LeagueStatContractError:
                continue
            label = canonical_stat_type(league, stat_type)
            season = con.execute(
                f"SELECT MAX(season) FROM player_stats WHERE league=? AND {clause}",
                [league, *params],
            ).fetchone()[0]
            if season is None:
                continue
            for row in con.execute(
                f"""SELECT player_id FROM player_stats
                    WHERE league=? AND season=? AND {clause}
                      AND player_id IS NOT NULL""",
                [league, season, *params],
            ):
                seen.add((league, label, int(row[0])))
    return seen


RULE_NAMES = (
    "R1_non_canonical_stat_type",
    "R2_non_owning_source",
    "R3_unowned_identity",
    "R4_legacy_season_vocabulary",
    "R5_duplicate_owner",
    "R6_stale_display_name",
)


def classify(con: sqlite3.Connection):
    """Assign every offending row to exactly one rule.

    R1-R4 are evaluated per row, first match wins, so the counts add up to rows
    touched rather than to a total that double-counts a row failing two
    conditions at once. R5 and R6 then run over what R1-R4 leave behind, because
    both ask questions about the surviving population: whether one player still
    owns two rows, and whether the display copy still matches the spine.
    """
    rules: dict[str, list] = {name: [] for name in RULE_NAMES}
    rekey: dict[int, int] = {}

    rows = con.execute(
        """SELECT ps.id, ps.league, ps.season, ps.stat_type, ps.source,
                  ps.player_id, ps.player_name, ps.name_norm, ps.team, ps.games,
                  p.name AS canonical_name
           FROM player_stats ps
           LEFT JOIN players p ON p.id = ps.player_id
           ORDER BY ps.id"""
    ).fetchall()
    survivors = []
    for row in rows:
        league = str(row["league"] or "").strip().lower()
        raw_type = str(row["stat_type"] or "").strip().lower()
        try:
            expected = canonical_stat_type(league, row["stat_type"])
        except LeagueStatContractError:
            # A league this table is not allowed to hold at all. R1 owns it:
            # no canonical predicate can name it, so no reader can reach it.
            rules["R1_non_canonical_stat_type"].append(row)
            continue
        if raw_type != expected:
            rules["R1_non_canonical_stat_type"].append(row)
            continue
        if not source_owns_stats(league, expected, row["season"], row["source"]):
            rules["R2_non_owning_source"].append(row)
            continue
        if row["player_id"] is None:
            rules["R3_unowned_identity"].append(row)
            continue
        season = int(row["season"])
        source = str(row["source"] or "").strip()
        if (league, source) in LEGACY_SEASON_SOURCES:
            normalized = normalize_season(source, league, season)
            if normalized != season:
                rules["R4_legacy_season_vocabulary"].append(row)
                rekey[int(row["id"])] = normalized
                continue
        survivors.append((row, (int(row["player_id"]), league, season, expected)))

    moved, deleted = _split_legacy(
        rules["R4_legacy_season_vocabulary"], rekey, survivors
    )
    survivors.extend(moved)
    _classify_survivors(rules, rekey, survivors)
    return rules, rekey, {"moved": [row for row, _ in moved], "deleted": deleted}


def _classify_survivors(rules: dict[str, list], rekey: dict[int, int], survivors) -> None:
    """R5 and R6, over the rows R1-R4 leave in place.

    R5 `duplicate_owner` -- one player, two rows under the canonical key, which
    is what the name key made possible and what the canonical key will reject.
    Two shapes produced it, and the survivor rule is the same for both: keep the
    row the CURRENT writer would produce, meaning the one whose `name_norm`
    equals `normalize_player_name(players.name)`.

      * a placeholder beside its resolution -- `mlbam_669911` next to
        `michael toglia`, 71 of them on prod
      * two spellings of one normalizer -- `h ctor rodr guez` next to
        `hector rodriguez`, because the NFKD/ascii-fold path changed underneath
        rows already written

    If no row in a group is what the writer would produce today, that is a third
    shape nobody has measured, and the repair refuses rather than picking by
    games played and calling it a rule.

    R6 `stale_display_name` -- `player_name` is a denormalized copy of
    `players.name` that `publish_player_stats` rewrites on every publish. Where
    it has drifted the source of truth is not in doubt, so this one repairs
    rather than deletes.
    """
    groups: dict[tuple, list] = {}
    for row, key in survivors:
        groups.setdefault(key, []).append(row)

    kept = []
    unresolvable = []
    for group in groups.values():
        if len(group) == 1:
            kept.append(group[0])
            continue
        wanted = [
            row for row in group
            if str(row["name_norm"] or "")
            == normalize_player_name(row["canonical_name"])
        ]
        if len(wanted) != 1:
            unresolvable.append(group)
            continue
        keep = wanted[0]
        kept.append(keep)
        rules["R5_duplicate_owner"].extend(row for row in group if row["id"] != keep["id"])

    if unresolvable:
        raise RuntimeError(
            f"REFUSING: {len(unresolvable)} duplicate group(s) where no single row is "
            "what the current writer would produce, so there is no rule here to apply "
            f"-- e.g. {[[(r['id'], r['name_norm']) for r in g] for g in unresolvable[:2]]}"
        )

    for row in kept:
        if row["canonical_name"] is None:
            continue
        if str(row["player_name"]) != str(row["canonical_name"]):
            rules["R6_stale_display_name"].append(row)


def _describe(rules: dict[str, list], rekey: dict[int, int], legacy: dict) -> None:
    for name, matched in rules.items():
        if not matched:
            print(f"  {name}: 0 rows")
            continue
        shape = Counter(
            (r["league"], r["season"], r["stat_type"], r["source"]) for r in matched
        )
        print(f"  {name}: {len(matched)} rows")
        for key, count in shape.most_common(6):
            print("      %-4s %-9s %-8s %-24s %6d" % (*[str(k) for k in key], count))

    if rules["R4_legacy_season_vocabulary"]:
        print(
            f"      -> {len(legacy['deleted'])} unreachable duplicates deleted, "
            f"{len(legacy['moved'])} re-keyed to the ESPN vocabulary"
        )
        for row in legacy["moved"][:4]:
            print(
                "         keep %s (%s games, %s -> %s)"
                % (row["player_name"], row["games"], row["season"], rekey[int(row["id"])])
            )


def _split_legacy(matched: list, rekey: dict[int, int], survivors: list):
    """Decide which legacy-key rows are duplicates and which are the only copy.

    The question is asked against the rows that SURVIVE R1-R3, not against the
    table, because a legacy row whose only ESPN-keyed twin is itself about to be
    deleted is not a duplicate -- it is the last copy, and re-keying it is what
    keeps the player. Returns `(moved, deleted)`, where each moved entry is the
    `(row, canonical key)` pair the later rules need.
    """
    occupied = {key for _, key in survivors}
    moved, deleted = [], []
    for row in matched:
        key = (
            int(row["player_id"]),
            str(row["league"] or "").strip().lower(),
            rekey[int(row["id"])],
            canonical_stat_type(row["league"], row["stat_type"]),
        )
        if key in occupied:
            deleted.append(row)
            continue
        occupied.add(key)
        moved.append((row, key))
    return moved, deleted


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    before = served_population(con)
    print(f"served population before: {len(before)} (league, stat_type, player) pairs")

    rules, rekey, legacy = classify(con)
    total = sum(len(v) for v in rules.values())
    if not total:
        print("nothing to repair: every row is canonical, owned, identified and ESPN-keyed")
        return 0
    print(f"{total} row(s) matched a repair rule:")
    _describe(rules, rekey, legacy)

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    legacy_deleted, legacy_moved = legacy["deleted"], legacy["moved"]
    try:
        con.execute("BEGIN IMMEDIATE")
        for row in rules["R3_unowned_identity"]:
            # Queued before it is deleted: the row leaves `player_stats`, but the
            # fact that this publisher named a player nobody could resolve stays
            # on the record where the ingest already writes its misses.
            queue_unresolved_player(
                con,
                source=str(row["source"] or "unknown"),
                raw_name=str(row["player_name"] or ""),
                league=str(row["league"] or ""),
                team=row["team"],
                source_player_key=None,
                reason="stranded_stats_row_without_identity",
            )
        drop_ids = [
            (int(row["id"]),)
            for name in (
                "R1_non_canonical_stat_type",
                "R2_non_owning_source",
                "R3_unowned_identity",
                "R5_duplicate_owner",
            )
            for row in rules[name]
        ]
        drop_ids.extend((int(row["id"]),) for row in legacy_deleted)
        con.executemany("DELETE FROM player_stats WHERE id=?", drop_ids)
        con.executemany(
            "UPDATE player_stats SET season=? WHERE id=?",
            [(rekey[int(row["id"])], int(row["id"])) for row in legacy_moved],
        )
        # R6 repairs rather than deletes: `player_name`/`name_norm` are copies of
        # `players.name` that the next publish would overwrite anyway.
        con.executemany(
            "UPDATE player_stats SET player_name=?, name_norm=? WHERE id=?",
            [
                (
                    str(row["canonical_name"]),
                    normalize_player_name(row["canonical_name"]),
                    int(row["id"]),
                )
                for row in rules["R6_stale_display_name"]
            ],
        )

        after = served_population(con)
        lost = before - after
        if lost:
            raise RuntimeError(
                f"REFUSING: {len(lost)} identifiable player(s) would stop being served, "
                f"e.g. {sorted(lost)[:5]}"
            )
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise

    after = served_population(con)
    print(
        f"deleted {len(drop_ids)} row(s), re-keyed {len(legacy_moved)}, "
        f"re-synced {len(rules['R6_stale_display_name'])} display name(s); "
        f"served population after: {len(after)} "
        f"({'unchanged' if after >= before else 'SHRANK'})"
    )
    gained = after - before
    if gained:
        print(f"  (+{len(gained)} now reachable that were not before)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
