#!/usr/bin/env python3
"""HPC-only, resumable Caravan-Qual full-release transfer from Utrecht Yoda.

Uses the publisher's public landing-page file manifest, not a guessed ZIP URL.
No files download on login nodes; data stay inside the dedicated project tree.
This does NOT complete license review, scientific validation, or the full-data G0.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path("/home/tariq.qayyum/hpc/hydrocast-llm")
LANDING = "https://public.yoda.uu.nl/geo/UU01/1U1Q13.html"
HOST = "public.yoda.uu.nl"
LIMIT_HTML = 4 * 1024 * 1024
LIMIT_MANIFEST = 128 * 1024 * 1024
CHUNK = 8 * 1024 * 1024
GIB = 1024 ** 3


class DownloadError(RuntimeError):
    pass


class YodaLanding(HTMLParser):
    def __init__(self):
        super().__init__()
        self.view = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("id") == "viewContents":
            self.view = (attrs.get("href"), attrs.get("data-random-id"))


def require_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.username or parsed.password:
        raise DownloadError("Unexpected publisher URL/redirect: " + url[:200])
    return url


def safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 1024:
        raise DownloadError("Invalid empty or oversize manifest name")
    if "\\" in name or "\x00" in name or name.startswith("/"):
        raise DownloadError("Unsafe manifest path: " + repr(name[:200]))
    pure = PurePosixPath(name)
    parts = name.rstrip("/").split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise DownloadError("Unsafe manifest segments: " + repr(name[:200]))
    if any(p.startswith("~") for p in parts):
        raise DownloadError("Unsafe manifest segment: " + repr(name[:200]))
    return str(pure)


def parse_page(html, landing_url):
    reader = YodaLanding()
    reader.feed(html)
    if not reader.view or not all(reader.view):
        raise DownloadError("Yoda viewContents link or data-random-id missing from landing HTML")
    href, random_id = reader.view
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", random_id):
        raise DownloadError("Invalid Yoda publication identifier")
    base = require_url(urljoin(landing_url, href))
    manifest = require_url(urljoin(landing_url, "./" + random_id + "-manifest.json"))
    return base.rstrip("/"), manifest


def publisher_get(url, max_bytes, is_html=False):
    request = Request(require_url(url), headers={
        "User-Agent": "HydroCast-LLM/0.3 (scientific reproducibility; metadata inventory)",
        "X-Requested-With": "XMLHttpRequest",
    })
    with urlopen(request, timeout=90) as response:
        require_url(response.geturl())
        content_type = response.headers.get("Content-Type", "").lower()
        if response.status != 200:
            raise DownloadError("Metadata HTTP " + str(response.status))
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise DownloadError("Metadata exceeded configured byte limit")
        if is_html and (b"<html" not in body[:4096].lower() and b"<!doctype" not in body[:4096].lower()):
            raise DownloadError("Publisher did not return recognizable HTML (possibly a bot challenge)")
        if not is_html and ("html" in content_type or b"<html" in body[:256].lower()):
            raise DownloadError("Publisher returned HTML rather than its JSON manifest")
        return body


def parse_manifest(raw):
    try:
        records = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise DownloadError("Yoda manifest is not JSON: " + str(exc)) from exc
    if not isinstance(records, list) or not records:
        raise DownloadError("Yoda manifest must be a nonempty JSON list")
    entries, seen = [], set()
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get("name"), str):
            raise DownloadError("Invalid Yoda manifest entry")
        name = rec["name"]
        safe_name(name)
        directory = name.endswith("/")
        key = name.rstrip("/")
        if key in seen:
            raise DownloadError("Duplicate archive entry " + key[:200])
        seen.add(key)
        size = rec.get("size")
        if size is not None:
            if isinstance(size, bool) or not str(size).isdigit():
                raise DownloadError("Invalid manifest byte size " + key[:200])
            size = int(size)
        if len(entries) >= 1000000:
            raise DownloadError("Manifest exceeds one million entries")
        entries.append({"name": name, "directory": directory, "size": size})
    return entries


def get_metadata(root):
    # Yoda's published JS builds file URLs from viewContents and the sibling
    # {data-random-id}-manifest.json; see official Yoda download.js.
    raw_page = publisher_get(LANDING, LIMIT_HTML, is_html=True)
    base, url = parse_page(raw_page.decode("utf-8", "replace"), LANDING)
    raw_manifest = publisher_get(url, LIMIT_MANIFEST)
    entries = parse_manifest(raw_manifest)
    sha = hashlib.sha256(raw_manifest).hexdigest()
    manifest_path = root / "data_manifest" / "yoda_full_publisher_manifest.json"
    manifest_path.write_bytes(raw_manifest)
    return base, url, sha, entries


def output_json(path, data):
    tmp = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def inventory(root):
    base, url, sha, entries = get_metadata(root)
    files = [e for e in entries if not e["directory"]]
    dirs = sum(e["directory"] for e in entries)
    sizes = [e["size"] for e in files if e["size"] is not None]
    disk_free = shutil.disk_usage(root).free
    summary = {
        "status": "publisher_manifest_discovered",
        "source_landing": LANDING, "base": base, "manifest_url": url,
        "manifest_sha256": sha, "entries": len(entries), "files": len(files),
        "directories": dirs, "files_with_declared_sizes": len(sizes),
        "declared_bytes_partial": sum(sizes),
        "all_file_sizes_known": len(sizes) == len(files),
        "filesystem_free_gib_not_quota": round(disk_free / GIB, 2),
        "download_started": False, "full_archive_verified": False,
    }
    output_json(root / "results/full_yoda_inventory.json", summary)
    lines = [
        "# Full Caravan-Qual Yoda publisher manifest", "",
        "- Published landing page: " + LANDING,
        "- Manifest URL: " + url,
        "- Manifest SHA256: " + sha,
        "- Files: " + str(len(files)),
        "- Directories: " + str(dirs),
        "- Publisher-declared sizes for files: " + str(len(sizes)) + "/" + str(len(files)),
        "- Sum of known file sizes (GiB): " + str(round(sum(sizes) / GIB, 3)),
        "- Filesystem free space (GiB, **not your individual quota**): " +
          str(round(disk_free / GIB, 2)), "",
        "## First 40 published names", "",
    ]
    lines.extend("- " + e["name"] + (" (" + str(e["size"]) + " bytes)" if e["size"] is not None else "")
                 for e in files[:40])
    lines.extend(["", "## Integrity notice", "",
                  "The manifest is source metadata. File checksums and source licenses still need review.",
                  "Do not treat the observation lite archive as the full release.",
                  "Use a separate Slurm download job; never download large files on login nodes.", ""])
    (root / "reports/FULL_YODA_INVENTORY.md").write_text("\n".join(lines), encoding="utf-8")
    print("INVENTORY files={0} directories={1} size_known={2}/{0} SHA256={3}".format(
        len(files), dirs, len(sizes), sha), flush=True)
    print("REPORT", root / "reports/FULL_YODA_INVENTORY.md", flush=True)
    return summary


def check_compute():
    if not os.environ.get("SLURM_JOB_ID"):
        raise DownloadError("Network access requires a submitted Slurm job (SLURM_JOB_ID missing)")
    node = socket.gethostname().split(".")[0].lower()
    if node.startswith("login"):
        raise DownloadError("Refusing publisher network access on login node " + node)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_completed(path):
    completed = {}
    if not path.is_file():
        return completed
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # truncated final line after crash
            if (isinstance(event, dict) and isinstance(event.get("name"), str)
                    and isinstance(event.get("sha256"), str)):
                completed[event["name"]] = event
    return completed


def append_complete(ledger, entry):
    with open(ledger, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def stream_one(url, dest, expected, allowance):
    """Download into .part with safe HTTP Range retry. Never truncate final data."""
    part = dest.with_name(dest.name + ".part")
    offset = part.stat().st_size if part.is_file() else 0
    headers = {"User-Agent": "HydroCast-LLM/0.3 (research dataset transfer)",
               "X-Requested-With": "XMLHttpRequest", "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = "bytes={}-".format(offset)
    request = Request(require_url(url), headers=headers)
    with urlopen(request, timeout=180) as response:
        require_url(response.geturl())
        status = response.status
        if status not in (200, 206):
            raise DownloadError("Unexpected data HTTP status " + str(status))
        ctype = response.headers.get("Content-Type", "").lower()
        if "html" in ctype:
            raise DownloadError("Publisher returned HTML (not a dataset file)")
        if offset and status == 206:
            range_value = response.headers.get("Content-Range", "")
            match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", range_value)
            if match is None or int(match.group(1)) != offset:
                raise DownloadError("Invalid Content-Range when resuming: " + range_value)
        else:
            # No Range support: safely restart from byte zero, keeping final files untouched.
            offset = 0
        content_len = response.headers.get("Content-Length")
        if content_len is not None and (not content_len.isdigit() or int(content_len) < 0):
            raise DownloadError("Invalid Content-Length")
        advertised = (offset + int(content_len)) if content_len else None
        if expected is not None and advertised is not None and advertised != expected:
            raise DownloadError("Publisher manifest size differs from HTTP transfer size")
        if advertised is not None and advertised > allowance:
            raise DownloadError("Transfer would exceed HC_MAX_DOWNLOAD_GIB; increase only after quota check")
        mode = "ab" if offset else "wb"
        received = 0
        with part.open(mode) as writer:
            first = True
            while True:
                block = response.read(CHUNK)
                if not block:
                    break
                if first and offset == 0 and block[:2048].lower().lstrip().startswith(
                        (b"<!doctype html", b"<html")):
                    raise DownloadError("Received HTML challenge rather than dataset file")
                first = False
                received += len(block)
                if offset + received > allowance:
                    raise DownloadError("Download byte cap reached (partial file retained)")
                if shutil.disk_usage(dest.parent).free < 10 * GIB:
                    raise DownloadError("Filesystem space fell below 10 GiB; partial retained")
                writer.write(block)
        if content_len is not None and received != int(content_len):
            raise DownloadError("Truncated HTTP transfer; partial retained")
    final_bytes = part.stat().st_size
    if expected is not None and final_bytes != expected:
        raise DownloadError("Final size mismatched publisher manifest; partial retained")
    digest = sha256_file(part)
    part.replace(dest)
    return {"size": final_bytes, "sha256": digest}


def perform_download(root, cap_gib):
    if cap_gib < 1:
        raise DownloadError("HC_MAX_DOWNLOAD_GIB must be >= 1")
    recorded = root / "results/full_yoda_inventory.json"
    if not recorded.is_file():
        raise DownloadError("First run the Slurm inventory job; no pinned manifest found")
    prior = json.loads(recorded.read_text(encoding="utf-8"))
    base, url, sha, entries = get_metadata(root)
    if (prior.get("manifest_sha256") != sha or prior.get("base") != base or
            prior.get("manifest_url") != url):
        raise DownloadError("Yoda publisher manifest changed since inventory; rerun inventory")
    files = [e for e in entries if not e["directory"]]
    target_root = (root / "data/raw/full/yoda_original").resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    ledger = root / "outputs/full_download/complete.jsonl"
    finished = load_completed(ledger)
    known = sum(x["size"] for x in files if x["size"] is not None)
    cap = int(cap_gib * GIB)
    if all(e["size"] is not None for e in files) and known > cap:
        raise DownloadError("Publisher total exceeds HC_MAX_DOWNLOAD_GIB; verify individual HPC quota")
    present = sum(path.stat().st_size for path in target_root.rglob("*") if path.is_file())
    if present > cap:
        raise DownloadError("Existing Yoda files exceed configured transfer cap")
    completed = 0
    files_skipped = 0
    for i, entry in enumerate(files, 1):
        name = entry["name"]
        dest = (target_root / safe_name(name)).resolve()
        if not dest.is_relative_to(target_root):
            raise DownloadError("Manifest path escaped download root")
        dest.parent.mkdir(parents=True, exist_ok=True)
        old = finished.get(name)
        if dest.is_file():
            if (old and dest.stat().st_size == old.get("size") and
                    sha256_file(dest) == old.get("sha256")):
                completed += 1
                files_skipped += 1
                print("RESUME", i, len(files), name, flush=True)
                continue
            raise DownloadError("Untracked existing file; refusing to overwrite " + name)
        part = dest.with_name(dest.name + ".part")
        # Reserve existing files + each partial file, not compressed/deduplicated pseudo-quota.
        present = sum(x.stat().st_size for x in target_root.rglob("*") if x.is_file())
        allowance = cap - (present - (part.stat().st_size if part.is_file() else 0))
        if allowance <= 0:
            raise DownloadError("Configured download cap reached, retaining all partial data")
        source_url = require_url(base + "/" + quote(name, safe="/"))
        for retry in range(3):
            try:
                result = stream_one(source_url, dest, entry["size"], allowance)
                break
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                if retry == 2:
                    raise DownloadError("File exhausted retries: " + name + ": " + str(exc))
                delay = 2 ** (retry + 1)
                print("RETRY", name, str(exc)[:150], "sleep", delay, flush=True)
                time.sleep(delay)
        event = {"name": name, "source_url": source_url, "size": result["size"],
                 "sha256": result["sha256"], "manifest_sha256": sha,
                 "verification": "transport_sha256_only_no_publisher_checksum"}
        append_complete(ledger, event)
        completed += 1
        print("DOWNLOADED", i, len(files), name, "bytes", result["size"], flush=True)
        output_json(root / "outputs/full_download/progress.json",
                    {"total_files": len(files), "completed_files": completed,
                     "skipped_files": files_skipped, "manifest_sha256": sha,
                     "publisher_checksums_verified": False})
    summary = {"status": "transfer_complete_unreviewed", "completed_files": completed,
               "expected_files": len(files), "manifest_sha256": sha,
               "publisher_checksums_verified": False, "licenses_reviewed": False,
               "scientific_data_verified": False, "full_release_G0_passed": False,
               "path": str(target_root)}
    output_json(root / "results/full_yoda_download.json", summary)
    print("SUCCESS full publisher file transfer completed; G0 still requires scientific and license audit")
    print("SUMMARY", root / "results/full_yoda_download.json")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Official Yoda manifest inventory / HPC-only resume transfer")
    parser.add_argument("mode", choices=("inventory", "download"))
    parser.add_argument("--max-download-gib", type=int, default=500,
                        help="Cumulative project transfer cap; adjust only after checking actual quota")
    args = parser.parse_args(argv)
    check_compute()
    root = ROOT.resolve()
    if not root.is_dir() or root != ROOT:
        raise DownloadError("Expected dedicated HydroCast project directory is missing")
    for name in ("data_manifest", "data/raw/full/yoda_original", "results",
                 "reports", "outputs/full_download", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    if args.mode == "inventory":
        inventory(root)
    else:
        perform_download(root, args.max_download_gib)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (DownloadError, HTTPError, URLError, OSError, ValueError) as exc:
        print("FATAL", type(exc).__name__, str(exc), file=sys.stderr, flush=True)
        sys.exit(2)
