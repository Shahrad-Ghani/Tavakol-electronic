"""Transfer the actual live data/state from an existing V4.0.6.1 installation.

Safe-by-default --dry-run; --apply backs up destination conflicts before overwrite.
Never modifies the source installation or copies any source code.
"""
from __future__ import annotations
import argparse
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, timezone

ASSET_FOLDERS = [
    'metadata', 'runtime_state', 'Final', 'datasheets', 'phase3_outputs',
    'products', 'work', 'output', 'input', 'input_PN', 'PN_input',
    'ready_for_upload', 'audit_history', 'logs',
]
PRIVATE_FILES = ['.env', 'proxies.txt']


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.digest()


def plan(source, dest):
    updates = []
    for dirname in ASSET_FOLDERS:
        folder = source / dirname
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob('*')):
            if path.is_file() and path.name != '.gitkeep':
                relative = path.relative_to(source)
                updates.append((path, dest / relative, relative))
    for name in PRIVATE_FILES:
        if (source/name).is_file():
            updates.append((source/name, dest/name, Path(name)))
    return updates


def main():
    parser = argparse.ArgumentParser(description='Transfer runtime data from live Integrated V4.0.6.1, never overwrite code')
    parser.add_argument('--source', type=Path, required=True, help='Old ACTIVE installation root')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true', help='Copy data after backing up different destination files')
    group.add_argument('--dry-run', action='store_true', help='Preview only (default)')
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    dest = Path(__file__).resolve().parent
    if not source.is_dir() or source == dest:
        parser.error('Source must be a real DIFFERENT installation folder')
    if not (source/'metadata').is_dir() or not (source/'run_ui.py').is_file():
        parser.error('Source does not look like an Integrated installation')
    jobs = plan(source,dest)
    changed = [(a,b,c) for a,b,c in jobs if not b.is_file() or digest(a) != digest(b)]
    conflicts = sum(1 for a,b,c in changed if b.exists())
    print(f'SOURCE: {source}\nDESTINATION: {dest}')
    print(f'Candidate files: {len(jobs)} | To copy: {len(changed)} | Different target files: {conflicts}')
    print('IMPORTANT: Private .env and proxies.txt are copied locally, NEVER distributed in ZIP.')
    if not args.apply:
        print('DRY RUN: No files changed. Re-run with --apply to transfer.')
        for a,b,c in changed[:20]: print('  COPY',c)
        if len(changed) > 20: print(f'  ... and {len(changed)-20} others')
        return
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = dest/'altimate_upgrade_backups'/stamp
    applied = 0
    for src, target, relative in changed:
        if target.exists():
            prev = backup/relative
            prev.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,prev)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,target)
        applied += 1
    print(f'APPLIED: {applied} file transfers. Backups: {backup if conflicts else "not needed"}')
    print('Original installation was NOT modified. Start with a small controlled pilot.')

if __name__ == '__main__':
    main()
