"""Command line for Phase 0. Dependencies: Python standard library only."""
import argparse
import json
import os
import platform
import sys
from pathlib import Path

from . import __version__
from . import audit
from .paths import initialize, inside, root_path
from .util import utc_now, write_json
from . import zenodo
from . import screen


def preflight(root):
    checks = {
        'root_absolute': root.is_absolute(),
        'root_is_directory': root.is_dir(),
        'python_version_ok': sys.version_info >= (3, 9),
        'virtualenv_local_when_active': (sys.prefix == sys.base_prefix or
            Path(sys.prefix).resolve() == inside(root, '.venv')),
        'project_root_inside_expected_tree': (str(root) == str(root_path(os.environ.get('HYDROCAST_EXPECTED_ROOT') or root))),
        'source_directory_exists': inside(root, 'data/raw').is_dir(),
        'logs_directory_exists': inside(root, 'logs').is_dir(),
        'result_directory_exists': inside(root, 'results').is_dir(),
    }
    response = {'version': __version__, 'time_utc': utc_now(), 'python': platform.python_version(),
                'root': str(root), 'checks': checks, 'pass': all(checks.values())}
    write_json(inside(root, 'results/preflight.json'), response)
    print(json.dumps(response, indent=2), flush=True)
    return 0 if response['pass'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='HydroCast-LLM: auditable Phase 0 (no training)')
    parser.add_argument('--root', default=os.environ.get('HYDROCAST_ROOT'),
                        help='Absolute project root (default is dedicated HPC directory)')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init', help='Initialize local project directories')
    sub.add_parser('preflight', help='Check paths, Python and local environment')
    fetch = sub.add_parser('fetch-lite', help='Fetch checked official lite metadata, optionally observations')
    fetch.add_argument('--observations', action='store_true',
                       help='Explicitly download 641 MB water-quality zip (still NOT full daily weather)')
    auditor = sub.add_parser('audit', help='Stream per-constituent archive; checkpoint/restart each shard')
    auditor.add_argument('--workers', type=int, default=8)
    auditor.add_argument('--max-shards', type=int, help='DEBUG ONLY: process first N constituents')
    screening = sub.add_parser('screen', help='Phase 0b training-only station support screen (no models)')
    screening.add_argument('--workers', type=int, default=4)
    screening.add_argument('--max-shards', type=int, help='Debug-only subset of constituents')
    args = parser.parse_args(argv)
    root = root_path(args.root)
    initialize(root)
    if args.command == 'init':
        print(f'PROJECT_DIR {root}', flush=True)
        return 0
    if args.command == 'preflight':
        return preflight(root)
    if args.command == 'fetch-lite':
        zenodo.fetch(root, include_observations=args.observations)
        return 0
    if args.command == 'audit':
        if args.workers < 1 or (args.max_shards is not None and args.max_shards < 1):
            parser.error('workers and max-shards must be positive')
        return audit.run(root, workers=args.workers, max_shards=args.max_shards)
    if args.command == 'screen':
        return screen.run(root, workers=args.workers, max_shards=args.max_shards)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'FATAL {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
