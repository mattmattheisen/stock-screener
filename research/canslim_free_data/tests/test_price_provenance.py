import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from price_provenance import PriceProvenance, Purpose, check_provenance

class ProvenanceTests(unittest.TestCase):
    def receipt(self, **changes):
        x=dict(symbol="MSFT", source="audited_provider", expected_session=date(2026,11,11),
               latest_session=date(2026,11,11), requested_as_of=date(2026,11,11),
               retrieved_at=datetime(2026,11,11,23,tzinfo=timezone.utc),
               history_start=date(2026,8,1),
               adjustment_mode="verified_explicit_adj_close",
               adjustment_verified_by="audit_run_1",
               corporate_actions_verified_by="actions_audit_1",
               split_volume_verified_by="volume_audit_1", point_in_time_source=True)
        x.update(changes)
        return PriceProvenance(**x)
    def test_attested_live_receipt(self):
        self.assertTrue(check_provenance(self.receipt(),Purpose.LIVE_EOD).accepted)
    def test_missing_price_adjustment_auditor(self):
        x=check_provenance(self.receipt(adjustment_verified_by=""),Purpose.LIVE_EOD)
        self.assertIn("NO_ADJUSTMENT_AUDITOR",x.failures)
    def test_stale_bar(self):
        x=check_provenance(self.receipt(latest_session=date(2026,11,10)),Purpose.LIVE_EOD)
        self.assertIn("STALE_OR_FUTURE_SESSION",x.failures)
    def test_unchecked_volume(self):
        x=check_provenance(self.receipt(split_volume_verified_by=""),Purpose.LIVE_EOD)
        self.assertIn("NO_VOLUME_RECONCILIATION",x.failures)
    def test_retrospectively_fetched_backtest_not_valid(self):
        x=check_provenance(self.receipt(
            requested_as_of=date(2026,9,1),expected_session=date(2026,9,1),
            latest_session=date(2026,9,1),retrieved_at=datetime(2026,11,11,tzinfo=timezone.utc)),
            Purpose.HISTORICAL_BACKTEST)
        self.assertIn("NOT_POINT_IN_TIME",x.failures)
    def test_historical_without_point_in_time_source(self):
        x=check_provenance(self.receipt(point_in_time_source=False),Purpose.HISTORICAL_BACKTEST)
        self.assertIn("NOT_POINT_IN_TIME",x.failures)
    def test_naive_timestamp(self):
        x=check_provenance(self.receipt(retrieved_at=datetime(2026,11,11)),
                           Purpose.LIVE_EOD)
        self.assertIn("NAIVE_RETRIEVAL_TIMESTAMP",x.failures)
    def test_adjustment_mode_fallback(self):
        x=check_provenance(self.receipt(adjustment_mode="raw_close_fallback"),Purpose.LIVE_EOD)
        self.assertIn("ADJUSTMENT_MODE_UNVERIFIED",x.failures)

if __name__=="__main__":
    unittest.main()
