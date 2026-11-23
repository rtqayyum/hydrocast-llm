"""Safely confine every project read/write to a single explicit root."""
from pathlib import Path
import os

DEFAULT_ROOT = Path('/home/tariq.qayyum/hpc/hydrocast-llm')
DIRS = ('data/raw/lite', 'data/raw/full', 'data_manifest', 'logs', 'logs/workers',
        'results', 'outputs', 'outputs/audit/shards', 'figures', 'reports',
        'checkpoints', 'tmp', 'cache', 'models')


def root_path(override=None):
    root = Path(override or os.environ.get('HYDROCAST_ROOT') or DEFAULT_ROOT).expanduser().resolve()
    if not root.is_absolute() or root == Path('/'):
        raise ValueError('Invalid project root')
    return root


def inside(root, relative):
    """Fail closed on absolute paths, .., and symlinks leaving the root."""
    relative = Path(relative)
    if relative.is_absolute():
        raise ValueError(f'Absolute project-relative path: {relative}')
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes project root: {relative}')
    return target


def initialize(root):
    root = root.resolve()
    for d in DIRS:
        inside(root, d).mkdir(parents=True, exist_ok=True)
    return root
