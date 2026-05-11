"""Tier 2 node-graph verbs: add_node, link_nodes, build_node_tree."""

from __future__ import annotations

import time
from typing import Any

import bpy

from ...vtables.node_trees import iter_trees
from ._common import (
    VerbError,
    arg,
    envelope,
    parse_json_dict,
    parse_vec,
    require_str,
    trunc,
)


def add_node(*args: Any) -> str:
    start = time.monotonic()
    owner = arg(args, 0)
    node_type = arg(args, 1)
    audit_text = f'add_node({owner}, {node_type})'
    try:
        owner = require_str(owner, 'tree_owner')
        node_type = require_str(node_type, 'node_type')
        location = parse_vec(arg(args, 2), 'location_json', 2) if arg(args, 2) is not None else None
        params = parse_json_dict(arg(args, 3), 'params_json')

        tree = _resolve_tree(owner)
        try:
            node = tree.nodes.new(node_type)
        except (RuntimeError, TypeError) as exc:
            raise VerbError(f"could not create node of type '{node_type}': {exc}") from exc
        if location is not None:
            node.location = location
        for key, value in params.items():
            try:
                setattr(node, key, value)
            except (AttributeError, ValueError, TypeError) as exc:
                raise VerbError(f"node param '{key}': {exc}") from exc
        bpy.ops.ed.undo_push(message=f'blendersql: add_node {owner}/{node.name}')
        return envelope(start, 'add_node', audit_text, node.name, None)
    except Exception as exc:
        return envelope(start, 'add_node', audit_text, None, exc)


def link_nodes(*args: Any) -> str:
    start = time.monotonic()
    owner = arg(args, 0)
    audit_text = trunc(
        f'link_nodes({owner}, {arg(args, 1)}.{arg(args, 2)} -> {arg(args, 3)}.{arg(args, 4)})'
    )
    try:
        owner = require_str(owner, 'tree_owner')
        from_node = require_str(arg(args, 1), 'from_node')
        from_socket = require_str(arg(args, 2), 'from_socket')
        to_node = require_str(arg(args, 3), 'to_node')
        to_socket = require_str(arg(args, 4), 'to_socket')

        tree = _resolve_tree(owner)
        src = _resolve_node(tree, from_node)
        dst = _resolve_node(tree, to_node)
        out = _resolve_socket(src.outputs, from_socket, from_node, 'output')
        inp = _resolve_socket(dst.inputs, to_socket, to_node, 'input')
        tree.links.new(out, inp)
        bpy.ops.ed.undo_push(message=f'blendersql: link_nodes {owner}')
        result = {'from': f'{from_node}.{out.name}', 'to': f'{to_node}.{inp.name}'}
        return envelope(start, 'link_nodes', audit_text, result, None)
    except Exception as exc:
        return envelope(start, 'link_nodes', audit_text, None, exc)


def build_node_tree(*args: Any) -> str:
    start = time.monotonic()
    owner = arg(args, 0)
    audit_text = f'build_node_tree({owner})'
    try:
        owner = require_str(owner, 'tree_owner')
        spec = parse_json_dict(arg(args, 1), 'spec_json')
        nodes_spec = spec.get('nodes', [])
        links_spec = spec.get('links', [])
        if not isinstance(nodes_spec, list) or not isinstance(links_spec, list):
            raise VerbError("spec_json: 'nodes' and 'links' must be arrays")

        tree = _resolve_tree(owner)
        if spec.get('clear'):
            tree.nodes.clear()

        named: dict[str, Any] = {}
        for i, ns in enumerate(nodes_spec):
            if not isinstance(ns, dict):
                raise VerbError(f'spec_json.nodes[{i}] must be an object')
            ntype = require_str(ns.get('type'), f'spec_json.nodes[{i}].type')
            try:
                node = tree.nodes.new(ntype)
            except (RuntimeError, TypeError) as exc:
                raise VerbError(f"spec_json.nodes[{i}]: bad type '{ntype}': {exc}") from exc
            loc = ns.get('location')
            if loc is not None:
                node.location = parse_vec_inline(loc, f'spec_json.nodes[{i}].location', 2)
            for key, value in (ns.get('params') or {}).items():
                try:
                    setattr(node, key, value)
                except (AttributeError, ValueError, TypeError) as exc:
                    raise VerbError(f'spec_json.nodes[{i}].params.{key}: {exc}') from exc
            label = ns.get('name')
            if isinstance(label, str) and label:
                named[label] = node

        for i, ls in enumerate(links_spec):
            if not isinstance(ls, dict):
                raise VerbError(f'spec_json.links[{i}] must be an object')
            fn = require_str(ls.get('from_node'), f'spec_json.links[{i}].from_node')
            fs = require_str(ls.get('from_socket'), f'spec_json.links[{i}].from_socket')
            tn = require_str(ls.get('to_node'), f'spec_json.links[{i}].to_node')
            ts = require_str(ls.get('to_socket'), f'spec_json.links[{i}].to_socket')
            src = named.get(fn) or _resolve_node(tree, fn)
            dst = named.get(tn) or _resolve_node(tree, tn)
            out = _resolve_socket(src.outputs, fs, fn, 'output')
            inp = _resolve_socket(dst.inputs, ts, tn, 'input')
            tree.links.new(out, inp)

        bpy.ops.ed.undo_push(message=f'blendersql: build_node_tree {owner}')
        result = {'node_count': len(tree.nodes), 'link_count': len(tree.links)}
        return envelope(start, 'build_node_tree', audit_text, result, None)
    except Exception as exc:
        return envelope(start, 'build_node_tree', audit_text, None, exc)


def parse_vec_inline(value: Any, name: str, length: int) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise VerbError(f'{name} must be a {length}-element array')
    out: list[float] = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise VerbError(f'{name} must contain only numbers')
        out.append(float(v))
    return out


def _resolve_tree(owner: str) -> Any:
    for _owner_type, owner_name, tree in iter_trees():
        if owner_name == owner:
            return tree
    raise VerbError(f"no node tree owned by '{owner}'")


def _resolve_node(tree: Any, name: str) -> Any:
    node = tree.nodes.get(name)
    if node is None:
        raise VerbError(f"node '{name}' not found in tree")
    return node


def _resolve_socket(sockets: Any, ref: str, node_name: str, kind: str) -> Any:
    # '#<index>' disambiguates duplicate socket names.
    if ref.startswith('#'):
        try:
            idx = int(ref[1:])
        except ValueError as exc:
            raise VerbError(f"bad socket index '{ref}'") from exc
        if idx < 0 or idx >= len(sockets):
            raise VerbError(f"node '{node_name}' has no {kind} socket at index {idx}")
        return sockets[idx]
    for s in sockets:
        if s.name == ref or s.identifier == ref:
            return s
    raise VerbError(f"node '{node_name}' has no {kind} socket named '{ref}'")
