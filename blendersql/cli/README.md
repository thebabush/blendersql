# blendersql CLI

A thin command-line tool that boots a headless Blender hosting the extension's
HTTP server and runs SQL against a `.blend` file without opening the GUI. Ships
with the source repo, not inside the built extension zip.

Requires the extension to be installed/discoverable so
`bpy.ops.preferences.addon_enable(module='bl_ext.user_default.blendersql')`
works — run `make install-dev` (creates the dev symlink) or install the built
zip first.

## Usage

```sh
# one query, JSON to stdout (same shape as HTTP POST /query)
uv run blendersql -s scene.blend -q "SELECT name, type FROM objects"

# run statements from a .sql file (semicolon-separated)
uv run blendersql -s scene.blend -f queries.sql

# interactive REPL (.help, .tables, .schema <table>, .q/.quit/.exit, Ctrl+D)
uv run blendersql -s scene.blend -i

# server-only mode — prints the URL, Ctrl+C / SIGTERM shuts it down
uv run blendersql -s scene.blend --http 8174   # port optional, default 8174

# persist changes made during the session
uv run blendersql -s scene.blend -w -q "INSERT INTO objects(name,type) VALUES('E','EMPTY')"

# print the extension version
uv run blendersql --version
```

Flags: `-s/--source` (`.blend` path), `-q/--query`, `-f/--file`,
`-i/--interactive`, `--http [PORT]`, `-w/--write` (save on exit), `--bind ADDR`
(default `127.0.0.1`), `--version`.

Blender is located via `$BLENDER`, then `blender` on `$PATH`, then the macOS
default `/Applications/Blender.app/Contents/MacOS/Blender`.

`-q`/`-f` exit 0 if the last query was `ok:true`, non-zero otherwise. Bad
arguments or a missing file/Blender exit 2.
