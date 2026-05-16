"""Asserts that auto-generated skill content is in sync with the live registry.

Calls the same regen script CI / pre-commit would call. Fails if a marker
section would change — fix by running `python scripts/regen_skills.py --write`
and committing the result.

This test spawns a headless Blender via the regen script (the same way the
script's own subprocess does), so it's on the slow end (~1-2s of Blender
boot per run). There's no slow-test marker convention in this repo, so it
just runs alongside everything else; the existing soak test is heavier.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def test_skill_autogen_blocks_are_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, 'scripts/regen_skills.py', '--check'],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        'skill autogen drift detected — run '
        '`python scripts/regen_skills.py --write` and commit the changes.\n\n'
        f'--- stdout ---\n{result.stdout}\n'
        f'--- stderr ---\n{result.stderr}'
    )
