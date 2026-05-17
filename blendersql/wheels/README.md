# Vendored apsw wheels

`blender_manifest.toml` lists one apsw wheel per target platform. Only the
macOS arm64 wheel is committed (zero-setup dev install on Apple Silicon, the
common dev platform). Run `python scripts/fetch_wheels.py` (or `make wheels`)
to download the other four — the release CI does this automatically.

A fresh clone therefore has a manifest referencing four absent wheels. That's
fine: Blender only installs the wheel matching the host platform on enable, so
Apple Silicon dev installs work as-is. Keep `_APSW_VERSION` in
`scripts/fetch_wheels.py` in sync with the apsw pin in `pyproject.toml`.
