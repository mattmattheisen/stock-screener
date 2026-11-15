import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cache_bridge import from_cached_frame, read_existing_cache, UnverifiedPriceData

class FakeFrame:
    columns=("Close", "Adj Close", "Volume")
    def __init__(self, rows):
        self.rows=rows
        self.empty=not rows
    def iterrows(self):
        yield from self.rows

class FakeCache:
    def __init__(self, frame):
        self.frame=frame
        self.calls=0
    def get_cached_only(self, symbol, period="1y"):
        self.calls+=1
        return self.frame

class CacheBridgeTests(unittest.TestCase):
    def sample(self, count=55, price=100, last_price=100):
        start=date(2026,1,1)
        return FakeFrame([(start+timedelta(days=i),{
            "Close": 100, "Adj Close": last_price if i==count-1 else price,
            "Volume": 100
        }) for i in range(count)])
    def kwargs(self):
        return dict(symbol="MSFT",as_of=date(2026,2,24),
                    last_complete_session=date(2026,2,24), source="existing_cache",
                    adjustment_provenance_verified=True,corporate_action_window_verified=True)
    def test_cache_approved(self):
        result=from_cached_frame(self.sample(),**self.kwargs())
        self.assertEqual(result.as_of,date(2026,2,24))
    def test_default_rejects_unverified_cache(self):
        cache=FakeCache(self.sample())
        with self.assertRaises(UnverifiedPriceData):
            read_existing_cache(cache,symbol="MSFT",as_of=date(2026,2,24),
                                last_complete_session=date(2026,2,24),source="existing_cache")
        self.assertEqual(cache.calls,0)
    def test_cache_used_without_network(self):
        cache=FakeCache(self.sample())
        result=read_existing_cache(cache,**self.kwargs())
        self.assertEqual(result.symbol,"MSFT")
        self.assertEqual(cache.calls,1)
    def test_missing_adjusted_close_rejected(self):
        frame=self.sample()
        frame.columns=("Close","Volume")
        with self.assertRaises(UnverifiedPriceData):
            from_cached_frame(frame,**self.kwargs())
    def test_stale_cache_rejected(self):
        frame=self.sample(50)
        with self.assertRaises(UnverifiedPriceData):
            from_cached_frame(frame,**self.kwargs())
    def test_future_bar_not_used(self):
        frame=self.sample()
        frame.rows.append((date(2026,2,25),{"Adj Close":1,"Close":1,"Volume":99999}))
        result=from_cached_frame(frame,**self.kwargs())
        self.assertEqual(result.price,100)
    def test_unverified_corporate_actions_rejected(self):
        opts=self.kwargs()
        opts["corporate_action_window_verified"]=False
        with self.assertRaises(UnverifiedPriceData):
            from_cached_frame(self.sample(),**opts)
if __name__=="__main__":
    unittest.main()
