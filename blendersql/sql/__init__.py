"""SQL engine — apsw connection, vtables, and SQL functions.

This module is the engine boundary. Everything that touches bpy.data lives
behind run_on_main; everything that interacts with apsw runs on the thread
that owns the connection (usually the main thread).
"""
