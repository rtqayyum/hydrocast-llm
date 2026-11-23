"""Register Phase 0 source inside the project's own virtual environment.

No network or package manager is needed; never write to shared Anaconda.
"""
import sys
import sysconfig
from pathlib import Path


def register(root):
    root = Path(root).resolve()
    expected_venv = (root / '.venv').resolve()
    actual_prefix = Path(sys.prefix).resolve()
    if actual_prefix != expected_venv:
        raise RuntimeError('Refusing to register source outside the project-local .venv')
    site = Path(sysconfig.get_path('purelib')).resolve()
    if site != expected_venv and expected_venv not in site.parents:
        raise RuntimeError('Refusing to write outside the project-local .venv')
    src = (root / 'src').resolve()
    if src.parent != root or not (src / 'hydrocast' / 'cli.py').is_file():
        raise RuntimeError('Source directory is missing or not inside the project')
    path = site / 'hydrocast_local_src.pth'
    path.write_text(str(src) + '\n', encoding='utf-8')
    print('LOCAL_PACKAGE_REGISTERED', path, flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('Usage: python scripts/register_local_source.py <absolute-project-root>')
    register(sys.argv[1])
