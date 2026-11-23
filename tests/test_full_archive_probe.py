"""Offline synthetic HTML test for the full-archive access probe."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/probe_full_archive.py'
SPEC = importlib.util.spec_from_file_location('hydrocast_full_probe', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FullProbeTests(unittest.TestCase):
    def test_extracts_file_links_not_javascript(self):
        html = ('<a href="daily-weather.zip">Download weather</a>'
                '<a href="javascript:void(0)">Ignore</a>'
                '<a href="https://example.com/a.nc">NetCDF</a>')
        links = MODULE.find_links(html, 'https://public.yoda.uu.nl/folder/')
        self.assertEqual(len(links), 2)
        self.assertTrue(links[0]['url'].endswith('daily-weather.zip'))

    def test_empty_page_does_not_fabricate_urls(self):
        self.assertEqual(MODULE.find_links('<div>Loading...</div>',
                                           'https://public.yoda.uu.nl/'), [])


if __name__ == '__main__':
    unittest.main()
