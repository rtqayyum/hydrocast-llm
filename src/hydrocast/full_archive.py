"""Human-review gated verification of full archive file manifest.

User-supplied checksums must refer to actual downloaded files; no inference from file names.
"""
import csv
import json
from .paths import inside
from .util import sha256_file

REQUIRED_ROLES = {'water_quality', 'daily_weather', 'site_metadata', 'licenses'}


def verify(root):
    manifest_path = inside(root, 'data_manifest/FULL_ARCHIVE_MANIFEST.csv')
    review_path = inside(root, 'data_manifest/LICENSE_REVIEW.json')
    response = {'verified': False, 'reason': None, 'files': 0, 'roles': [], 'license_review_complete': False}
    if not manifest_path.is_file():
        response['reason'] = 'No user-verified full archive manifest. Lite never qualifies.'
        return response
    if not review_path.is_file():
        response['reason'] = 'Missing independent license review.'
        return response
    review = json.loads(review_path.read_text(encoding='utf-8'))
    response['license_review_complete'] = review.get('review_complete') is True
    if not response['license_review_complete']:
        response['reason'] = 'Source licenses have not been reviewed.'
        return response
    roles = set()
    with manifest_path.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            rel = row.get('path', '').strip()
            expected = row.get('sha256', '').strip().lower()
            role = row.get('role', '').strip()
            if not rel.startswith('data/raw/full/'):
                response['reason'] = f'Full manifest entry outside data/raw/full: {rel}'
                return response
            target = inside(root, rel)
            if not target.is_file() or len(expected) != 64 or sha256_file(target) != expected:
                response['reason'] = f'File missing or SHA256 mismatch: {rel}'
                return response
            roles.add(role)
            response['files'] += 1
    response['roles'] = sorted(roles)
    if not REQUIRED_ROLES.issubset(roles):
        response['reason'] = f'Missing required full roles: {sorted(REQUIRED_ROLES - roles)}'
        return response
    response.update(verified=True, reason='Local file hashes and license-review flag verified; scientific content still needs audit.')
    return response
