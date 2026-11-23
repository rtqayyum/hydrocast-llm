"""Checkpointed, per-constituent, streaming Caravan-Qual observation census.

Supports official wqms-csv.zip without extracting it and the extracted wqms-csv/
directory. No zero-filling, label interpolation or censored-value substitution.
"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import time
import traceback
import zipfile

from .full_archive import verify as verify_full
from .paths import inside
from .util import clean_name, md5_file, utc_now, write_json

REQUIRED = {'wqms_id', 'dates', 'obs', 'unit', 'flag', 'detection_limit', 'imputation_method', 'streamflow'}


def _missing(value):
    return value is None or value.strip().lower() in ('', 'nan', 'na', 'null', 'none')


def _float_ok(v):
    try:
        num = float(v)
        return num == num and abs(num) != float('inf')
    except (TypeError, ValueError):
        return False


def _summarize_stream(stream, member):
    reader = csv.DictReader(stream)
    columns = set(reader.fieldnames or [])
    if not REQUIRED.issubset(columns):
        raise RuntimeError(f'{member}: missing official columns {sorted(REQUIRED - columns)}')
    counts = Counter()
    units = Counter()
    years = Counter()
    stations = Counter()
    first = '9999-99-99'
    last = ''
    for row in reader:
        counts['rows'] += 1
        site = (row.get('wqms_id') or '').strip()
        if site:
            stations[site] += 1
        else:
            counts['missing_site'] += 1
        date = (row.get('dates') or '').strip()[:10]
        if len(date) == 10 and date[:4].isdigit():
            if date < first:
                first = date
            if date > last:
                last = date
            years[date[:4]] += 1
        else:
            counts['missing_or_invalid_date'] += 1
        if _float_ok(row.get('obs')):
            counts['numeric_obs'] += 1
        else:
            counts['missing_or_nonfinite_obs'] += 1
        flag = (row.get('flag') or '').strip()
        if flag == '<':
            counts['left_censored'] += 1
            if not _float_ok(row.get('detection_limit')):
                counts['censored_missing_detection_limit'] += 1
        elif flag:
            counts['other_flagged'] += 1
        else:
            counts['unflagged'] += 1
        if not _missing(row.get('imputation_method')):
            counts['original_imputation_marked'] += 1
        if _float_ok(row.get('streamflow')):
            counts['numeric_same_day_streamflow'] += 1
        unit = (row.get('unit') or '').strip() or '<missing>'
        units[unit] += 1
    return {
        'counts': dict(counts), 'unit_counts': dict(units),
        'observation_year_counts': dict(years),
        'distinct_stations': len(stations),
        'stations_ge_10_obs': sum(n >= 10 for n in stations.values()),
        'stations_ge_24_obs': sum(n >= 24 for n in stations.values()),
        'first_date': None if first == '9999-99-99' else first,
        'last_date': last or None,
        'note': 'Minimum count is not proof of forecast eligibility or consistent units.'
    }


def _audit_one(task):
    root_string, source_type, source_path, member, fingerprint = task
    root = Path(root_string)
    slug = clean_name(Path(member).stem)
    identifier = hashlib.sha256(member.encode('utf-8')).hexdigest()[:12]
    stem = f'{slug}-{identifier}'
    shard = inside(root, f'outputs/audit/shards/{stem}.json')
    log_path = inside(root, f'logs/workers/{stem}.log')
    if shard.exists():
        try:
            done = json.loads(shard.read_text(encoding='utf-8'))
            if done.get('fingerprint') == fingerprint and done.get('status') == 'complete':
                with log_path.open('a', encoding='utf-8') as log:
                    log.write(f'{utc_now()} RESUME previously complete {member}\n')
                return done, 'resumed'
        except (ValueError, OSError):
            pass
    with log_path.open('a', encoding='utf-8') as log:
        log.write(f'{utc_now()} START {member}\n')
    try:
        if source_type == 'zip':
            with zipfile.ZipFile(source_path) as zf:
                with zf.open(member, 'r') as raw:
                    with io.TextIOWrapper(raw, encoding='utf-8-sig', newline='', errors='replace') as f:
                        result = _summarize_stream(f, member)
        else:
            with open(source_path, newline='', encoding='utf-8-sig', errors='replace') as f:
                result = _summarize_stream(f, member)
        result.update(member=member, fingerprint=fingerprint, status='complete', completed_utc=utc_now())
        write_json(shard, result)
        with log_path.open('a', encoding='utf-8') as log:
            log.write(f'{utc_now()} DONE {member} rows={result["counts"].get("rows", 0)}\n')
        return result, 'computed'
    except Exception:
        with log_path.open('a', encoding='utf-8') as log:
            log.write(f'{utc_now()} FAILED {member}\n{traceback.format_exc()}\n')
        raise


def _find_tasks(root):
    # Prefer a full release per-constituent archive if present; do not silently
    # union full and lite duplicate records.
    possibilities = [inside(root, 'data/raw/full/wqms-csv.zip'),
                     inside(root, 'data/raw/full/wqms-csv'),
                     inside(root, 'data/raw/lite/wqms-csv.zip'),
                     inside(root, 'data/raw/lite/wqms-csv')]
    for src in possibilities:
        if src.is_file() and zipfile.is_zipfile(src):
            with zipfile.ZipFile(src) as zf:
                entries = [item for item in zf.infolist() if item.filename.lower().endswith('.csv') and not item.is_dir()]
            # Ensure no source data ZIP unexpectedly smuggles paths outside logical namespace.
            tasks = []
            for entry in entries:
                if '..' in Path(entry.filename).parts:
                    raise ValueError(f'Unsafe ZIP member: {entry.filename}')
                fingerprint = f'zip:{src.stat().st_size}:{src.stat().st_mtime_ns}:{entry.CRC}:{entry.file_size}'
                tasks.append((str(root), 'zip', str(src), entry.filename, fingerprint))
            return tasks, str(src.relative_to(root))
        if src.is_dir():
            entries = sorted(src.rglob('*.csv'))
            tasks = []
            for path in entries:
                stat = path.stat()
                fingerprint = f'file:{stat.st_size}:{stat.st_mtime_ns}'
                tasks.append((str(root), 'csv', str(path), str(path.relative_to(src)), fingerprint))
            return tasks, str(src.relative_to(root))
    return [], None


def _csv_metadata(root):
    result = {}
    for name in ('wqms_site_info.csv', 'caravan_site_info.csv', 'Caravan-Qual_zarr_variables.csv'):
        path = next((p for p in (inside(root, 'data/raw/full/' + name),
                                 inside(root, 'data/raw/lite/' + name)) if p.is_file()), None)
        if not path:
            result[name] = {'present': False}
            continue
        with path.open(newline='', encoding='utf-8-sig', errors='replace') as f:
            reader = csv.DictReader(f)
            cols = reader.fieldnames or []
            rows = 0
            categories = Counter()
            for row in reader:
                rows += 1
                if name.endswith('zarr_variables.csv'):
                    categories[(row.get('category') or '<unknown>')] += 1
            result[name] = {'present': True, 'rows': rows, 'columns': cols,
                            'category_counts': dict(categories), 'path': str(path.relative_to(root))}
    return result


def _compact_report(summary):
    lines = [
        '# HydroCast Phase 0 - Data Inventory', '',
        f'- Audit time UTC: {summary["audit_utc"]}',
        f'- Status: **{summary["status"]}**',
        f'- Source: {summary["observation_source"] or "NONE"}',
        f'- Constituents read: {summary["completed_shards"]}/{summary["total_shards"]}',
        f'- Observation rows counted: {summary["observation_rows"]:,}',
        f'- Below-detection records: {summary["left_censored"]:,}',
        f'- Other flagged records: {summary["other_flagged"]:,}',
        f'- Full release gate G0: **{summary["full_release"]["verified"]}**',
        f'- G0 explanation: {summary["full_release"]["reason"]}',
        f'- Lite file publisher integrity: {summary["publisher_integrity"]["verified"]}', '',
        '## Important limitations', '',
        '- A lite-source count DOES NOT establish full daily weather availability.',
        '- Counts of all constituents do not establish daily predictability.',
        '- The raw `obs` field can already be substituted for a censored result; no model must treat it as exact truth.',
        '- This stage does not create models or paper-quality validation results.',
        '- The independent scientific unit is a catchment, not an observation row.', '',
        '## Counts by constituent', '',
        '| Constituent | Rows | Stations | Below detection | From | To |',
        '|---|---:|---:|---:|---|---|',
    ]
    for item in summary['constituents']:
        c = item.get('counts', {})
        lines.append(f'| {Path(item["member"]).stem} | {c.get("rows", 0):,} | {item["distinct_stations"]:,} | '
                     f'{c.get("left_censored", 0):,} | {item.get("first_date") or "-"} | {item.get("last_date") or "-"} |')
    lines += ['', '## Source conditions', '',
              'Full dataset: https://doi.org/10.24416/UU01-39ZXC4',
              'Lite-only archive: https://zenodo.org/records/21337532',
              'Source-license review is required before redistribution.', '']
    return '\n'.join(lines)


def run(root, workers=8, max_shards=None):
    start = time.monotonic()
    full = verify_full(root)
    tasks, source = _find_tasks(root)
    total = len(tasks)
    if max_shards is not None:
        tasks = tasks[:max_shards]
    results = []
    errors = []
    metadata = _csv_metadata(root)
    publisher_integrity = {'verified': False, 'reason': 'No matching publisher record and checksum verified'}
    lite_manifest_path = inside(root, 'data_manifest/zenodo_lite_v1.1.json')
    if source == 'data/raw/lite/wqms-csv.zip' and lite_manifest_path.is_file():
        try:
            published = json.loads(lite_manifest_path.read_text(encoding='utf-8'))
            check = published['files']['wqms-csv.zip']['checksum']
            if published.get('record_id') == '21337532' and check.startswith('md5:'):
                actual = md5_file(inside(root, source))
                publisher_integrity = {'verified': actual == check.split(':', 1)[1],
                                       'reason': 'Local source matched official lite MD5' if actual == check.split(':', 1)[1] else 'Publisher MD5 mismatch'}
        except (KeyError, ValueError, OSError, TypeError) as exc:
            publisher_integrity = {'verified': False, 'reason': f'Could not validate publisher checksum: {exc}'}
    progress = inside(root, 'outputs/audit/progress.json')
    for_start = {'total_shards': len(tasks), 'completed_shards': 0, 'failed_shards': 0,
                 'start_utc': utc_now(), 'mode': 'partial_debug' if max_shards is not None else 'all_available'}
    write_json(progress, for_start)
    if tasks:
        with ProcessPoolExecutor(max_workers=max(1, min(workers, len(tasks)))) as pool:
            jobs = {pool.submit(_audit_one, task): task[3] for task in tasks}
            for fut in as_completed(jobs):
                member = jobs[fut]
                try:
                    value, action = fut.result()
                    results.append(value)
                    print(f'PROGRESS {len(results)}/{len(tasks)} member={member} action={action} rows={value["counts"].get("rows", 0)}', flush=True)
                except Exception as exc:
                    errors.append({'member': member, 'error': str(exc)})
                    print(f'ERROR worker member={member}: {exc}', flush=True)
                write_json(progress, dict(for_start, completed_shards=len(results),
                                          failed_shards=len(errors), last_update_utc=utc_now()))
    results.sort(key=lambda r: r['member'])
    status = ('failed' if errors else 'blocked_missing_observations' if not tasks
              else 'partial_debug_only' if max_shards is not None
              else 'complete_full_source' if source and source.startswith('data/raw/full/')
              else 'complete_lite_source')
    summary = {
        'schema_version': 1, 'audit_utc': utc_now(), 'duration_seconds': round(time.monotonic()-start, 2),
        'status': status, 'observation_source': source, 'total_shards': total,
        'completed_shards': len(results), 'failed_shards': len(errors), 'errors': errors,
        'observation_rows': sum(i['counts'].get('rows', 0) for i in results),
        'left_censored': sum(i['counts'].get('left_censored', 0) for i in results),
        'other_flagged': sum(i['counts'].get('other_flagged', 0) for i in results),
        'metadata': metadata, 'full_release': full, 'constituents': results,
        'publisher_integrity': publisher_integrity,
        'data_authenticity': 'verified_published_lite' if publisher_integrity['verified'] else 'unverified',
        'synthetic_data_excluded_from_science': 'unknown_until_source_verification',
        'model_trained': False,
        'ready_for_gpu_training': False,
        'blocker': 'Require full data, daily weather, verified licenses, split design and baseline gate before GPU training.'
    }
    write_json(inside(root, 'results/phase0_summary.json'), summary)
    inside(root, 'reports/PHASE0_AUDIT.md').write_text(_compact_report(summary), encoding='utf-8')
    print(f'REPORT {inside(root, "reports/PHASE0_AUDIT.md")}', flush=True)
    print(f'SUMMARY {inside(root, "results/phase0_summary.json")}', flush=True)
    return 2 if errors or not tasks else 0
