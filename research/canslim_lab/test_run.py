import csv
import io
import unittest

from research.canslim_lab.run import regime, run


class ResearchWorkflowTests(unittest.TestCase):
    def setUp(self):
        index = dict(above_21=True, above_50=True, distribution_days=2,
                     follow_through_active=True, follow_through_failed=False)
        self.snapshot = dict(as_of="2026-11-27", market=dict(
            nasdaq=index.copy(), sp500=index.copy(), breadth_trend="stable", vix_curve="contango"))
        self.stock = dict(ticker="TEST", close=102, pivot=100, invalidation=95,
                          pivot_basis="Supplied handle high", base="cup with handle",
                          breakout_volume=150, prior_daily_volume_average=100, earnings_sessions=20,
                          eps_growth=30, sales_growth=25, annual_eps_growth=[26, 27, 28],
                          ibd=dict(source="fixture", as_of="2026-11-27", rs_rating=90),
                          leadership=dict(rs_line_near_high=True, outperforming_peers=3),
                          bear_case="Margins fade", thesis_invalidation="Margins revert")
        self.snapshot["stocks"] = [self.stock]

    def test_correction_takes_precedence(self):
        market = self.snapshot["market"]
        market["nasdaq"]["distribution_days"] = 5
        market["sp500"]["follow_through_failed"] = True
        self.assertEqual(regime(market)[0], "Correction")
        self.assertEqual(regime({})[0], "Unconfirmed")

    def test_screen_and_missing_ibd(self):
        result = run("SCREEN", self.snapshot, [], [])
        self.assertEqual(result["findings"][0]["verdict"], "Actionable")
        del self.stock["ibd"]
        result = run("SCREEN", self.snapshot, [], [])
        self.assertEqual(result["findings"][0]["verdict"], "Watch")
        self.assertEqual(result["findings"][0]["grades"]["L"], "Provisional")

    def test_repeat_preserves_verdict_and_score(self):
        first = run("SCREEN", self.snapshot, [], [])
        log = list(csv.DictReader(io.StringIO(first["verdict_csv"])))
        signal_id = log[0]["signal_id"]
        self.stock["failed_breakout"] = True
        repeat = run("SCREEN", self.snapshot, [], log)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(repeat["verdict_csv"])))), 1)
        self.assertEqual(log[0]["verdict"], "Actionable")
        result = run("SCORE", dict(as_of="2026-12-28", outcomes={signal_id: {"4": dict(
            date="2026-12-28", close=112.2, source="fixture", spx_return=4,
            matched_baseline_return=5)}}), [], log)
        comparison = result["score"]["Actionable_4w"]["comparisons"]["baseline"]
        self.assertEqual(comparison["mean_excess"], 5)
        self.assertFalse(comparison["sufficient_sample"])

    def test_holding_uses_actual_entry(self):
        self.stock.update(holding=True, close=91, actual_entry=100)
        result = run("HOLDING-REVIEW", self.snapshot, [], [])
        self.assertEqual(result["findings"][0]["verdict"], "Exit")


if __name__ == "__main__":
    unittest.main()
