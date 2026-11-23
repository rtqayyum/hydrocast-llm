"""Phase 0b: training-only station-support screening on published observations.

No fabricated dates, no unit conversion, no daily target construction, no model.
Cohort membership uses ONLY historical training-period metadata. Validation/test
counts are descriptive (never used to select sites or hyperparameters).
"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import traceback
import zipfile

from .audit import _find_tasks, _float_ok, _missing, REQUIRED
from .paths import inside
from .util import clean_name, utc_now, write_json

SCHEMA_VERSION = 1
TRAIN_END = date(2018, 12, 31)
VAL_END = date(2021, 12, 31)
TEST_END = date(2025, 12, 31)


class Site:
    __slots__ = ('train_rows', 'train_exact', 'train_censored', 'train_yearmask',
                 'train_first', 'train_last', 'val_labels', 'test_labels')

    def __init__(self):
        self.train_rows = 0
        self.train_exact = 0
        self.train_censored = 0
        self.train_yearmask = 0
        self.train_first = None
        self.train_last = None
        self.val_labels = 0
        self.test_labels = 0


def _scan(stream, member, min_train, min_years, min_span_days):
    reader = csv.DictReader(stream)
    if not REQUIRED.issubset(reader.fieldnames or []):
        raise ValueError(f'{member}: missing required columns')
    sites = {}
    counts = Counter()
    units = Counter()
    for row in reader:
        counts['all_rows'] += 1
        sid = (row.get('wqms_id') or '').strip()
        if not sid:
            counts['missing_station'] += 1
            continue
        try:
            sampled = date.fromisoformat((row.get('dates') or '')[:10])
        except ValueError:
            counts['invalid_date'] += 1
            continue
        if sampled > TEST_END:
            counts['outside_registered_period'] += 1
            continue
        site = sites.get(sid)
        if site is None:
            site = Site()
            sites[sid] = site
        period = ('train' if sampled <= TRAIN_END else
                  'validation' if sampled <= VAL_END else 'test')
        if period == 'train':
            site.train_rows += 1
        units[(row.get('unit') or '').strip() or '<missing>'] += 1
        flag = (row.get('flag') or '').strip()
        # A left-censored label is an interval, never an observed exact value.
        censored = (flag == '<' and _float_ok(row.get('detection_limit')) and
                    float(row['detection_limit']) > 0)
        exact = (flag == '' and _missing(row.get('imputation_method')) and
                 _float_ok(row.get('obs')))
        if flag == '<' and not censored:
            counts['censored_without_valid_limit'] += 1
        if not exact and not censored:
            counts['excluded_from_usable_labels'] += 1
            continue
        counts[f'{period}_usable_rows'] += 1
        if period == 'train':
            site.train_exact += int(exact)
            site.train_censored += int(censored)
            site.train_yearmask |= 1 << (sampled.year - 1800)
            if site.train_first is None or sampled < site.train_first:
                site.train_first = sampled
            if site.train_last is None or sampled > site.train_last:
                site.train_last = sampled
            counts['train_exact'] += int(exact)
            counts['train_left_censored'] += int(censored)
        elif period == 'validation':
            site.val_labels += 1
        else:
            site.test_labels += 1
    train_candidates = 0
    candidates_with_val = 0
    candidates_with_test = 0
    candidates_with_both = 0
    candidate_train_rows = 0
    train_sites = 0
    for site in sites.values():
        count = site.train_exact + site.train_censored
        train_sites += int(count > 0)
        if (count >= min_train and bin(site.train_yearmask).count('1') >= min_years
                and site.train_first is not None and site.train_last is not None
                and (site.train_last - site.train_first).days >= min_span_days):
            train_candidates += 1
            candidate_train_rows += count
            candidates_with_val += int(site.val_labels >= 4)
            candidates_with_test += int(site.test_labels >= 4)
            candidates_with_both += int(site.val_labels >= 4 and site.test_labels >= 4)
    return {
        'counts': dict(counts), 'distinct_stations_in_file': len(sites),
        'train_sites_with_usable_labels': train_sites,
        'training_only_candidate_stations': train_candidates,
        'training_only_candidate_rows': candidate_train_rows,
        'candidates_with_4plus_validation_rows': candidates_with_val,
        'candidates_with_4plus_test_rows': candidates_with_test,
        'candidates_with_4plus_both_periods': candidates_with_both,
        'units_observed': dict(units),
        'caveats': [
            'Counts are observation rows, not distinct sampling dates or forecast-origin pairs.',
            'Cohort eligibility uses training observations only; later-period counts are diagnostic.',
            'No unit harmonization, station-alias deduplication, or catchment independence established.',
        ],
    }


def _work(task, rules):
    root_str, kind, archive_path, member, fingerprint = task
    root = Path(root_str)
    key = clean_name(Path(member).stem) + '-' + hashlib.sha256(member.encode()).hexdigest()[:12]
    shard = inside(root, f'outputs/screen/shards/{key}.json')
    log = inside(root, f'logs/workers/screen_{key}.log')
    if shard.is_file():
        try:
            old = json.loads(shard.read_text())
            if (old.get('status') == 'complete' and old.get('source_fingerprint') == fingerprint
                    and old.get('rules') == rules and old.get('schema_version') == SCHEMA_VERSION):
                with log.open('a') as f:
                    f.write(f'{utc_now()} RESUME {member}\n')
                return old, 'resumed'
        except (ValueError, OSError):
            pass
    with log.open('a') as f:
        f.write(f'{utc_now()} START {member}\n')
    try:
        if kind == 'zip':
            with zipfile.ZipFile(archive_path) as zf, zf.open(member) as data:
                with io.TextIOWrapper(data, encoding='utf-8-sig', newline='', errors='replace') as stream:
                    stats = _scan(stream, member, **rules)
        else:
            with open(archive_path, newline='', encoding='utf-8-sig', errors='replace') as stream:
                stats = _scan(stream, member, **rules)
        result = dict(stats, status='complete', member=member, rules=rules,
                      schema_version=SCHEMA_VERSION, source_fingerprint=fingerprint,
                      completed_utc=utc_now())
        write_json(shard, result)
        with log.open('a') as f:
            f.write(f'{utc_now()} DONE {member} candidates={stats["training_only_candidate_stations"]}\n')
        return result, 'computed'
    except Exception:
        with log.open('a') as f:
            f.write(f'{utc_now()} FAILED {member}\n{traceback.format_exc()}\n')
        raise


def run(root, workers=4, min_train=24, min_years=3, min_span_days=365, max_shards=None):
    if min_train < 1 or min_years < 1 or min_span_days < 0 or workers < 1:
        raise ValueError('Invalid screening parameters')
    rules = dict(min_train=min_train, min_years=min_years, min_span_days=min_span_days)
    inside(root, 'outputs/screen/shards').mkdir(parents=True, exist_ok=True)
    inside(root, 'logs/workers').mkdir(parents=True, exist_ok=True)
    tasks, source = _find_tasks(root)
    total = len(tasks)
    if max_shards is not None:
        if max_shards < 1:
            raise ValueError('max-shards must be positive')
        tasks = tasks[:max_shards]
    audit_file = inside(root, 'results/phase0_summary.json')
    audit_summary = json.loads(audit_file.read_text()) if audit_file.is_file() else {}
    # Refuse misleading screening of observations that were not successfully audited.
    if (audit_summary.get('observation_source') != source or
            audit_summary.get('failed_shards') != 0 or
            not str(audit_summary.get('status', '')).startswith('complete_')):
        raise RuntimeError('Complete the Phase 0 source audit first; source mismatch or missing audit')
    progress = inside(root, 'outputs/screen/progress.json')
    write_json(progress, dict(total_shards=len(tasks), completed_shards=0, failed_shards=0,
                              stage='screen', updated_utc=utc_now()))
    results, errors = [], []
    if tasks:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
            future_map = {executor.submit(_work, t, rules): t[3] for t in tasks}
            for future in as_completed(future_map):
                member = future_map[future]
                try:
                    result, action = future.result()
                    results.append(result)
                    print(f'SCREEN {len(results)}/{len(tasks)} {member} action={action} candidates={result["training_only_candidate_stations"]}', flush=True)
                except Exception as exc:
                    errors.append({'member': member, 'message': str(exc)})
                    print(f'ERROR SCREEN {member}: {exc}', flush=True)
                write_json(progress, dict(total_shards=len(tasks), completed_shards=len(results),
                                          failed_shards=len(errors), stage='screen', updated_utc=utc_now()))
    results.sort(key=lambda r: r['member'])
    status = ('failed' if errors else 'missing_data' if not tasks else
              'partial_debug' if max_shards is not None else 'complete')
    summary = {
        'schema_version': SCHEMA_VERSION, 'status': status, 'time_utc': utc_now(),
        'source': source, 'rules': rules, 'historical_cutoffs': {
            'train_end': str(TRAIN_END), 'validation_end': str(VAL_END), 'test_end': str(TEST_END)},
        'source_publisher_integrity_verified': audit_summary.get('publisher_integrity', {}).get('verified') is True,
        'full_release_verified': audit_summary.get('full_release', {}).get('verified') is True,
        'total_shards': total, 'completed_shards': len(results), 'failed_shards': len(errors),
        'errors': errors, 'constituents': results,
        'model_trained': False, 'ready_for_gpu_training': False,
        'note': 'Preliminary station training-support screen only. Not forecast pair eligibility or geographic evaluation.',
    }
    write_json(inside(root, 'results/phase0b_summary.json'), summary)
    report = [
        '# Phase 0b - Training-only station support screen', '',
        f'- Status: **{status}**', f'- Input: {source}',
        f'- File counts: {len(results)}/{total}',
        f'- Official lite source integrity verified by Phase 0: **{summary["source_publisher_integrity_verified"]}**',
        '- Full daily-weather release verified: **' + str(summary['full_release_verified']) + '**',
        '- This is not a forecasting or trained-model result.', '',
        '## Provisional historical periods', '',
        '- Training: through 2018-12-31',
        '- Validation coverage inspection: 2019-01-01 through 2021-12-31',
        '- Test coverage inspection: 2022-01-01 through 2025-12-31',
        '- Training-only candidate rule: >=24 clean or properly censored historical rows, >=3 training years, >=365 days training span.',
        '- Validation/test coverage does NOT determine candidate membership.', '',
        '## Constituents', '',
        '| Constituent | Training-only candidate stations | With >=4 validation rows | With >=4 test rows |',
        '|---|---:|---:|---:|',
    ]
    for item in sorted(results, key=lambda s: -s['training_only_candidate_stations']):
        report.append('| {} | {:,} | {:,} | {:,} |'.format(
            Path(item['member']).stem, item['training_only_candidate_stations'],
            item['candidates_with_4plus_validation_rows'],
            item['candidates_with_4plus_test_rows']))
    report.extend(['', '## Scientific limits', '',
                   '- Station totals across constituents are **not** unique basin/site totals.',
                   '- Same-day replicates may inflate counts; exact horizon-aligned pairs are NOT assessed.',
                   '- Sampling cadence, unit harmonization, source aliases, basin linkage, and leakage-safe splits remain unverified.',
                   '- Historical cutoffs are provisional and must be justified using train-only coverage before registration.',
                   '- Lite data is missing the full daily meteorological forcing: G0 remains closed.',
                   '- No GPU jobs or model training are authorized by this screening.', ''])
    inside(root, 'reports/PHASE0B_STATION_SUPPORT.md').write_text('\n'.join(report), encoding='utf-8')
    print('REPORT ' + str(inside(root, 'reports/PHASE0B_STATION_SUPPORT.md')), flush=True)
    return 2 if errors or not tasks else 0
