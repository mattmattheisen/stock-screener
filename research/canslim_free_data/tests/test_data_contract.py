import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data_contract import MarketObservation, evaluate_history

class FreeDataTests(unittest.TestCase):
    def sample(self, n=51, close=100, last=100, last_vol=100):
        start=date(2026, 1, 1)
        return [MarketObservation("MSFT",start+timedelta(days=i),last if i==n-1 else close,
                last_vol if i==n-1 else 100,"existing_market_provider", True,True) for i in range(n)]

    def test_no_data(self):
        with self.assertRaises(ValueError):
            evaluate_history([],date(2026,3,1))
    def test_incomplete_session_ignored(self):
        bars=self.sample()
        bad=MarketObservation("MSFT",date(2026,3,1),1,999,"provider",True,False)
        x=evaluate_history(bars+[bad],date(2026,3,1))
        self.assertEqual(x.price,100)
    def test_high_volume_50dma_break(self):
        bars=self.sample(last=70,last_vol=250)
        x=evaluate_history(bars,date(2026,3,1))
        self.assertEqual(x.status,"REVIEW: below 50DMA on elevated volume")
    def test_short_history_unknown(self):
        x=evaluate_history(self.sample(10),date(2026,3,1))
        self.assertEqual(x.status,"INSUFFICIENT DATA")
    def test_duplicate_rejected(self):
        bars=self.sample()
        with self.assertRaises(ValueError):
            evaluate_history(bars+[bars[-1]],date(2026,3,1))
    def test_unadjusted_rejected(self):
        bars=self.sample()
        bars[-1]=MarketObservation("MSFT",bars[-1].as_of,100,100,"source",False,True)
        with self.assertRaises(ValueError):
            evaluate_history(bars,date(2026,3,1))
    def test_point_in_time_cutoff(self):
        bars=self.sample()
        result=evaluate_history(bars,date(2026,2,10))
        self.assertEqual(result.as_of,date(2026,2,10))
if __name__=="__main__":
    unittest.main()
