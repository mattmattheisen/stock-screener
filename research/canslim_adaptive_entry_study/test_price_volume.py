import unittest
from research.canslim_adaptive_entry_study.price_volume import calculate


class TestPriceVolume(unittest.TestCase):
    def test_intraday_high_not_close(self):
        c = [90.0] * 253
        h = [90.0] * 253
        v = [100.0] * 253
        h[-10] = 100.0
        r = calculate(c, h, v)
        self.assertEqual(r.high_52w, 100)
        self.assertTrue(r.n_10_pass)
        self.assertEqual(r.distance_from_high_pct, 10)
        self.assertIsNone(r.s_13_pass)

    def test_up_down_uses_chronological_returns(self):
        c = [90.0] * 203 + [90.0 + i % 2 for i in range(50)]
        h = [max(x, 91.0) for x in c]
        v = [100.0] * 203 + [200.0 if i % 2 else 100.0 for i in range(50)]
        r = calculate(c, h, v)
        self.assertGreater(r.up_volume, r.down_volume)
        self.assertTrue(r.s_13_pass)

    def test_rolling_high_excludes_stale_high(self):
        c = [90.0] * 253
        h = [90.0] * 253
        v = [100.0] * 253
        h[0] = 200
        self.assertEqual(calculate(c, h, v).high_52w, 90)

    def test_missing_history_fails_closed(self):
        with self.assertRaises(ValueError):
            calculate([1.0], [1.0], [1.0])
