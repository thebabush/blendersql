from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import bpy

DATABLOCK_KINDS: dict[str, str] = {
    'actions': 'action',
    'armatures': 'armature',
    'brushes': 'brush',
    'cache_files': 'cache_file',
    'cameras': 'camera',
    'collections': 'collection',
    'curves': 'curve',
    'fonts': 'font',
    'grease_pencils': 'grease_pencil',
    'hair_curves': 'hair_curves',
    'images': 'image',
    'lattices': 'lattice',
    'libraries': 'library',
    'lightprobes': 'lightprobe',
    'lights': 'light',
    'linestyles': 'linestyle',
    'masks': 'mask',
    'materials': 'material',
    'meshes': 'mesh',
    'metaballs': 'metaball',
    'movieclips': 'movieclip',
    'node_groups': 'node_group',
    'objects': 'object',
    'paint_curves': 'paint_curve',
    'palettes': 'palette',
    'particles': 'particle',
    'pointclouds': 'pointcloud',
    'scenes': 'scene',
    'screens': 'screen',
    'shape_keys': 'shape_key',
    'sounds': 'sound',
    'speakers': 'speaker',
    'texts': 'text',
    'textures': 'texture',
    'volumes': 'volume',
    'workspaces': 'workspace',
    'worlds': 'world',
}


# 'object' -> 'objects', etc. — reverse of DATABLOCK_KINDS so a datablock_type
# value (as surfaced by the read path) can be resolved back to a bpy.data
# container. Used by custom_properties and the M2.c verbs.
RESOLVE_CONTAINER: dict[str, str] = {kind: attr for attr, kind in DATABLOCK_KINDS.items()}


def iter_named_datablocks() -> Iterator[tuple[str, Any]]:
    for attr, kind in DATABLOCK_KINDS.items():
        container = getattr(bpy.data, attr, None)
        if container is None:
            continue
        for item in container:
            if getattr(item, 'name', None) is None:
                continue
            yield kind, item
