"""Standalone command-line interface for BlenderSQL.

Ships with the source repo, not inside the Blender extension zip. The CLI
spawns a headless Blender that hosts the extension's HTTP server and talks to
it over HTTP; the CLI process itself needs only the standard library.
"""
