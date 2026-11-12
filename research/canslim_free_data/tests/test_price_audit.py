import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from price_audit import PriceAuditRow, audit_prices

START=date(2026, 1, 2)
def row(day=START, raw=100, adjusted=98, volume=100, split=None):
    return PriceAuditRow(day,raw,adjusted,volume,split)
def issues(rows, as_of=START, last=START):
    return {x.code for x in audit_prices(rows,as_of=as_of,expected_last_session=last)}
class PriceAuditTests(unittest.TestCase):
    def test_unattested_even_when_numbers_look_valid(self):
        self.assertEqual(issues([row()]),{"PROVENANCE_NOT_CERTIFIED"})
    def test_missing_adj_close(self):
        self.assertIn("MISSING_ADJUSTED_CLOSE",issues([row(adjusted=None)]))
    def test_future_bar(self):
        self.assertIn("FUTURE_BAR",issues([row(),row(START+timedelta(days=1))]))
    def test_duplicate(self):
        self.assertIn("DUPLICATE_DATE",issues([row(),row()]))
    def test_stale(self):
        self.assertIn("STALE_OR_MISSING_EXPECTED_BAR",issues([row()],last=START+timedelta(days=1)))
    def test_split_window_not_silently_accepted(self):
        self.assertIn("SPLIT_WINDOW",issues([row(split=2)]))
    def test_large_price_gap_diagnostic_not_split_assumption(self):
        self.assertIn("LARGE_RAW_PRICE_DISCONTINUITY",
                      issues([row(),row(START+timedelta(days=1),raw=60)],
                      as_of=START+timedelta(days=1),last=START+timedelta(days=1)))
    def test_negative_volume(self):
        self.assertIn("INVALID_VOLUME",issues([row(volume=-3)]))
    def test_no_data(self):
        self.assertIn("NO_DATA",issues([]))
if __name__=="__main__":
    unittest.main()
