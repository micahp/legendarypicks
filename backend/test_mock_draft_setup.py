#!/usr/bin/env python3

"""A drafter chooses the league they are drafting in, and where they sit in it.

Until now both were decided for them: ``teams`` and ``rounds`` were literals in
the INSERT (``VALUES (?, ?, ?, ?, 12, 15, ...)``) and the seat was a random
integer the frontend picked without asking. A 10- or 14-team draft was
unrepresentable in the schema's data even though the columns existed.

EXPECTED VALUES WRITTEN 2026-07-28, BEFORE THE CODE. Everything below is a
number this file asserts and the implementation must meet -- not a description
of what the implementation happens to do:

  * league sizes are exactly {10, 12, 14}. 11, 8, 16 and "12" are rejected.
  * omitting ``teams`` keeps the old default of 12, so every draft created
    before this change still round-trips.
  * ``seat`` is bounded by the league, not by the literal 12: seat 13 is legal
    in a 14-team draft and illegal in a 12-team one.
  * ``picks_expected`` is teams x rounds -- 150 / 180 / 210, never a constant.

LP_DB_PATH is pointed at a tempfile BEFORE importing the router, same pattern
as test_mock_draft_completion.py.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="mock-draft-setup-", suffix=".db", delete=False
)
_TEST_DB.close()
_ORIGINAL_LP_DB_PATH = os.environ.get("LP_DB_PATH")
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers import nfl_mock_draft  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

if _ORIGINAL_LP_DB_PATH is None:
    os.environ.pop("LP_DB_PATH", None)
else:
    os.environ["LP_DB_PATH"] = _ORIGINAL_LP_DB_PATH

app = FastAPI()
app.include_router(nfl_mock_draft.router)
client = TestClient(app)

DEVICE = "cccccccc-cccc-cccc-cccc-cccccccccccc"
SEASON = nfl_mock_draft._CURRENT_SEASON
ROUNDS = 15


class LeagueSizeTests(unittest.TestCase):

    def setUp(self):
        connection = nfl_mock_draft._conn()
        try:
            connection.execute("DELETE FROM nfl_mock_draft_picks")
            connection.execute("DELETE FROM nfl_mock_drafts")
            connection.commit()
        finally:
            connection.close()

    def _create(self, **body):
        payload = {"season": SEASON, "seat": 1, "seed": 42}
        payload.update(body)
        return client.post(
            "/api/nfl/mock-draft", headers={"X-Device-Id": DEVICE}, json=payload
        )

    def _get(self, draft_id):
        return client.get(
            f"/api/nfl/mock-draft/{draft_id}", headers={"X-Device-Id": DEVICE}
        )

    # ── league size ───────────────────────────────────────────────────────

    def test_the_three_league_sizes_are_accepted_and_stored(self):
        for teams in (10, 12, 14):
            res = self._create(teams=teams)
            self.assertEqual(res.status_code, 200, res.text)
            body = self._get(res.json()["id"]).json()
            self.assertEqual(body["teams"], teams)
            self.assertEqual(body["rounds"], ROUNDS)

    def test_picks_expected_follows_the_league_size(self):
        for teams, expected in ((10, 150), (12, 180), (14, 210)):
            res = self._create(teams=teams)
            body = self._get(res.json()["id"]).json()
            self.assertEqual(
                body["picks_expected"],
                expected,
                "a %d-team draft expects %d picks" % (teams, expected),
            )

    def test_a_league_size_we_do_not_offer_is_refused(self):
        # 11 and 16 are real fantasy league sizes we deliberately do not
        # support; accepting them would put a draft on screen the bots and the
        # roster construction were never sized for.
        for teams in (0, 1, 8, 9, 11, 13, 16, 32, -12):
            res = self._create(teams=teams)
            self.assertEqual(res.status_code, 400, "teams=%r must be 400" % (teams,))

    def test_a_league_size_of_the_wrong_type_is_refused(self):
        for teams in ("12", 12.0, True, None, [12], {"teams": 12}):
            res = self._create(teams=teams)
            self.assertEqual(res.status_code, 400, "teams=%r must be 400" % (teams,))

    def test_omitting_teams_keeps_the_twelve_team_default(self):
        res = self._create()
        self.assertEqual(res.status_code, 200, res.text)
        body = self._get(res.json()["id"]).json()
        self.assertEqual(body["teams"], 12)
        self.assertEqual(body["picks_expected"], 180)

    # ── seat, bounded by the league ───────────────────────────────────────

    def test_the_last_seat_of_a_fourteen_team_league_is_draftable(self):
        for seat in (13, 14):
            res = self._create(teams=14, seat=seat)
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(self._get(res.json()["id"]).json()["seat"], seat)

    def test_a_seat_past_the_end_of_the_league_is_refused(self):
        # The old bound was the literal 12. Seat 13 has to flip on league size:
        # legal at 14 teams, illegal at 12.
        self.assertEqual(self._create(teams=12, seat=13).status_code, 400)
        self.assertEqual(self._create(teams=10, seat=11).status_code, 400)
        self.assertEqual(self._create(teams=14, seat=15).status_code, 400)
        self.assertEqual(self._create(teams=14, seat=0).status_code, 400)

    def test_the_seat_is_stored_as_chosen_not_reassigned(self):
        for teams in (10, 12, 14):
            for seat in (1, teams // 2, teams):
                res = self._create(teams=teams, seat=seat)
                self.assertEqual(res.status_code, 200, res.text)
                self.assertEqual(self._get(res.json()["id"]).json()["seat"], seat)

    # ── the saved row stays coherent under the chosen size ────────────────

    def test_a_ten_team_draft_completes_at_one_hundred_fifty_picks(self):
        res = self._create(teams=10, seat=3)
        draft_id = res.json()["id"]
        picks = [
            {"pick_no": n, "team_no": (n - 1) % 10 + 1, "player_id": 2000 + n, "auto": 1}
            for n in range(1, 151)
        ]
        for i in range(0, len(picks), 50):
            res = client.post(
                f"/api/nfl/mock-draft/{draft_id}/picks",
                headers={"X-Device-Id": DEVICE},
                json={"picks": picks[i:i + 50]},
            )
            self.assertEqual(res.status_code, 200, res.text)

        done = client.post(
            f"/api/nfl/mock-draft/{draft_id}/complete", headers={"X-Device-Id": DEVICE}
        )
        self.assertEqual(done.status_code, 200, done.text)
        body = done.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["pick_count"], 150)
        self.assertEqual(body["picks_expected"], 150)
        self.assertEqual(body["missing_picks"], [])

    def test_the_drafts_list_reports_each_leagues_own_size(self):
        wanted = {}
        for teams in (10, 12, 14):
            wanted[self._create(teams=teams).json()["id"]] = teams

        listed = client.get(
            "/api/nfl/mock-drafts", headers={"X-Device-Id": DEVICE}
        ).json()["drafts"]
        by_id = {d["id"]: d for d in listed}
        for draft_id, teams in wanted.items():
            self.assertEqual(by_id[draft_id]["teams"], teams)
            self.assertEqual(by_id[draft_id]["picks_expected"], teams * ROUNDS)


if __name__ == "__main__":
    unittest.main()
