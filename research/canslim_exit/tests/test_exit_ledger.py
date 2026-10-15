"""Offline unit tests: python -m unittest discover -s research/canslim_exit/tests -v"""
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exit_ledger import evaluate

class ExitLedgerTests(unittest.TestCase):
    def test_missing_data_is_not_hold(self):
        result = evaluate({"symbol": "TEST", "entry_price": "100", "close": "105"})
        self.assertEqual(result["status"], "INSUFFICIENT DATA - MANUAL REVIEW")
        self.assertLess(result["indicator_coverage_pct"], 75)

    def test_eight_percent_stop(self):
        result = evaluate({"symbol": "TEST", "entry_price": "100", "close": "92"})
        self.assertEqual(result["status"], "HARD STOP BREACH - REVIEW IMMEDIATELY")

    def test_stop_threshold_is_not_hardcoded_per_symbol(self):
        result = evaluate({"symbol": "TSM", "entry_price": "428.23", "close": "390"})
        self.assertEqual(result["status"], "HARD STOP BREACH - REVIEW IMMEDIATELY")

    def test_failed_breakout_requires_known_nonpositive_return(self):
        result = evaluate({"symbol": "TEST", "failed_breakout": "true"})
        self.assertEqual(result["status"], "INSUFFICIENT DATA - MANUAL REVIEW")

    def test_chandelier_missing_atr(self):
        result = evaluate({"symbol": "TEST", "entry_price": "100", "close": "110", "peak_close_since_entry": "115"})
        self.assertEqual(result["chandelier_close_proxy"], "")

    def test_no_automatic_execution(self):
        result = evaluate({"symbol": "TEST", "entry_price": "100", "close": "90"})
        self.assertNotIn("order", result)

if __name__ == "__main__":
    unittest.main()
