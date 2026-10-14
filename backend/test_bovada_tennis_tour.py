"""Tennis discovery keys on the tour path, so the lane survives a tournament ending."""
import unittest

from bovada_scraper.client import tennis_tour_events


def _group(*events):
    return {"events": list(events)}


class TennisTourEventsTest(unittest.TestCase):
    def test_keeps_only_the_requested_tour_across_tournaments(self):
        data = [_group(
            {"description": "ATP Shanghai", "link": "/tennis/atp/shanghai/atp-shanghai-202610150010"},
            {"description": "A vs B", "link": "/tennis/atp/shanghai/a-b-202610150230"},
            {"description": "C vs D", "link": "/tennis/wta/beijing/c-d-202610150400"},
            {"description": "E vs F", "link": "/tennis/us-open/men-s-singles/e-f-202609010100"},
        )]
        atp = tennis_tour_events("atp", data)
        wta = tennis_tour_events("wta", data)
        self.assertEqual([e["description"] for e in atp], ["ATP Shanghai", "A vs B"])
        self.assertEqual([e["description"] for e in wta], ["C vs D"])

    def test_a_missing_link_is_skipped_not_matched(self):
        data = [_group({"description": "no link"}, {"description": "null link", "link": None})]
        self.assertEqual(tennis_tour_events("atp", data), [])

    def test_an_empty_coupon_yields_no_events(self):
        self.assertEqual(tennis_tour_events("atp", []), [])
        self.assertEqual(tennis_tour_events("atp", [{"events": []}]), [])


if __name__ == "__main__":
    unittest.main()
