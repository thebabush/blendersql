#!/usr/bin/env python3
"""Download the apsw wheels BlenderSQL vendors and rewrite the manifest's wheels list.

Keep _APSW_VERSION in sync with the apsw pin in pyproject.toml.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

_APSW_VERSION = '3.53.1.0'

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WHEELS_DIR = _REPO_ROOT / 'wheels'
_MANIFEST = _REPO_ROOT / 'blender_manifest.toml'

# Each slot: (label, regex on the wheel filename). Multiple matches -> highest sort wins,
# which picks the newer manylinux glibc tag (manylinux_2_28 > manylinux2014).
_SLOTS: list[tuple[str, re.Pattern[str]]] = [
    ('macOS arm64', re.compile(r'-cp313-cp313-macosx_\d+_\d+_arm64\.whl$')),
    ('macOS x86_64', re.compile(r'-cp313-cp313-macosx_\d+_\d+_x86_64\.whl$')),
    ('Linux x86_64', re.compile(r'-cp313-cp313-manylinux[._\d]*_x86_64\.whl$')),
    ('Linux aarch64', re.compile(r'-cp313-cp313-manylinux[._\d]*_aarch64\.whl$')),
    ('Windows x86_64', re.compile(r'-cp313-cp313-win_amd64\.whl$')),
]


def _pypi_urls(version: str) -> list[dict]:
    url = f'https://pypi.org/pypi/apsw/{version}/json'
    with urllib.request.urlopen(url) as resp:
        return json.load(resp)['urls']


def _select_wheels(urls: list[dict]) -> list[tuple[str, dict]]:
    selected: list[tuple[str, dict]] = []
    for label, pattern in _SLOTS:
        matches = [u for u in urls if pattern.search(u['filename'])]
        if not matches:
            raise SystemExit(f'no apsw wheel matched slot: {label}')
        best = max(matches, key=lambda u: u['filename'])
        selected.append((label, best))
    return selected


def _download(entry: dict) -> Path:
    dest = _WHEELS_DIR / entry['filename']
    if dest.exists():
        print(f'  have   {dest.name}')
        return dest
    print(f'  fetch  {dest.name}')
    with urllib.request.urlopen(entry['url']) as resp:
        dest.write_bytes(resp.read())
    return dest


def _rewrite_manifest(wheel_names: list[str]) -> None:
    text = _MANIFEST.read_text()
    block = 'wheels = [\n'
    block += ''.join(f'    "./wheels/{name}",\n' for name in wheel_names)
    block += ']'
    new_text, n = re.subn(r'wheels = \[.*?\]', block, text, count=1, flags=re.DOTALL)
    if n != 1:
        raise SystemExit('could not locate the wheels = [...] array in blender_manifest.toml')
    _MANIFEST.write_text(new_text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--version', default=_APSW_VERSION, help='apsw version (default: %(default)s)'
    )
    args = parser.parse_args()

    _WHEELS_DIR.mkdir(exist_ok=True)
    print(f'apsw {args.version} wheels:')
    selected = _select_wheels(_pypi_urls(args.version))
    for label, entry in selected:
        print(f'  {label:14s} -> {entry["filename"]}')
    print('downloading:')
    names = sorted(_download(entry).name for _, entry in selected)
    _rewrite_manifest(names)
    print(f'manifest updated: {len(names)} wheels')
    return 0


if __name__ == '__main__':
    sys.exit(main())
