"""Starters and jersey numbers for one NFL game, from synthetic depth-chart and roster tables."""
import json
import os
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

import build_nfl_starters_snapshot as b


def depth_row(dt, team, grp, abb, rank, gsis, name):
    return {"dt": dt, "team": team, "player_name": name, "gsis_id": gsis, "pos_grp": grp,
            "pos_abb": abb, "pos_rank": rank}


def roster_row(week, team, gsis, jersey, name):
    return {"season": 2026, "week": week, "game_type": "REG", "team": team, "gsis_id": gsis,
            "jersey_number": jersey, "full_name": name}


def write(rows, path):
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    pq.write_table(pa.table(cols), path)


class StartersAndJerseys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        dt = "2026-10-25T12:00:00Z"
        rows = []
        n = 0

        def add(team, grp, abb, rank=1):
            nonlocal n
            n += 1
            rows.append(depth_row(dt, team, grp, abb, rank, "00-%07d" % n, "%s %s %d" % (team, abb, rank)))

        for team, offense_grp, defense_grp in (("AAA", b.OFFENSE_GROUP, "Base 4-3 D"), ("BBB", b.OFFENSE_GROUP, "Base 3-4 D")):
            for abb, count in b.OFFENSE_SLOTS:
                for rank in range(1, count + 1):
                    add(team, offense_grp, abb, rank)
            for abb, _ in b.DEFENSE_SLOTS[defense_grp]:
                add(team, defense_grp, abb, 1)
            for abb, _ in b.SPECIAL_TEAMS:
                add(team, "Special Teams", abb, 1)
        self.depth = os.path.join(self.tmp, "depth.parquet")
        write(rows, self.depth)
        # Latest regular-season week carries jersey numbers; an older week carries different ones and must be ignored.
        roster = []
        for r in rows:
            roster.append(roster_row(6, r["team"], r["gsis_id"], 90, "old"))
            roster.append(roster_row(7, r["team"], r["gsis_id"], 1 + (int(r["gsis_id"][-7:]) % 98), r["player_name"]))
        self.roster = os.path.join(self.tmp, "roster.parquet")
        write(roster, self.roster)

    def test_each_side_has_its_full_starting_units_and_latest_numbers(self):
        out = os.path.join(self.tmp, "out.json")
        doc = b.main([self.depth, "--roster", self.roster, "--away", "AAA", "--home", "BBB", "--out", out])
        for side in ("away", "home"):
            r = doc["rosters"][side]
            self.assertEqual(len(r["players"]), 28, side)
            self.assertEqual([g for g in r["missing"] if "gap" not in g and "pos_abb" in g], [], side)
            self.assertTrue(all(p["jersey_number"] is not None for p in r["players"]), side)
            self.assertEqual(r["jersey_week"], 7)
        with open(out) as fh:
            self.assertEqual(json.load(fh)["schema"], "lp-nfl-starters-snapshot-1")

    def test_a_missing_starter_is_a_gap_not_a_substitute(self):
        rows = pq.read_table(self.depth).to_pydict()
        keep = [i for i in range(len(rows["pos_abb"])) if not (rows["team"][i] == "AAA" and rows["pos_abb"][i] == "LT")]
        trimmed = {k: [v[i] for i in keep] for k, v in rows.items()}
        path = os.path.join(self.tmp, "depth-missing.parquet")
        pq.write_table(pa.table(trimmed), path)
        doc = b.main([path, "--roster", self.roster, "--away", "AAA", "--home", "BBB", "--out", os.path.join(self.tmp, "m.json")])
        away = doc["rosters"]["away"]
        self.assertEqual(len(away["players"]), 27)
        self.assertIn({"pos_abb": "LT", "needed": 1, "found": 0, "group": b.OFFENSE_GROUP}, away["missing"])
        self.assertNotIn("LG", [p["pos_abb"] for p in away["players"] if p["pos_abb"] == "LT"])

    def test_a_player_on_another_team_gets_no_number(self):
        roster = pq.read_table(self.roster).to_pydict()
        for i in range(len(roster["week"])):
            if roster["week"][i] == 7 and roster["team"][i] == "AAA" and roster["full_name"][i] == "AAA QB 1":
                roster["team"][i] = "BBB"
        path = os.path.join(self.tmp, "roster-moved.parquet")
        pq.write_table(pa.table(roster), path)
        doc = b.main([os.path.join(self.tmp, "depth.parquet"), "--roster", path, "--away", "AAA", "--home", "BBB",
                      "--out", os.path.join(self.tmp, "t.json")])
        qb = next(p for p in doc["rosters"]["away"]["players"] if p["pos_abb"] == "QB")
        self.assertIsNone(qb["jersey_number"])
        self.assertIn("team_mismatch", [g.get("gap") for g in doc["rosters"]["away"]["missing"]])


if __name__ == "__main__":
    unittest.main()
