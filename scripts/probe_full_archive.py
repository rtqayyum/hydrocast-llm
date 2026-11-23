#!/usr/bin/env python3
"""Read-only probe of the OFFICIAL Caravan-Qual full-release landing page.

No dataset downloads, no guesswork about download URLs and no change to G0.
Only outputs written to our project-local reports/results/outputs directories.
"""
import json
import shutil
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path('/home/tariq.qayyum/hpc/hydrocast-llm')
DOI = 'https://doi.org/10.24416/UU01-39ZXC4'
MAX_BYTES = 4 * 1024 * 1024


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.label = []

    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href:
            self.links.append((self.href, ' '.join(' '.join(self.label).split())[:120]))
            self.href = None
            self.label = []


def find_links(html, base):
    parser = Links()
    parser.feed(html)
    all_links = []
    for href, label in parser.links:
        url = urljoin(base, href.strip())
        p = urlparse(url)
        if p.scheme != 'https' or not p.hostname:
            continue
        looks_like_file = p.path.lower().endswith(
            ('.zip', '.tar', '.gz', '.xz', '.nc', '.csv', '.parquet', '.zarr', '.json'))
        if looks_like_file or 'download' in label.lower():
            all_links.append({'url': url, 'label': label})
    return list({x['url']: x for x in all_links}.values())


def main():
    root = ROOT.resolve()
    if root != ROOT or not root.is_dir():
        raise SystemExit('Project root missing/unsafe: ' + str(ROOT))
    for name in ('reports', 'results', 'outputs/full_probe'):
        (root / name).mkdir(parents=True, exist_ok=True)
    space = shutil.disk_usage(root)
    result = {'doi': DOI, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'unreachable', 'landing_url': None, 'download_links': [],
              'free_space_gib_not_quota': round(space.free / 1024**3, 2),
              'full_dataset_downloaded': False, 'g0_passed': False,
              'error': None}
    try:
        request = Request(DOI, headers={'User-Agent': 'HydroCast-LLM research full-data inventory'})
        with urlopen(request, timeout=25) as response:
            landing = response.geturl()
            loc = urlparse(landing)
            if loc.scheme != 'https' or loc.hostname not in ('public.yoda.uu.nl', 'doi.org'):
                raise RuntimeError('Unexpected landing redirect host: ' + str(loc.hostname))
            ctype = response.headers.get('Content-Type', '').lower()
            if 'html' not in ctype:
                raise RuntimeError('Not an HTML landing page: ' + ctype[:100])
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError('Landing response exceeded 4 MiB safety limit')
            html = raw.decode('utf-8', errors='replace')
            (root / 'outputs/full_probe/landing.html').write_text(html, encoding='utf-8')
            result['status'] = 'landing_reachable'
            result['landing_url'] = landing
            result['download_links'] = find_links(html, landing)
    except (HTTPError, URLError, RuntimeError, OSError, TimeoutError, ValueError) as exc:
        result['error'] = str(exc)[:800]
    (root / 'results/full_archive_probe.json').write_text(
        json.dumps(result, indent=2) + '\n', encoding='utf-8')
    lines = ['# Full Caravan-Qual access check', '',
             '- Official DOI: ' + DOI,
             '- Status: **' + result['status'] + '**',
             '- Redirect: ' + str(result['landing_url']),
             '- Free filesystem space, GiB (NOT quota): ' + str(result['free_space_gib_not_quota']),
             '- Links visible in HTML: ' + str(len(result['download_links'])),
             '- Full archive downloaded: **False**', '- Full-data gate G0: **False**',
             '- Error: ' + str(result['error']), '',
             '## Candidate URLs (NOT verified dataset files)', '']
    lines += ['- ' + x['url'] + ' — ' + x['label'] for x in result['download_links'][:100]]
    if not result['download_links']:
        lines += ['No archive links found. The Yoda page might require a browser or JavaScript.']
    lines += ['', '## Next action', '',
              'Check filenames, byte sizes, license terms, available HPC quota and publisher checksums.',
              'Do not start a large transfer until these are confirmed.', '']
    (root / 'reports/FULL_ARCHIVE_ACCESS.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({k: result[k] for k in
          ('status', 'landing_url', 'free_space_gib_not_quota', 'error')}, indent=2))
    print('DOWNLOAD_LINKS_FOUND', len(result['download_links']))
    print('REPORT', root / 'reports/FULL_ARCHIVE_ACCESS.md')
    return 0 if result['status'] == 'landing_reachable' else 2


if __name__ == '__main__':
    sys.exit(main())
