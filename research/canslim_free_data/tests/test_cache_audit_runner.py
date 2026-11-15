import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cache_audit_runner import inspect_cached_prices

START = date(2026, 1, 1)

class Frame:
    def __init__(self, rows, columns=("Close","Adj Close","Volume")):
        self.rows = rows
        self.columns = columns
        self.empty = not rows
    def iterrows(self):
        yield from self.rows

class Cache:
    def __init__(self, frame):
        self.frame = frame
        self.reads = 0
    def get_cached_only(self, symbol, period="1y"):
        assert period == "1y"
        self.reads += 1
        return self.frame

def bars(n=55, adjusted=98):
    return Frame([(START+timedelta(days=i), {"Close": 100,
        "Adj Close": adjusted, "Volume": 100}) for i in range(n)])

class CacheAuditTests(unittest.TestCase):
    def run_audit(self, frame, expected=START+timedelta(days=54)):
        cache = Cache(frame)
        result = inspect_cached_prices(
            cache, symbol="MSFT", as_of=START+timedelta(days=54),
            expected_last_session=expected)
        self.assertEqual(cache.reads, 1)
        self.assertFalse(result.data_certified)
        return result

    def test_nominal_cache_remains_uncertified(self):
        x = self.run_audit(bars())
        self.assertIn("CORPORATE_ACTION_SOURCE_UNVERIFIED", x.findings)
        self.assertIn("PROVENANCE_NOT_CERTIFIED", x.findings)

    def test_raw_close_fallback_not_accepted(self):
        x = self.run_audit(bars(adjusted=100))
        self.assertIn("EQUAL_RAW_ADJUSTED_REQUIRES_SOURCE_VERIFICATION", x.findings)

    def test_explicit_adjusted_missing(self):
        frame = bars()
        frame.columns = ("Close", "Volume")
        x = self.run_audit(frame)
        self.assertIn("EXPLICIT_ADJUSTED_COLUMN_ABSENT", x.findings)

    def test_stale_bar(self):
        x = self.run_audit(bars(50))
        self.assertIn("STALE_OR_MISSING_EXPECTED_BAR", x.findings)

    def test_future_bar_reported(self):
        frame = bars()
        frame.rows.append((START+timedelta(days=55),
                           {"Close": 100, "Adj Close": 98, "Volume": 100}))
        x = self.run_audit(frame)
        self.assertIn("FUTURE_BAR", x.findings)

    def test_missing_cache(self):
        x = self.run_audit(None)
        self.assertIn("NO_DATA", x.findings)

    def test_reject_future_expected_session(self):
        with self.assertRaises(ValueError):
            inspect_cached_prices(Cache(bars()), symbol="MSFT", as_of=START,
                                  expected_last_session=START+timedelta(days=1))

if __name__ == "__main__":
    unittest.main()
