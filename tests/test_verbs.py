"""Tests for the M2.c domain verbs (#51-58).

Each verb returns a JSON envelope {ok, result, error}; the outer SQL query
stays ok=true on verb failure. Tests prefer throwaway datablocks and clean up
after themselves so ordering doesn't matter.
"""

from __future__ import annotations

import json
import os

import pytest


def _verb(client, sql: str) -> dict:
    r = client.query(sql)
    assert r['ok'], r
    return json.loads(r['rows'][0][0])


def _bpy_exec(client, code: str) -> dict:
    r = client.query(f"SELECT bpy_exec('{code}')")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert not payload.get('error'), payload
    return payload


# --------------------------------------------------------------------------- add_object


def test_add_object_empty(client) -> None:
    try:
        env = _verb(client, "SELECT add_object('EMPTY', 'VerbEmpty')")
        assert env['ok'], env
        assert env['result'] == 'VerbEmpty'
        chk = client.query("SELECT type, data FROM objects WHERE name='VerbEmpty'")
        assert chk['ok'] and chk['row_count'] == 1
        assert chk['rows'][0][0] == 'EMPTY'
        assert chk['rows'][0][1] is None
    finally:
        client.query("DELETE FROM objects WHERE name='VerbEmpty'")


def test_add_object_with_location(client) -> None:
    try:
        env = _verb(client, "SELECT add_object('EMPTY', 'VerbLoc', '[1,2,3]')")
        assert env['ok'], env
        chk = client.query(
            "SELECT location_x, location_y, location_z FROM objects WHERE name='VerbLoc'"
        )
        assert chk['ok'], chk
        assert chk['rows'][0] == pytest.approx([1.0, 2.0, 3.0])
    finally:
        client.query("DELETE FROM objects WHERE name='VerbLoc'")


def test_add_object_mesh_has_datablock(client) -> None:
    try:
        env = _verb(client, "SELECT add_object('MESH', 'VerbMesh')")
        assert env['ok'], env
        chk = client.query("SELECT data FROM objects WHERE name='VerbMesh'")
        assert chk['ok'] and chk['rows'][0][0] == 'VerbMesh'
        m = client.query("SELECT COUNT(*) FROM meshes WHERE name='VerbMesh'")
        assert m['ok'] and m['rows'][0][0] == 1
    finally:
        _bpy_exec(
            client,
            'o = bpy.data.objects.get("VerbMesh")\n'
            'if o is not None: bpy.data.objects.remove(o, do_unlink=True)\n'
            'm = bpy.data.meshes.get("VerbMesh")\n'
            'if m is not None: bpy.data.meshes.remove(m)',
        )


def test_add_object_bad_type(client) -> None:
    env = _verb(client, "SELECT add_object('NOTATYPE', 'VerbBad')")
    assert env['ok'] is False
    assert env['error'] is not None
    chk = client.query("SELECT COUNT(*) FROM objects WHERE name='VerbBad'")
    assert chk['ok'] and chk['rows'][0][0] == 0


# --------------------------------------------------------------------------- add_modifier


def test_add_modifier_subsurf(client) -> None:
    try:
        env = _verb(client, "SELECT add_modifier('Cube', 'SUBSURF', '{\"levels\":2}')")
        assert env['ok'], env
        mod_name = env['result']
        chk = client.query(
            f"SELECT json_extract(params_json, '$.levels') FROM modifiers "
            f"WHERE object='Cube' AND name='{mod_name}'"
        )
        assert chk['ok'] and chk['rows'][0][0] == 2
    finally:
        _bpy_exec(
            client,
            'o = bpy.data.objects["Cube"]\n'
            'for m in list(o.modifiers):\n'
            '    if m.name.startswith("Subsurf"): o.modifiers.remove(m)',
        )


def test_add_modifier_missing_object(client) -> None:
    env = _verb(client, "SELECT add_modifier('NoSuchObject', 'SUBSURF')")
    assert env['ok'] is False
    assert env['error'] is not None


# --------------------------------------------------------------------------- add_constraint


def test_add_constraint_track_to(client) -> None:
    try:
        env = _verb(
            client,
            "SELECT add_constraint('Cube', 'TRACK_TO', 'Cam', "
            '\'{"track_axis":"TRACK_NEGATIVE_Z"}\')',
        )
        assert env['ok'], env
        con_name = env['result']
        chk = client.query(
            f"SELECT type, target FROM constraints WHERE owner_name='Cube' AND name='{con_name}'"
        )
        assert chk['ok'] and chk['row_count'] == 1
        assert chk['rows'][0][0] == 'TRACK_TO'
        assert chk['rows'][0][1] == 'Cam'
    finally:
        _bpy_exec(
            client,
            'o = bpy.data.objects["Cube"]\n'
            'for c in list(o.constraints):\n'
            '    if c.type == "TRACK_TO": o.constraints.remove(c)',
        )


# --------------------------------------------------------------------------- set_keyframe / ensure_fcurve


def test_set_keyframe(client) -> None:
    try:
        env = _verb(
            client,
            "SELECT set_keyframe('object', 'Cube', 'location', 50, '[5,0,0]', 0, 'LINEAR')",
        )
        assert env['ok'], env
        assert env['result']['frame'] == 50
        chk = client.query(
            "SELECT interpolation FROM keyframes WHERE action='CubeAction' AND frame=50.0"
        )
        assert chk['ok'] and chk['row_count'] == 1
        assert chk['rows'][0][0] == 'LINEAR'
    finally:
        _bpy_exec(
            client,
            'obj = bpy.data.objects["Cube"]\n'
            'act = bpy.data.actions.get("CubeAction")\n'
            'if act is not None: bpy.data.actions.remove(act)\n'
            'obj.animation_data_clear()\n'
            'obj.animation_data_create()\n'
            'act = bpy.data.actions.new("CubeAction")\n'
            'obj.animation_data.action = act\n'
            'for fr in (1, 30):\n'
            '    obj.location.x = float(fr) / 10\n'
            '    obj.keyframe_insert(data_path="location", frame=fr)\n'
            'obj.location.x = 0.1',
        )


def test_ensure_fcurve(client) -> None:
    try:
        env = _verb(client, "SELECT ensure_fcurve('object', 'Cube', 'rotation_euler', 2)")
        assert env['ok'], env
        assert env['result']['action'] == 'CubeAction'
        chk = client.query(
            "SELECT COUNT(*) FROM fcurves WHERE action='CubeAction' "
            "AND data_path='rotation_euler' AND array_index=2"
        )
        assert chk['ok'] and chk['rows'][0][0] == 1
    finally:
        _bpy_exec(
            client,
            'obj = bpy.data.objects["Cube"]\n'
            'act = bpy.data.actions.get("CubeAction")\n'
            'if act is not None: bpy.data.actions.remove(act)\n'
            'obj.animation_data_clear()\n'
            'obj.animation_data_create()\n'
            'act = bpy.data.actions.new("CubeAction")\n'
            'obj.animation_data.action = act\n'
            'for fr in (1, 30):\n'
            '    obj.location.x = float(fr) / 10\n'
            '    obj.keyframe_insert(data_path="location", frame=fr)\n'
            'obj.location.x = 0.1',
        )


# --------------------------------------------------------------------------- save


def test_save_to_temp_path(client) -> None:
    out = '/tmp/blendersql_verbtest.blend'
    if os.path.exists(out):
        os.remove(out)
    try:
        env = _verb(client, f"SELECT save('{out}')")
        assert env['ok'], env
        assert env['result']['filepath'] == out
        assert os.path.exists(out)
    finally:
        if os.path.exists(out):
            os.remove(out)


# --------------------------------------------------------------------------- add_node / link_nodes


def test_add_node_and_link(client) -> None:
    try:
        env = _verb(client, "SELECT add_node('Mat', 'ShaderNodeRGB', '[-400,0]')")
        assert env['ok'], env
        node_name = env['result']
        chk = client.query(f"SELECT bl_idname FROM nodes WHERE tree='Mat' AND name='{node_name}'")
        assert chk['ok'] and chk['row_count'] == 1
        assert chk['rows'][0][0] == 'ShaderNodeRGB'

        env = _verb(
            client,
            f"SELECT link_nodes('Mat', '{node_name}', 'Color', 'Principled BSDF', 'Emission Color')",
        )
        assert env['ok'], env
        link = client.query(
            f"SELECT COUNT(*) FROM node_links WHERE tree='Mat' AND from_node='{node_name}'"
        )
        assert link['ok'] and link['rows'][0][0] == 1
    finally:
        _bpy_exec(
            client,
            'tree = bpy.data.materials["Mat"].node_tree\n'
            'for n in list(tree.nodes):\n'
            '    if n.bl_idname == "ShaderNodeRGB": tree.nodes.remove(n)',
        )


def test_link_nodes_missing_node(client) -> None:
    env = _verb(client, "SELECT link_nodes('Mat', 'NoNode', 'X', 'Principled BSDF', 'Base Color')")
    assert env['ok'] is False
    assert env['error'] is not None


def test_build_node_tree(client) -> None:
    try:
        _bpy_exec(client, 'bpy.data.node_groups.new("VerbGeoGroup", "GeometryNodeTree")')
        spec = json.dumps(
            {
                'clear': True,
                'nodes': [
                    {'name': 'a', 'type': 'GeometryNodeSetPosition', 'location': [-200, 0]},
                    {'name': 'b', 'type': 'GeometryNodeSetPosition', 'location': [0, 0]},
                    {'name': 'c', 'type': 'GeometryNodeSetPosition', 'location': [200, 0]},
                ],
                'links': [
                    {
                        'from_node': 'a',
                        'from_socket': 'Geometry',
                        'to_node': 'b',
                        'to_socket': 'Geometry',
                    },
                    {
                        'from_node': 'b',
                        'from_socket': 'Geometry',
                        'to_node': 'c',
                        'to_socket': 'Geometry',
                    },
                ],
            }
        ).replace("'", "''")
        env = _verb(client, f"SELECT build_node_tree('VerbGeoGroup', '{spec}')")
        assert env['ok'], env
        assert env['result']['node_count'] == 3
        assert env['result']['link_count'] == 2
        chk = client.query("SELECT COUNT(*) FROM nodes WHERE tree='VerbGeoGroup'")
        assert chk['ok'] and chk['rows'][0][0] == 3
    finally:
        _bpy_exec(
            client,
            'g = bpy.data.node_groups.get("VerbGeoGroup")\n'
            'if g is not None: bpy.data.node_groups.remove(g)',
        )


# --------------------------------------------------------------------------- grease pencil


def test_gp_verbs_roundtrip(client) -> None:
    try:
        _bpy_exec(client, 'bpy.data.grease_pencils.new("VerbGP")')
        env = _verb(client, "SELECT gp_add_layer('VerbGP', 'L1')")
        assert env['ok'], env
        env = _verb(client, "SELECT gp_add_frame('VerbGP', 'L1', 1)")
        assert env['ok'], env
        env = _verb(client, "SELECT gp_add_stroke('VerbGP', 'L1', 1, '[[0,0,0],[1,0,0],[1,1,0]]')")
        assert env['ok'], env
        assert env['result']['point_count'] == 3
        s = client.query("SELECT point_count FROM gp_strokes WHERE gp='VerbGP' AND layer='L1'")
        assert s['ok'] and s['row_count'] == 1
        assert s['rows'][0][0] == 3
        p = client.query("SELECT COUNT(*) FROM gp_points WHERE gp='VerbGP' AND layer='L1'")
        assert p['ok'] and p['rows'][0][0] == 3
    finally:
        _bpy_exec(
            client,
            'gp = bpy.data.grease_pencils.get("VerbGP")\n'
            'if gp is not None: bpy.data.grease_pencils.remove(gp)',
        )


# --------------------------------------------------------------------------- vse


def test_vse_add_color(client) -> None:
    scene = _verb(client, "SELECT bpy_eval('bpy.context.scene.name')")
    try:
        env = _verb(client, f"SELECT vse_add_color('{scene}', '[1,0,0]', 3, 1, 24)")
        assert env['ok'], env
        chk = client.query(
            f"SELECT type, channel FROM vse_strips WHERE scene='{scene}' AND name='{env['result']}'"
        )
        assert chk['ok'] and chk['row_count'] == 1
        assert chk['rows'][0][0] == 'COLOR'
        assert chk['rows'][0][1] == 3
    finally:
        _bpy_exec(
            client,
            'sc = bpy.context.scene\n'
            'if sc.sequence_editor is not None:\n'
            '    for st in list(sc.sequence_editor.strips):\n'
            '        sc.sequence_editor.strips.remove(st)\n'
            '    sc.sequence_editor_clear()',
        )


# --------------------------------------------------------------------------- import_file error


def test_import_file_missing(client) -> None:
    env = _verb(client, "SELECT import_file('/nonexistent_blendersql_test.obj', 'OBJ')")
    assert env['ok'] is False
    assert env['error'] is not None


# --------------------------------------------------------------------------- audit log


def test_verb_logged_to_session_log(client) -> None:
    try:
        _verb(client, "SELECT add_object('EMPTY', 'VerbLog')")
        r = client.query('SELECT op FROM session_log ORDER BY ts DESC LIMIT 1')
        assert r['ok'], r
        assert r['rows'][0][0] == 'add_object'
    finally:
        client.query("DELETE FROM objects WHERE name='VerbLog'")


# --------------------------------------------------------------------------- render_object


def test_render_object_default_path(client) -> None:
    env = _verb(client, "SELECT render_object('Cube')")
    assert env['ok'], env
    path = env['result']['path']
    assert os.path.exists(path) and os.path.getsize(path) > 1000, path
    # the throwaway render scene / camera must not leak
    chk = client.query(
        "SELECT (SELECT COUNT(*) FROM scenes WHERE name='__bsql_render'), "
        "(SELECT COUNT(*) FROM objects WHERE name='__bsql_cam')"
    )
    assert chk['ok'] and chk['rows'][0] == [0, 0]


def test_render_object_custom_path(client, tmp_path) -> None:
    out = str(tmp_path / 'cube.png')
    env = _verb(client, f"SELECT render_object('Cube', NULL, '{out}')")
    assert env['ok'], env
    assert env['result']['path'] == out
    assert os.path.exists(out) and os.path.getsize(out) > 1000


def test_render_object_missing(client) -> None:
    env = _verb(client, "SELECT render_object('NoSuchObject')")
    assert env['ok'] is False, env
    assert 'not found' in env['error']['message'].lower()


# --------------------------------------------------------------------------- cleanup verbs


def test_purge_orphans(client) -> None:
    _bpy_exec(client, 'm = bpy.data.materials.new("OrphanMat"); m.use_fake_user = False')
    chk = client.query("SELECT users FROM materials WHERE name='OrphanMat'")
    assert chk['ok'] and chk['rows'][0][0] == 0
    env = _verb(client, 'SELECT purge_orphans()')
    assert env['ok'], env
    assert env['result']['total'] >= 1
    assert env['result']['removed'].get('materials', 0) >= 1
    gone = client.query("SELECT COUNT(*) FROM materials WHERE name='OrphanMat'")
    assert gone['ok'] and gone['rows'][0][0] == 0


def test_remove_unused_material_slots(client) -> None:
    _bpy_exec(
        client,
        'me = bpy.data.meshes.new("SlotMesh")\n'
        'import bmesh\n'
        'bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0); bm.to_mesh(me); bm.free()\n'
        'o = bpy.data.objects.new("SlotObj", me)\n'
        'bpy.context.scene.collection.objects.link(o)\n'
        'me.materials.append(bpy.data.materials.new("SlotUsed"))\n'
        'me.materials.append(bpy.data.materials.new("SlotUnused"))\n'
        'for p in me.polygons: p.material_index = 0',
    )
    try:
        before = client.query("SELECT COUNT(*) FROM material_slots WHERE object='SlotObj'")
        assert before['ok'] and before['rows'][0][0] == 2
        env = _verb(client, "SELECT remove_unused_material_slots('SlotObj')")
        assert env['ok'], env
        assert env['result']['objects'].get('SlotObj') == 1
        after = client.query("SELECT COUNT(*) FROM material_slots WHERE object='SlotObj'")
        assert after['ok'] and after['rows'][0][0] == 1
    finally:
        _bpy_exec(
            client,
            'o = bpy.data.objects.get("SlotObj")\n'
            'if o is not None: bpy.data.objects.remove(o, do_unlink=True)\n'
            'for n in ("SlotMesh","SlotUsed","SlotUnused"):\n'
            '    d = bpy.data.meshes.get(n) or bpy.data.materials.get(n)\n'
            '    if d is not None and d.users == 0:\n'
            '        (bpy.data.meshes if isinstance(d, bpy.types.Mesh) else bpy.data.materials).remove(d)',
        )
