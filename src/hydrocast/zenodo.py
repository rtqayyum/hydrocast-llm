"""Download only explicitly chosen Caravan-Qual lite components.

Never equate this with the full dataset. Full archive needs separate source audit.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .paths import inside
from .util import md5_file, utc_now, write_json

RECORD_ID = '21337532'
RECORD_URL = f'https://zenodo.org/api/records/{RECORD_ID}'
SMALL_FILES = ('Caravan-Qual_zarr_variables.csv', 'wqms_site_info.csv',
               'caravan_site_info.csv', 'Caravan-Qual_licenses.zip',
               'Caravan-Qual_linkages.parquet')
WQ_FILE = 'wqms-csv.zip'


def read_remote_manifest(timeout=40):
    req = urllib.request.Request(RECORD_URL, headers={'User-Agent': 'HydroCast-LLM/0.1 (academic audit)'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        record = json.load(resp)
    files = {}
    for f in record.get('files', []):
        key = f['key']
        files[key] = {
            'size': f.get('size'),
            'checksum': f.get('checksum'),
            'url': f.get('links', {}).get('content') or f'{RECORD_URL}/files/{key}/content'
        }
    if WQ_FILE not in files:
        raise RuntimeError('Zenodo file manifest does not include wqms-csv.zip; stop and review')
    return {'record_id': RECORD_ID, 'retrieved_utc': utc_now(), 'files': files,
            'note': 'LITE version. Daily meteorological forcing is NOT included.'}


def _download_one(root, filename, metadata):
    dest = inside(root, Path('data/raw/lite') / filename)
    partial = inside(root, Path('data/raw/lite') / (filename + '.part'))
    check = metadata['checksum'] or ''
    if ':' not in check:
        raise ValueError(f'Missing checksum for {filename}: refusing unverified download')
    method, checksum = check.split(':', 1)
    if method.lower() != 'md5':
        raise ValueError(f'Unsupported publisher checksum for {filename}: {method}')
    if dest.exists():
        if md5_file(dest) == checksum:
            return {'file': filename, 'action': 'verified_existing', 'bytes': dest.stat().st_size}
        raise RuntimeError(f'Existing file checksum mismatch; not overwriting {dest}')

    offset = partial.stat().st_size if partial.exists() else 0
    headers = {'User-Agent': 'HydroCast-LLM/0.1 (academic audit)'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    req = urllib.request.Request(metadata['url'], headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        status = getattr(resp, 'status', resp.getcode())
        if offset and status != 206:
            raise RuntimeError('Server does not support HTTP Range resume; partial file retained')
        if offset and not resp.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise RuntimeError('Unexpected Content-Range; refusing potentially corrupted append')
        with partial.open('ab' if offset else 'wb') as f:
            while True:
                b = resp.read(4 * 1024 * 1024)
                if not b:
                    break
                f.write(b)
                f.flush()
    if metadata.get('size') is not None and partial.stat().st_size != metadata['size']:
        raise RuntimeError(f'Incomplete download {filename}: {partial.stat().st_size} bytes; .part retained')
    if md5_file(partial) != checksum:
        raise RuntimeError(f'Checksum mismatch for {filename}; .part retained for investigation')
    os.replace(partial, dest)
    return {'file': filename, 'action': 'downloaded_verified', 'bytes': dest.stat().st_size}


def fetch(root, include_observations=False):
    manifest = read_remote_manifest()
    write_json(inside(root, 'data_manifest/zenodo_lite_v1.1.json'), manifest)
    required = list(SMALL_FILES) + ([WQ_FILE] if include_observations else [])
    results = []
    for filename in required:
        if filename not in manifest['files']:
            raise RuntimeError(f'Missing required file {filename} in Zenodo API response')
        r = _download_one(root, filename, manifest['files'][filename])
        results.append(r)
        print(f'DOWNLOAD {r["file"]} {r["action"]} bytes={r["bytes"]}', flush=True)
    write_json(inside(root, 'results/download_lite.json'), {
        'status': 'lite_components_verified', 'retrieved_utc': utc_now(), 'files': results,
        'full_release_verified': False,
        'daily_weather_available': False
    })
    return results
