"""Synthetic metadata and safety tests; NEVER download real observations."""
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock
import unittest

SRC = Path(__file__).resolve().parents[1] / "scripts" / "yoda_full.py"
SPEC = importlib.util.spec_from_file_location("hc_yoda_full", SRC)
yoda = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(yoda)


class YodaManifestTests(unittest.TestCase):
    def test_official_manifest_convention(self):
        html = ('<html><a id="viewContents" '
                'href="https://public.yoda.uu.nl/geo/UU01/1U1Q13/" '
                'data-random-id="1U1Q13">View</a></html>')
        base, manifest_url = yoda.parse_page(html, yoda.LANDING)
        self.assertEqual(base, "https://public.yoda.uu.nl/geo/UU01/1U1Q13")
        self.assertEqual(manifest_url,
                         "https://public.yoda.uu.nl/geo/UU01/1U1Q13-manifest.json")

    def test_missing_view_contents_never_guesses_download_url(self):
        with self.assertRaises(yoda.DownloadError):
            yoda.parse_page('<html><a href="#">Download as ZIP</a></html>', yoda.LANDING)

    def test_parse_and_size_manifest(self):
        raw = json.dumps([{"name": "Caravan-Qual.zarr/"},
                          {"name": "Caravan-Qual.zarr/zarr.json", "size": 45},
                          {"name": "weather/daily_1980.nc"}]).encode()
        entries = yoda.parse_manifest(raw)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[1]["size"], 45)
        self.assertTrue(entries[0]["directory"])
        self.assertIsNone(entries[2]["size"])

    def test_reject_unsafe_names_and_duplicates(self):
        for name in ("../escape", "/absolute", "a//b", "a/../b", "x\\y", "."):
            with self.subTest(name=name):
                with self.assertRaises(yoda.DownloadError):
                    yoda.safe_name(name)
        with self.assertRaises(yoda.DownloadError):
            yoda.parse_manifest(b'[{"name":"foo"},{"name":"foo"}]')
        with self.assertRaises(yoda.DownloadError):
            yoda.parse_manifest(b'[{"name":"foo","size":-1}]')
        with self.assertRaises(yoda.DownloadError):
            yoda.parse_manifest(b'{"not":"a list"}')

    def test_refuse_external_urls(self):
        for url in ("http://public.yoda.uu.nl/geo/", "https://evil.invalid/x",
                    "https://public.yoda.uu.nl.evil.invalid/x"):
            with self.subTest(url=url):
                with self.assertRaises(yoda.DownloadError):
                    yoda.require_url(url)

    def test_refuse_login_node_or_non_slurm_execution(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(yoda.DownloadError):
                yoda.check_compute()
        with mock.patch.dict(os.environ, {"SLURM_JOB_ID": "123"}):
            with mock.patch.object(yoda.socket, "gethostname", return_value="login-2"):
                with self.assertRaises(yoda.DownloadError):
                    yoda.check_compute()

    def test_ledger_recovers_from_truncated_last_line(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "complete.jsonl"
            p.write_text('{"name":"ok","sha256":"abc","size":123}\n{"name":')
            result = yoda.load_completed(p)
            self.assertIn("ok", result)
            self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
