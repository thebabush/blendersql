"""Asserts that auto-generated skill content is in sync with the live registry.

Calls the same regen script CI / pre-commit would call. Fails if a marker
section would change — fix by running `python scripts/regen_skills.py --write`
and committing the result.

This test spawns a headless Blender via the regen script (the same way the
script's own subprocess does), so it's on the slow end (~1-2s of Blender
boot per run). There's no slow-test marker convention in this repo, so it
just runs alongside everything else; the existing soak test is heavier.

Exit-code contract (mirrors `scripts/regen_skills.py`):

* 0 — clean, no drift.
* 1 — drift detected; fix is mechanical (`--write` + commit).
* 2 — setup error (Blender missing, fixture absent, bad marker, …). The
       fix is environmental, not mechanical — we report it differently so
       the dev doesn't waste a `--write` on a broken setup.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_EXTENSIONS_ROOT = Path(__file__).resolve().parent / '.blender_user_extensions'


def test_skill_autogen_blocks_are_in_sync() -> None:
    # Forward BLENDER_USER_EXTENSIONS at the test-local extensions tree (set
    # up by conftest's session fixture) so the regen script's Blender child
    # picks up THIS checkout's code, not whatever the user's default install
    # symlink at ~/Library/Application Support/Blender/<v>/extensions/user_default/
    # happens to target. Without this, drift in this worktree vs. the main
    # checkout reports as false-positive regen failures.
    env = os.environ.copy()
    if _EXTENSIONS_ROOT.exists():
        env['BLENDER_USER_EXTENSIONS'] = str(_EXTENSIONS_ROOT)
    result = subprocess.run(
        [sys.executable, 'scripts/regen_skills.py', '--check'],
        cwd=str(_REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode == 0:
        return
    if result.returncode == 2:
        # Environmental — Blender boot failed, fixture missing, marker typo, …
        raise AssertionError(
            'regen_skills could not run — Blender / CLI / fixture / marker '
            'setup error (exit code 2). Fix the environment before re-running; '
            '`--write` will not help.\n\n'
            f'--- stdout ---\n{result.stdout}\n'
            f'--- stderr ---\n{result.stderr}'
        )
    # Treat any other non-zero exit (typically 1) as drift.
    raise AssertionError(
        'skill autogen drift detected — run '
        '`python scripts/regen_skills.py --write` and commit the changes.\n\n'
        f'--- stdout ---\n{result.stdout}\n'
        f'--- stderr ---\n{result.stderr}'
    )
