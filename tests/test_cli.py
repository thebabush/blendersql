"""Integration tests for the standalone `blendersql` CLI.

Each test spawns its own headless Blender (slower than the shared-server tests
in the rest of the suite — that is expected for an end-to-end CLI). Skipped
entirely if no Blender executable can be found.
"""

from __future__ import annotations

import json
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT))

from fixtures.expected import EXPECTED  # noqa: E402

from cli._blender import find_blender  # noqa: E402

if find_blender() is None:
    pytest.skip('blender executable not found', allow_module_level=True)

CLI = REPO_ROOT / 'cli' / 'blendersql.py'
FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'test_scene.blend'
_TIMEOUT = 120


def _run_cli(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        **kwargs,
    )


def _manifest_version() -> str:
    for line in (REPO_ROOT / 'blender_manifest.toml').read_text().splitlines():
        line = line.strip()
        if line.startswith('version'):
            return line.partition('=')[2].strip().strip('"').strip("'")
    raise AssertionError('version not found in manifest')


def test_version() -> None:
    result = _run_cli('--version')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == _manifest_version()


def test_query_ok() -> None:
    result = _run_cli('-s', str(FIXTURE), '-q', 'SELECT COUNT(*) FROM objects')
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload['ok'] is True
    assert payload['rows'][0][0] == EXPECTED['objects']
    assert set(payload) >= {'ok', 'columns', 'rows', 'row_count', 'duration_ms'}


def test_query_bad_sql() -> None:
    result = _run_cli('-s', str(FIXTURE), '-q', 'SELECT * FROM no_such_table')
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload['ok'] is False


def _parse_json_stream(text: str) -> list[dict]:
    decoder = json.JSONDecoder()
    out: list[dict] = []
    idx = 0
    text = text.strip()
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        obj, idx = decoder.raw_decode(text, idx)
        out.append(obj)
    return out


def test_file_mode(tmp_path: Path) -> None:
    sql_file = tmp_path / 'q.sql'
    sql_file.write_text('SELECT COUNT(*) FROM meshes;\nSELECT COUNT(*) FROM objects;\n')
    result = _run_cli('-s', str(FIXTURE), '-f', str(sql_file))
    assert result.returncode == 0, result.stderr
    payloads = _parse_json_stream(result.stdout)
    assert len(payloads) == 2
    assert payloads[-1]['ok'] is True
    assert payloads[-1]['rows'][0][0] == EXPECTED['objects']


def test_interactive() -> None:
    result = _run_cli('-s', str(FIXTURE), '-i', input='SELECT 1\n.tables\n.q\n')
    assert result.returncode == 0, result.stderr
    assert '| 1 |' in result.stdout or '1 row(s)' in result.stdout
    assert 'objects' in result.stdout


def test_http_mode() -> None:
    proc = subprocess.Popen(
        [sys.executable, str(CLI), '-s', str(FIXTURE), '--http', '0'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None and proc.stderr is not None
        url = None
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            if 'HTTP server:' in line:
                url = line.split('HTTP server:')[1].strip()
                break
        assert url, f'no URL printed; stderr: {proc.stderr.read()}'
        with urllib.request.urlopen(url + '/status', timeout=5) as resp:
            body = json.loads(resp.read().decode())
        assert body['status'] == 'ok'
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_write_roundtrip(tmp_path: Path) -> None:
    blend_copy = tmp_path / 'scene.blend'
    shutil.copy(FIXTURE, blend_copy)
    result = _run_cli(
        '-s',
        str(blend_copy),
        '-w',
        '-q',
        "INSERT INTO objects(name, type) VALUES ('CliWriteTest', 'EMPTY')",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['ok'] is True

    result2 = _run_cli(
        '-s',
        str(blend_copy),
        '-q',
        "SELECT COUNT(*) FROM objects WHERE name='CliWriteTest'",
    )
    assert result2.returncode == 0, result2.stderr
    assert json.loads(result2.stdout)['rows'][0][0] == 1


def test_missing_source() -> None:
    result = _run_cli('-q', 'SELECT 1')
    assert result.returncode != 0


def test_missing_blend_file() -> None:
    result = _run_cli('-s', '/nonexistent/file.blend', '-q', 'SELECT 1')
    assert result.returncode == 2
