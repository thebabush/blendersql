"""Session-scoped Blender subprocess fixture.

Boots a single headless Blender, starts the HTTP server, yields a client
fixture that POSTs SQL to /query. On teardown POSTs /shutdown and waits for
the process to exit, hard-killing it if it overruns.

Skips the entire suite if no Blender executable can be located.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
FIXTURE_BLEND = TESTS_DIR / 'fixtures' / 'test_scene.blend'
BUILD_FIXTURE_PY = TESTS_DIR / 'fixtures' / 'build_fixture.py'
RUNNER_PY = TESTS_DIR / 'runner.py'
SERVER_INFO = TESTS_DIR / '.server_info.json'
# Test-local extensions root so `make test` doesn't depend on the dev symlink
# at ~/Library/Application Support/Blender/5.1/extensions/. Crucially, when
# this file lives inside a git worktree it points Blender at the worktree's
# code instead of whatever the user's live install symlink targets.
EXTENSIONS_ROOT = TESTS_DIR / '.blender_user_extensions'

sys.path.insert(0, str(REPO_ROOT))
from blendersql.cli._blender import find_blender as _find_blender  # noqa: E402
from blendersql.cli._blender import pick_free_port as _pick_port  # noqa: E402

_READY_TIMEOUT_S = 60.0
_SHUTDOWN_TIMEOUT_S = 5.0


def _ensure_extension_symlink() -> None:
    """Wire the repo into a test-local extensions tree.

    Blender's extension loader expects each extension at
    `<extensions-root>/<repo>/<addon-name>/`. We mirror that under
    `tests/.blender_user_extensions/` and let `BLENDER_USER_EXTENSIONS`
    point Blender at it. The symlink target is `REPO_ROOT/blendersql`
    (the addon package dir inside this checkout, which is also the
    git worktree root when running under a worktree), so tests always
    exercise the code in this checkout — not whatever the user's live
    `~/Library/.../user_default/blendersql` happens to point at.
    """
    user_default = EXTENSIONS_ROOT / 'user_default'
    user_default.mkdir(parents=True, exist_ok=True)
    link = user_default / 'blendersql'
    target = str(REPO_ROOT / 'blendersql')
    # Recreate the symlink only if missing or pointing elsewhere — keeps the
    # check fast and avoids racing other test runs.
    if link.is_symlink():
        if os.readlink(link) == target:
            return
        link.unlink()
    elif link.exists():
        # A stray non-symlink path — refuse to clobber, surface the conflict.
        raise RuntimeError(f'expected {link} to be a symlink or absent; refusing to overwrite')
    link.symlink_to(target, target_is_directory=True)


def _build_fixture(blender: str) -> None:
    if FIXTURE_BLEND.exists():
        return
    cmd = [
        blender,
        '--background',
        '--factory-startup',
        '--python',
        str(BUILD_FIXTURE_PY),
        '--',
        str(FIXTURE_BLEND),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0 or not FIXTURE_BLEND.exists():
        raise RuntimeError(
            f'failed to build fixture .blend:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}'
        )


def _http_get(url: str, timeout: float = 1.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method='GET')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _http_post(url: str, body: str, timeout: float = 30.0) -> tuple[int, bytes]:
    data = body.encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def _wait_ready(base_url: str, proc: subprocess.Popen[str], deadline: float) -> None:
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stdout = ''
            stderr = ''
            with contextlib.suppress(Exception):
                stdout, stderr = proc.communicate(timeout=1)
            raise RuntimeError(
                f'blender exited with code {proc.returncode} before becoming ready.\n'
                f'stdout:\n{stdout}\nstderr:\n{stderr}'
            )
        if not SERVER_INFO.exists():
            time.sleep(0.1)
            continue
        try:
            status, _ = _http_get(base_url + '/status', timeout=1.0)
            if status == 200:
                return
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            last_err = exc
        time.sleep(0.1)
    raise RuntimeError(f'blender server never became ready (last error: {last_err})')


@pytest.fixture(scope='session')
def blender_server() -> Iterator[dict[str, Any]]:
    blender = _find_blender()
    if blender is None:
        pytest.skip('blender executable not found (set $BLENDER or install at default location)')

    _build_fixture(blender)
    SERVER_INFO.unlink(missing_ok=True)
    _ensure_extension_symlink()

    port = _pick_port()
    base_url = f'http://127.0.0.1:{port}'
    env = os.environ.copy()
    env['BLENDERSQL_TEST_PORT'] = str(port)
    env['BLENDERSQL_TEST_INFO'] = str(SERVER_INFO)
    # Redirect Blender's extension search at our test-local tree so the runner
    # picks up THIS checkout, not the user's installed dev symlink.
    env['BLENDER_USER_EXTENSIONS'] = str(EXTENSIONS_ROOT)

    cmd = [
        blender,
        '--background',
        '--factory-startup',
        '--python-use-system-env',
        str(FIXTURE_BLEND),
        '--python',
        str(RUNNER_PY),
    ]
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        _wait_ready(base_url, proc, time.monotonic() + _READY_TIMEOUT_S)
    except BaseException:
        with contextlib.suppress(Exception):
            proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=2)
        raise

    info = json.loads(SERVER_INFO.read_text())
    info['base_url'] = base_url
    yield info

    with contextlib.suppress(Exception):
        _http_post(base_url + '/shutdown', '', timeout=2.0)

    try:
        proc.wait(timeout=_SHUTDOWN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2.0)

    SERVER_INFO.unlink(missing_ok=True)


class Client:
    """Thin HTTP client wrapping POST /query."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def query(self, sql: str, timeout: float = 30.0) -> dict[str, Any]:
        try:
            _, body = _http_post(self.base_url + '/query', sql, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read()
        return json.loads(body.decode('utf-8'))

    def status(self) -> dict[str, Any]:
        _, body = _http_get(self.base_url + '/status', timeout=2.0)
        return json.loads(body.decode('utf-8'))


@pytest.fixture(scope='session')
def client(blender_server: dict[str, Any]) -> Client:
    return Client(blender_server['base_url'])


def pytest_report_header(config: pytest.Config) -> list[str]:
    _ = config
    blender = _find_blender()
    return [f'blender: {blender or "NOT FOUND"}']
