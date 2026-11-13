import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reconcile import reconcile, write_report

DB='symbol,date,close,adj_close,volume\nMSFT,2026-11-11,100,,1000\nTSM,2026-11-11,200,200,1000\nANET,2026-11-11,10,9,1000\n'
REF='symbol,date,close,adj_close,volume,source_id\nMSFT,2026-11-11,100,99,1000,ref-1\nTSM,2026-11-11,200,198,1000,ref-1\nANET,2026-11-11,10,9,1000,ref-1\n'

class ReconTest(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.a=Path(self.d.name)/'db.csv'
        self.b=Path(self.d.name)/'ref.csv'
        self.a.write_text(DB)
        self.b.write_text(REF)

    def r(self):
        return reconcile(self.a,self.b,as_of='2026-11-11')

    def test_classifications(self):
        self.assertEqual([r['status'] for r in self.r()['rows']], [
            'MATCHED_NUMERICALLY_UNCERTIFIED',
            'PROPOSE_ADJ_CLOSE_REVIEW',
            'ADJUSTED_CLOSE_CONFLICT',
        ])

    def test_hashes_and_uncertified(self):
        r=self.r()
        self.assertEqual(len(r['db_sha256']),64)
        self.assertFalse(r['reference_is_independently_certified'])

    def test_duplicate_rows_rejected(self):
        self.a.write_text(DB+'MSFT,2026-11-11,100,,1\n')
        with self.assertRaises(ValueError):
            self.r()

    def test_unknown_provider(self):
        self.b.write_text(REF.replace('ref-1',''))
        self.assertIn('UNATTRIBUTED_REFERENCE',[r['status'] for r in self.r()['rows']])

    def test_future_rows_excluded(self):
        self.assertEqual(reconcile(self.a,self.b,as_of='2026-11-10')['rows'],[])

    def test_missing_ref(self):
        self.b.write_text(REF.replace('MSFT,2026-11-11,100,99,1000,ref-1\n',''))
        self.assertIn('NO_REFERENCE_EVIDENCE',[r['status'] for r in self.r()['rows']])

    def test_raw_mismatch(self):
        self.b.write_text(REF.replace('MSFT,2026-11-11,100,99','MSFT,2026-11-11,101,99'))
        self.assertIn('RAW_CLOSE_CONFLICT',[r['status'] for r in self.r()['rows']])

    def test_output(self):
        p=Path(self.d.name)/'report.json'
        write_report(self.r(),p)
        self.assertIn('reference_sha256',p.read_text())


    def test_volume_mismatch_is_not_certified(self):
        self.b.write_text(REF.replace('MSFT,2026-11-11,100,99,1000,ref-1',
                                      'MSFT,2026-11-11,100,99,500,ref-1'))
        statuses = [r['status'] for r in self.r()['rows']]
        self.assertIn('VOLUME_CONFLICT_REVIEW_SPLITS', statuses)

    def test_fractional_volume_is_not_usable(self):
        self.b.write_text(REF.replace('MSFT,2026-11-11,100,99,1000,ref-1',
                                      'MSFT,2026-11-11,100,99,99.4,ref-1'))
        self.assertIn('INVALID_REFERENCE', [r['status'] for r in self.r()['rows']])

    def test_negative_tolerance_rejected(self):
        with self.assertRaises(ValueError):
            reconcile(self.a, self.b, as_of='2026-11-11', tolerance=-0.5)

    def test_extra_csv_fields_rejected(self):
        self.a.write_text(DB + 'MSFT,2026-11-12,101,99,1000,unexpected\\n')
        with self.assertRaises(ValueError):
            self.r()

if __name__=='__main__':
    unittest.main()
