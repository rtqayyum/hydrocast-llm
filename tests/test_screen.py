"""Software-only fixtures: never substitute for real river data."""
import csv
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from hydrocast.audit import run as audit_run
from hydrocast.paths import initialize, inside
from hydrocast.screen import run as screen_run


COLUMNS = ['wqms_id', 'dates', 'obs', 'unit', 'flag', 'detection_limit', 'imputation_method', 'streamflow']


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hc-screen-', dir=os.environ.get('TMPDIR'))
        self.root = initialize(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def make_zip(self):
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(COLUMNS)
        for i in range(36):
            day = date(2015, 1, 1) + timedelta(days=40 * i)
            writer.writerow(['station_a', day.isoformat(), '2', 'mg/l', '', '', '', ''])
        for i in range(5):
            writer.writerow(['station_a', f'2020-01-{i+1:02d}', '0.5', 'mg/l', '<', '1', '', ''])
            writer.writerow(['station_a', f'2023-01-{i+1:02d}', '3', 'mg/l', '', '', '', ''])
        for i in range(30):
            writer.writerow(['station_b', f'2023-05-{i+1:02d}', '2', 'mg/l', '', '', '', ''])
        writer.writerow(['station_c', '2017-05-01', '0.5', 'mg/l', '<', '', 'LOD/2', ''])
        writer.writerow(['station_c', '2017-06-01', '5', 'mg/l', '!', '', '', ''])
        writer.writerow(['station_c', '2017-07-01', '5', 'mg/l', '', '', 'interpolated', ''])
        with zipfile.ZipFile(inside(self.root, 'data/raw/lite/wqms-csv.zip'), 'w') as zf:
            zf.writestr('wqms-csv/NO3N.csv', buf.getvalue())

    def test_screen_train_only_and_resume(self):
        self.make_zip()
        self.assertEqual(audit_run(self.root, workers=1), 0)
        self.assertEqual(screen_run(self.root, workers=2), 0)
        result = json.loads(inside(self.root, 'results/phase0b_summary.json').read_text())
        r = result['constituents'][0]
        self.assertEqual(r['training_only_candidate_stations'], 1)
        self.assertEqual(r['candidates_with_4plus_validation_rows'], 1)
        self.assertEqual(r['candidates_with_4plus_test_rows'], 1)
        self.assertEqual(r['counts']['censored_without_valid_limit'], 1)
        self.assertEqual(r['counts']['excluded_from_usable_labels'], 3)
        self.assertFalse(result['ready_for_gpu_training'])
        shard = next(inside(self.root, 'outputs/screen/shards').glob('*.json'))
        before = shard.read_bytes()
        self.assertEqual(screen_run(self.root, workers=1), 0)
        self.assertEqual(shard.read_bytes(), before)

    def test_screen_requires_phase0_audit(self):
        self.make_zip()
        with self.assertRaises(RuntimeError):
            screen_run(self.root)


if __name__ == '__main__':
    unittest.main()
