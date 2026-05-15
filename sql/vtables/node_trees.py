from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import apsw
import bpy

from ..functions.jsonify import to_jsonable
from ._meta import Column
from .base import IteratorVTable, WritableSnapshotVTable

# `tree` identity is the owner's bare name (material/world/light/linestyle/scene)
# or the group's name (node_group). Matches PLAN verifications which use bare
# names like 'ProbeMat' and 'ProbeGeo'. Collision risk: a material and a node
# group with the same name would alias rows across these tables. Live data
# never hits this and the BlenderSQL writer can disambiguate via owner_type
# from `node_trees`. Escalation if it ever bites: add a `tree_owner_type`
# column to every join table.
#
# Performance note: AI_TEST.blend has ~70 trees and a few hundred nodes total
# — single-digit-ms snapshots. Real shader/geometry trees can have hundreds of
# nodes, at which point BestIndex pushdown on `tree` is the right escalation
# for `nodes` / `node_inputs` / `node_outputs` / `node_links`.


def iter_trees() -> Iterator[tuple[str, str, Any]]:
    for g in bpy.data.node_groups:
        yield 'node_group', g.name, g
    for m in bpy.data.materials:
        if m.use_nodes and m.node_tree is not None:
            yield 'material', m.name, m.node_tree
    for w in bpy.data.worlds:
        if w.use_nodes and w.node_tree is not None:
            yield 'world', w.name, w.node_tree
    for light in bpy.data.lights:
        if light.use_nodes and light.node_tree is not None:
            yield 'light', light.name, light.node_tree
    for ls in bpy.data.linestyles:
        if getattr(ls, 'use_nodes', False) and ls.node_tree is not None:
            yield 'linestyle', ls.name, ls.node_tree
    for s in bpy.data.scenes:
        nt = getattr(s, 'compositing_node_group', None)
        if nt is not None:
            yield 'scene', s.name, nt


class NodeTrees(IteratorVTable):
    DESCRIPTION = 'Every node tree in the file: standalone groups plus embedded trees.'
    AGENT_HINT = (
        'Enumerates node trees across node_groups, materials, worlds, lights, linestyles, '
        'and scene compositors. owner_type tells you which kind. JOIN nodes / node_links / '
        'node_inputs / node_outputs (tree=owner_name) to drill in. Read-only — edit '
        'node_inputs.default_value_json to retune sockets.'
    )
    COLUMNS: tuple[Column, ...] = (
        Column(
            'name',
            'TEXT',
            hint='Tree name — equals owner_name (and is the join key for child tables).',
        ),
        Column('bl_idname', 'TEXT', hint='ShaderNodeTree / GeometryNodeTree / CompositorNodeTree.'),
        Column('type', 'TEXT', hint='SHADER / GEOMETRY / COMPOSITING / TEXTURE.'),
        Column(
            'owner_type',
            'TEXT',
            hint='node_group / material / world / light / linestyle / scene.',
        ),
        Column(
            'owner_name',
            'TEXT',
            pk=True,
            hint='Name of the owning datablock; join key for nodes/links/sockets.',
        ),
        Column('node_count', 'INTEGER', hint='len(tree.nodes).'),
        Column('link_count', 'INTEGER', hint='len(tree.links).'),
    )
    RELATED: tuple[str, ...] = (
        'nodes',
        'node_links',
        'node_inputs',
        'node_outputs',
        'node_tree_interface',
        'materials',
    )
    schema = (
        'CREATE TABLE node_trees('
        'name TEXT, '
        'bl_idname TEXT, '
        'type TEXT, '
        'owner_type TEXT, '
        'owner_name TEXT, '
        'node_count INTEGER, '
        'link_count INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for owner_type, owner_name, tree in iter_trees():
            rows.append(
                (
                    tree.name,
                    tree.bl_idname,
                    tree.type,
                    owner_type,
                    owner_name,
                    len(tree.nodes),
                    len(tree.links),
                )
            )
        return rows


class Nodes(IteratorVTable):
    schema = (
        'CREATE TABLE nodes('
        'tree TEXT, '
        'name TEXT, '
        'bl_idname TEXT, '
        'type TEXT, '
        'location_x REAL, '
        'location_y REAL, '
        'mute INTEGER, '
        'hide INTEGER, '
        'parent TEXT, '
        'label TEXT, '
        'width REAL, '
        'height REAL)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for _owner_type, owner_name, tree in iter_trees():
            for n in tree.nodes:
                loc = n.location
                parent = n.parent
                rows.append(
                    (
                        owner_name,
                        n.name,
                        n.bl_idname,
                        n.type,
                        float(loc[0]),
                        float(loc[1]),
                        int(n.mute),
                        int(n.hide),
                        parent.name if parent is not None else None,
                        n.label,
                        float(n.width),
                        float(n.height),
                    )
                )
        return rows


_NODE_INPUT_COLUMNS: tuple[str, ...] = (
    'tree',
    'node',
    'identifier',
    'index',
    'name',
    'type',
    'default_value_json',
    'is_linked',
)
_NI_COL_INDEX: dict[str, int] = {name: i for i, name in enumerate(_NODE_INPUT_COLUMNS)}


class NodeInputs(WritableSnapshotVTable):
    table_name = 'node_inputs'
    schema = (
        'CREATE TABLE node_inputs('
        'tree TEXT, '
        'node TEXT, '
        'identifier TEXT, '
        '"index" INTEGER, '
        'name TEXT, '
        'type TEXT, '
        'default_value_json TEXT, '
        'is_linked INTEGER)'
    )

    def _snapshot(self) -> tuple[list[tuple[Any, ...]], list[tuple[str, str, int]]]:
        rows: list[tuple[Any, ...]] = []
        idents: list[tuple[str, str, int]] = []
        for _owner_type, owner_name, tree in iter_trees():
            for n in tree.nodes:
                for i, s in enumerate(n.inputs):
                    rows.append(_socket_row(owner_name, n, s, i))
                    idents.append((owner_name, n.name, i))
        return rows, idents

    def _describe_identifier(self, identifier: Any) -> str:
        tree_name, node_name, idx = identifier
        return f'{tree_name}/{node_name}#{idx}'

    def _apply_insert(self, fields: tuple[Any, ...]) -> Any:
        raise apsw.SQLError(
            'INSERT into node_inputs is not supported; sockets are defined by the node'
        )

    def _apply_delete(self, identifier: Any) -> None:
        raise apsw.SQLError(
            'DELETE from node_inputs is not supported; sockets are defined by the node'
        )

    def _apply_update(self, identifier: Any, fields: tuple[Any, ...]) -> None:
        tree_name, node_name, idx = identifier
        socket = _resolve_input_socket(tree_name, node_name, idx)
        current = _socket_row(tree_name, _find_node(tree_name, node_name), socket, idx)

        for col in ('tree', 'node', 'identifier', 'index', 'name', 'type', 'is_linked'):
            i = _NI_COL_INDEX[col]
            if fields[i] != current[i]:
                raise apsw.SQLError(f"column '{col}' is read-only on UPDATE")

        new_json = fields[_NI_COL_INDEX['default_value_json']]
        if new_json == current[_NI_COL_INDEX['default_value_json']]:
            return
        if socket.is_linked:
            raise apsw.SQLError('cannot set default_value on a linked socket')
        _assign_socket_default(socket, new_json)


class NodeOutputs(IteratorVTable):
    schema = (
        'CREATE TABLE node_outputs('
        'tree TEXT, '
        'node TEXT, '
        'identifier TEXT, '
        '"index" INTEGER, '
        'name TEXT, '
        'type TEXT, '
        'default_value_json TEXT, '
        'is_linked INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        return _socket_rows(inputs=False)


class NodeLinks(IteratorVTable):
    schema = (
        'CREATE TABLE node_links('
        'tree TEXT, '
        'from_node TEXT, '
        'from_socket TEXT, '
        'to_node TEXT, '
        'to_socket TEXT, '
        'is_muted INTEGER, '
        'is_valid INTEGER)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for _owner_type, owner_name, tree in iter_trees():
            for link in tree.links:
                rows.append(
                    (
                        owner_name,
                        link.from_node.name,
                        link.from_socket.name,
                        link.to_node.name,
                        link.to_socket.name,
                        int(link.is_muted),
                        int(link.is_valid),
                    )
                )
        return rows


class NodeTreeInterface(IteratorVTable):
    # Only node groups have an interface; embedded trees (material/world/light/
    # linestyle/scene) have no sockets exposed to a parent graph.
    # Root panel's `.name` is the empty string — surface as NULL parent_panel.
    schema = (
        'CREATE TABLE node_tree_interface('
        'tree TEXT, '
        'identifier TEXT, '
        'name TEXT, '
        'item_type TEXT, '
        'in_out TEXT, '
        'socket_type TEXT, '
        'parent_panel TEXT, '
        'description TEXT, '
        '"index" INTEGER, '
        'default_value_json TEXT)'
    )

    def snapshot(self) -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for owner_type, owner_name, tree in iter_trees():
            if owner_type != 'node_group':
                continue
            iface = getattr(tree, 'interface', None)
            if iface is None:
                continue
            for it in iface.items_tree:
                item_type = it.item_type
                in_out = getattr(it, 'in_out', None) if item_type == 'SOCKET' else None
                socket_type = getattr(it, 'socket_type', None) if item_type == 'SOCKET' else None
                parent = it.parent
                parent_name = parent.name if parent is not None and parent.name else None
                default_json = None
                if item_type == 'SOCKET':
                    try:
                        default_json = json.dumps(to_jsonable(it.default_value))
                    except Exception:
                        default_json = None
                rows.append(
                    (
                        owner_name,
                        it.identifier,
                        it.name,
                        item_type,
                        in_out,
                        socket_type,
                        parent_name,
                        getattr(it, 'description', '') or '',
                        int(getattr(it, 'index', -1)),
                        default_json,
                    )
                )
        return rows


def _socket_rows(*, inputs: bool) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for _owner_type, owner_name, tree in iter_trees():
        for n in tree.nodes:
            sockets = n.inputs if inputs else n.outputs
            for i, s in enumerate(sockets):
                rows.append(_socket_row(owner_name, n, s, i))
    return rows


def _socket_row(owner_name: str, node: Any, socket: Any, index: int) -> tuple[Any, ...]:
    return (
        owner_name,
        node.name,
        socket.identifier,
        index,
        socket.name,
        socket.type,
        _socket_default_json(socket),
        int(socket.is_linked),
    )


def _socket_default_json(socket: Any) -> str | None:
    try:
        v = socket.default_value
    except Exception:
        return None
    try:
        return json.dumps(to_jsonable(v))
    except Exception:
        return None


def _find_tree(tree_name: str) -> Any:
    for _owner_type, owner_name, tree in iter_trees():
        if owner_name == tree_name:
            return tree
    raise apsw.SQLError(f"node tree '{tree_name}' not found")


def _find_node(tree_name: str, node_name: str) -> Any:
    tree = _find_tree(tree_name)
    node = tree.nodes.get(node_name)
    if node is None:
        raise apsw.SQLError(f"node '{node_name}' not found in tree '{tree_name}'")
    return node


def _resolve_input_socket(tree_name: str, node_name: str, index: int) -> Any:
    node = _find_node(tree_name, node_name)
    if index < 0 or index >= len(node.inputs):
        raise apsw.SQLError(f"node '{node_name}' has no input socket at index {index}")
    return node.inputs[index]


def _assign_socket_default(socket: Any, raw_json: Any) -> None:
    if raw_json is None:
        raise apsw.SQLError('default_value_json must not be NULL')
    if not isinstance(raw_json, str):
        raise apsw.SQLError('default_value_json must be a JSON-encoded TEXT value')
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise apsw.SQLError(f'default_value_json: invalid JSON ({exc.msg})') from exc
    try:
        current = socket.default_value
    except Exception as exc:
        raise apsw.SQLError(f'socket has no settable default_value ({exc})') from exc
    try:
        if hasattr(current, '__len__') and not isinstance(current, (str, bytes)):
            seq = parsed if isinstance(parsed, (list, tuple)) else [parsed]
            n = len(current)
            if len(seq) == 1 and n > 1:
                seq = list(seq) * n
            if len(seq) != n:
                raise apsw.SQLError(f'default_value_json: expected {n} components, got {len(seq)}')
            for i in range(n):
                socket.default_value[i] = seq[i]
        else:
            socket.default_value = parsed
    except apsw.SQLError:
        raise
    except (ValueError, TypeError) as exc:
        raise apsw.SQLError(f'default_value_json: {exc}') from exc
