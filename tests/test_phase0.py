"""Synthetic unit tests ONLY; never interpreted as observed river results."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from hydrocast.audit import run
from hydrocast.paths import initialize, inside
from hydrocast.util import write_json

COLUMNS = ['wqms_id', 'dates', 'obs', 'unit', 'flag', 'detection_limit', 'imputation_method', 'streamflow']
ROWS = [
    ['wqms_1', '2018-01-01', '1.0', 'mg/l', '', '', '', '10'],
    ['wqms_1', '2018-02-01', '0.5', 'mg/l', '<', '1.0', 'LOD/2', ''],
    ['wqms_2', '2019-03-01', '25', 'mg/l', '*', '', '', '20'],
    ['wqms_3', '2020-01-01', '', 'mg/l', '', '', '', ''],
]


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hc-', dir=os.environ.get('TMPDIR'))
        self.root = initialize(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def make_zip(self, name='NO3N.csv'):
        from io import StringIO
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(COLUMNS)
        writer.writerows(ROWS)
        with zipfile.ZipFile(inside(self.root, 'data/raw/lite/wqms-csv.zip'), 'w') as zf:
            zf.writestr('wqms-csv/' + name, buf.getvalue())

    def test_synthetic_audit_and_resume(self):
        self.make_zip()
        self.assertEqual(run(self.root, workers=2), 0)
        result = json.loads(inside(self.root, 'results/phase0_summary.json').read_text())
        self.assertEqual(result['status'], 'complete_lite_source')
        self.assertEqual(result['observation_rows'], 4)
        self.assertEqual(result['left_censored'], 1)
        self.assertEqual(result['other_flagged'], 1)
        self.assertFalse(result['full_release']['verified'])
        self.assertFalse(result['ready_for_gpu_training'])
        shard_path = next(inside(self.root, 'outputs/audit/shards').glob('*.json'))
        first_bytes = shard_path.read_bytes()
        self.assertEqual(run(self.root, workers=2), 0)
        self.assertEqual(shard_path.read_bytes(), first_bytes)
        self.assertTrue(inside(self.root, 'reports/PHASE0_AUDIT.md').is_file())

    def test_missing_data_is_not_success(self):
        self.assertEqual(run(self.root, workers=1), 2)
        summary = json.loads(inside(self.root, 'results/phase0_summary.json').read_text())
        self.assertEqual(summary['status'], 'blocked_missing_observations')

    def test_root_escapes_and_symlink_escapes_rejected(self):
        with self.assertRaises(ValueError):
            inside(self.root, '../other')
        with self.assertRaises(ValueError):
            inside(self.root, '/tmp/out')
        extra = Path(self.tmp.name).parent
        (self.root / 'escape').symlink_to(extra)
        with self.assertRaises(ValueError):
            inside(self.root, 'escape/outfile')

    def test_invalid_shard_schema_is_failed(self):
        with zipfile.ZipFile(inside(self.root, 'data/raw/lite/wqms-csv.zip'), 'w') as zf:
            zf.writestr('wqms-csv/BAD.csv', 'site,value\n1,2\n')
        self.assertEqual(run(self.root, workers=1), 2)
        summary = json.loads(inside(self.root, 'results/phase0_summary.json').read_text())
        self.assertEqual(summary['status'], 'failed')
        self.assertEqual(summary['failed_shards'], 1)

    def test_full_requires_real_checked_manifest(self):
        self.make_zip()
        write_json(inside(self.root, 'data_manifest/LICENSE_REVIEW.json'), {'review_complete': True})
        self.assertEqual(run(self.root, workers=1), 0)
        summary = json.loads(inside(self.root, 'results/phase0_summary.json').read_text())
        self.assertFalse(summary['full_release']['verified'])


if __name__ == '__main__':
    unittest.main()
