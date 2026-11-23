"""Small no-dependency helpers for robust resumable processing."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def sha256_file(path, chunk_size=4 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()


def md5_file(path, chunk_size=4 * 1024 * 1024):
    h = hashlib.md5()  # noqa: S324 - comparing publisher checksum, not for security
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()


def clean_name(name):
    import re
    return re.sub(r'[^a-zA-Z0-9_.-]+', '_', name).strip('._')[:80] or 'unnamed'
