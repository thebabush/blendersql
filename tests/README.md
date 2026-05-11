# BlenderSQL tests

`pytest tests/ -v` boots a headless Blender once per session, starts the HTTP
server, and runs the suite against it.

The harness locates Blender in this order:

1. `$BLENDER` environment variable
2. `blender` on `$PATH`
3. `/Applications/Blender.app/Contents/MacOS/Blender` (macOS default)

If none of those exist the suite is skipped at module level.

The fixture `.blend` (`tests/fixtures/test_scene.blend`) is rebuilt
deterministically by `tests/fixtures/build_fixture.py` on first run; delete
it to regenerate. Expected row counts live in `tests/fixtures/expected.py`
and must be updated in lockstep.
