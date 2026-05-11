"""Round-trip write tests for the M3.c writable vtables.

Covers materials / modifiers / constraints / keyframes / fcurves / gp_layers /
node_inputs. Each test that mutates a fixture datablock snapshots the relevant
state and restores it on teardown, or works on a throwaway datablock created
via bpy_exec, so test ordering doesn't matter.
"""

from __future__ import annotations

import json

import pytest


def _bpy_exec(client, code: str) -> dict:
    # `code` must use double-quoted Python string literals so it can be embedded
    # verbatim inside an SQLite single-quoted string. Newlines are fine.
    r = client.query(f"SELECT bpy_exec('{code}')")
    assert r['ok'], r
    payload = json.loads(r['rows'][0][0])
    assert not payload.get('error'), payload
    return payload


# --------------------------------------------------------------------------- materials


def test_material_insert_update_delete(client) -> None:
    r = client.query("INSERT INTO materials(name) VALUES ('SqlMat')")
    assert r['ok'], r
    chk = client.query("SELECT use_nodes FROM materials WHERE name='SqlMat'")
    assert chk['ok'] and chk['rows'][0][0] == 1

    upd = client.query("UPDATE materials SET surface_render_method='BLENDED' WHERE name='SqlMat'")
    assert upd['ok'], upd
    chk = client.query("SELECT surface_render_method FROM materials WHERE name='SqlMat'")
    assert chk['ok'] and chk['rows'][0][0] == 'BLENDED'

    ren = client.query("UPDATE materials SET name='SqlMatRenamed' WHERE name='SqlMat'")
    assert ren['ok'], ren
    chk = client.query("SELECT COUNT(*) FROM materials WHERE name='SqlMatRenamed'")
    assert chk['ok'] and chk['rows'][0][0] == 1

    dlt = client.query("DELETE FROM materials WHERE name='SqlMatRenamed'")
    assert dlt['ok'], dlt
    chk = client.query("SELECT COUNT(*) FROM materials WHERE name LIKE 'SqlMat%'")
    assert chk['ok'] and chk['rows'][0][0] == 0


def test_material_insert_explicit_use_nodes(client) -> None:
    # In Blender 5.1 Material.use_nodes is effectively always True; the INSERT
    # still accepts the column without erroring.
    try:
        r = client.query("INSERT INTO materials(name, use_nodes) VALUES ('SqlMatPlain', 1)")
        assert r['ok'], r
        chk = client.query("SELECT use_nodes FROM materials WHERE name='SqlMatPlain'")
        assert chk['ok'] and chk['rows'][0][0] == 1
    finally:
        client.query("DELETE FROM materials WHERE name='SqlMatPlain'")


def test_material_is_grease_pencil_readonly(client) -> None:
    try:
        client.query("INSERT INTO materials(name) VALUES ('SqlMatGP')")
        r = client.query("UPDATE materials SET is_grease_pencil=1 WHERE name='SqlMatGP'")
        assert r['ok'] is False, r
        assert 'is_grease_pencil' in r.get('error', '')
    finally:
        client.query("DELETE FROM materials WHERE name='SqlMatGP'")


# --------------------------------------------------------------------------- modifiers


@pytest.fixture
def _restore_subdiv(client):
    snap = client.query(
        'SELECT show_viewport, show_render, params_json FROM modifiers '
        "WHERE object='Cube' AND name='Subdiv'"
    )
    assert snap['ok'] and snap['row_count'] == 1, snap
    show_vp, show_rn, params = snap['rows'][0]
    levels = json.loads(params).get('levels')
    yield
    client.query(
        f'UPDATE modifiers SET show_viewport={show_vp}, show_render={show_rn} '
        f"WHERE object='Cube' AND name='Subdiv'"
    )
    if levels is not None:
        client.query(
            f"UPDATE modifiers SET params_json=json_set(params_json, '$.levels', {levels}) "
            f"WHERE object='Cube' AND name='Subdiv'"
        )
    chk = client.query("SELECT COUNT(*) FROM modifiers WHERE object='Cube' AND name='Subdiv'")
    if chk['ok'] and chk['rows'][0][0] == 0:
        _bpy_exec(
            client,
            'bpy.data.objects["Cube"].modifiers.new("Subdiv", type="SUBSURF")',
        )


def test_modifier_update_params_json_levels(client, _restore_subdiv) -> None:
    upd = client.query(
        "UPDATE modifiers SET params_json=json_set(params_json, '$.levels', 3) "
        "WHERE object='Cube' AND name='Subdiv'"
    )
    assert upd['ok'], upd
    chk = client.query(
        "SELECT json_extract(params_json, '$.levels') FROM modifiers "
        "WHERE object='Cube' AND name='Subdiv'"
    )
    assert chk['ok'] and chk['rows'][0][0] == 3


def test_modifier_update_show_viewport(client, _restore_subdiv) -> None:
    upd = client.query("UPDATE modifiers SET show_viewport=0 WHERE object='Cube' AND name='Subdiv'")
    assert upd['ok'], upd
    chk = client.query("SELECT show_viewport FROM modifiers WHERE object='Cube' AND name='Subdiv'")
    assert chk['ok'] and chk['rows'][0][0] == 0


def test_modifier_delete_and_restore(client, _restore_subdiv) -> None:
    dlt = client.query("DELETE FROM modifiers WHERE object='Cube' AND name='Subdiv'")
    assert dlt['ok'], dlt
    chk = client.query("SELECT COUNT(*) FROM modifiers WHERE object='Cube' AND name='Subdiv'")
    assert chk['ok'] and chk['rows'][0][0] == 0


def test_modifier_insert_rejected(client) -> None:
    r = client.query("INSERT INTO modifiers(object, name, type) VALUES ('Cube', 'Nope', 'SUBSURF')")
    assert r['ok'] is False, r
    assert 'add_modifier' in r.get('error', '')


# --------------------------------------------------------------------------- constraints


@pytest.fixture
def _con_on_cube(client):
    _bpy_exec(
        client,
        'c = bpy.data.objects["Cube"].constraints.new("COPY_LOCATION"); c.name = "SqlCon"',
    )
    yield
    _bpy_exec(
        client,
        'o = bpy.data.objects["Cube"]\n'
        'c = o.constraints.get("SqlCon")\n'
        'if c is not None: o.constraints.remove(c)',
    )


def test_constraint_update_influence(client, _con_on_cube) -> None:
    upd = client.query(
        "UPDATE constraints SET influence=0.5 WHERE owner_name='Cube' AND name='SqlCon'"
    )
    assert upd['ok'], upd
    chk = client.query(
        "SELECT influence FROM constraints WHERE owner_name='Cube' AND name='SqlCon'"
    )
    assert chk['ok'] and chk['rows'][0][0] == 0.5


def test_constraint_update_target(client, _con_on_cube) -> None:
    upd = client.query(
        "UPDATE constraints SET target='Rig' WHERE owner_name='Cube' AND name='SqlCon'"
    )
    assert upd['ok'], upd
    chk = client.query("SELECT target FROM constraints WHERE owner_name='Cube' AND name='SqlCon'")
    assert chk['ok'] and chk['rows'][0][0] == 'Rig'


def test_constraint_delete(client, _con_on_cube) -> None:
    dlt = client.query("DELETE FROM constraints WHERE owner_name='Cube' AND name='SqlCon'")
    assert dlt['ok'], dlt
    chk = client.query("SELECT COUNT(*) FROM constraints WHERE owner_name='Cube' AND name='SqlCon'")
    assert chk['ok'] and chk['rows'][0][0] == 0


def test_constraint_insert_rejected(client) -> None:
    r = client.query(
        'INSERT INTO constraints(owner_type, owner_name, name, type) '
        "VALUES ('OBJECT', 'Cube', 'X', 'COPY_LOCATION')"
    )
    assert r['ok'] is False, r
    assert 'add_constraint' in r.get('error', '')


# --------------------------------------------------------------------------- node_inputs


@pytest.fixture
def _restore_roughness(client):
    sel = (
        'SELECT default_value_json FROM node_inputs '
        "WHERE tree='Mat' AND node='Principled BSDF' AND name='Roughness'"
    )
    snap = client.query(sel)
    assert snap['ok'] and snap['row_count'] == 1, snap
    before = snap['rows'][0][0]
    yield
    client.query(
        f"UPDATE node_inputs SET default_value_json='{before}' "
        f"WHERE tree='Mat' AND node='Principled BSDF' AND name='Roughness'"
    )


def test_node_input_update_default_value(client, _restore_roughness) -> None:
    upd = client.query(
        "UPDATE node_inputs SET default_value_json='0.25' "
        "WHERE tree='Mat' AND node='Principled BSDF' AND name='Roughness'"
    )
    assert upd['ok'], upd
    chk = client.query(
        'SELECT default_value_json FROM node_inputs '
        "WHERE tree='Mat' AND node='Principled BSDF' AND name='Roughness'"
    )
    assert chk['ok'], chk
    assert json.loads(chk['rows'][0][0]) == pytest.approx(0.25)


def test_node_input_update_vector_default(client) -> None:
    try:
        _bpy_exec(client, 'm = bpy.data.materials.new("SqlNodeMat"); m.use_nodes = True')
        upd = client.query(
            "UPDATE node_inputs SET default_value_json='[0.1, 0.2, 0.3, 1.0]' "
            "WHERE tree='SqlNodeMat' AND node='Principled BSDF' AND name='Base Color'"
        )
        assert upd['ok'], upd
        chk = client.query(
            'SELECT default_value_json FROM node_inputs '
            "WHERE tree='SqlNodeMat' AND node='Principled BSDF' AND name='Base Color'"
        )
        assert chk['ok'], chk
        vals = json.loads(chk['rows'][0][0])
        assert vals[:3] == pytest.approx([0.1, 0.2, 0.3])
    finally:
        client.query("DELETE FROM materials WHERE name='SqlNodeMat'")


def test_node_input_linked_socket_rejected(client) -> None:
    linked = client.query(
        "SELECT node, name FROM node_inputs WHERE tree='Mat' AND is_linked=1 LIMIT 1"
    )
    assert linked['ok'] and linked['row_count'] == 1, linked
    node, sock = linked['rows'][0]
    r = client.query(
        f"UPDATE node_inputs SET default_value_json='0.0' "
        f"WHERE tree='Mat' AND node='{node}' AND name='{sock}'"
    )
    assert r['ok'] is False, r
    assert 'linked' in r.get('error', '').lower()


# --------------------------------------------------------------------------- keyframes / fcurves


def _kf_rows(client) -> list:
    r = client.query(
        'SELECT layer, strip_index, channelbag, fcurve_index, "index", frame, value, '
        'interpolation FROM keyframes WHERE action=\'CubeAction\' ORDER BY fcurve_index, "index"'
    )
    assert r['ok'], r
    return r['rows']


@pytest.fixture
def _restore_action(client):
    before = _kf_rows(client)
    yield
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
    after = _kf_rows(client)
    assert len(after) == len(before), (before, after)


def test_keyframe_update_value(client, _restore_action) -> None:
    rows = _kf_rows(client)
    layer, si, cb, fi, ki = rows[0][:5]
    upd = client.query(
        f"UPDATE keyframes SET value=9.5 WHERE action='CubeAction' AND layer='{layer}' "
        f'AND strip_index={si} AND channelbag=\'{cb}\' AND fcurve_index={fi} AND "index"={ki}'
    )
    assert upd['ok'], upd
    chk = client.query(
        f"SELECT value FROM keyframes WHERE action='CubeAction' AND layer='{layer}' "
        f'AND strip_index={si} AND channelbag=\'{cb}\' AND fcurve_index={fi} AND "index"={ki}'
    )
    assert chk['ok'] and chk['rows'][0][0] == pytest.approx(9.5)


def test_keyframe_update_interpolation(client, _restore_action) -> None:
    rows = _kf_rows(client)
    layer, si, cb, fi, ki = rows[0][:5]
    upd = client.query(
        f"UPDATE keyframes SET interpolation='LINEAR' WHERE action='CubeAction' AND layer='{layer}' "
        f'AND strip_index={si} AND channelbag=\'{cb}\' AND fcurve_index={fi} AND "index"={ki}'
    )
    assert upd['ok'], upd
    chk = client.query(
        f"SELECT interpolation FROM keyframes WHERE action='CubeAction' AND layer='{layer}' "
        f'AND strip_index={si} AND channelbag=\'{cb}\' AND fcurve_index={fi} AND "index"={ki}'
    )
    assert chk['ok'] and chk['rows'][0][0] == 'LINEAR'


def test_keyframe_delete(client, _restore_action) -> None:
    before = client.query("SELECT COUNT(*) FROM keyframes WHERE action='CubeAction'")
    assert before['ok'], before
    n_before = before['rows'][0][0]
    rows = _kf_rows(client)
    layer, si, cb, fi, ki = rows[0][:5]
    dlt = client.query(
        f"DELETE FROM keyframes WHERE action='CubeAction' AND layer='{layer}' "
        f'AND strip_index={si} AND channelbag=\'{cb}\' AND fcurve_index={fi} AND "index"={ki}'
    )
    assert dlt['ok'], dlt
    after = client.query("SELECT COUNT(*) FROM keyframes WHERE action='CubeAction'")
    assert after['ok'] and after['rows'][0][0] == n_before - 1


def test_keyframe_insert(client, _restore_action) -> None:
    rows = _kf_rows(client)
    layer, si, cb, fi = rows[0][0], rows[0][1], rows[0][2], rows[0][3]
    n_before = client.query("SELECT COUNT(*) FROM keyframes WHERE action='CubeAction'")['rows'][0][
        0
    ]
    ins = client.query(
        'INSERT INTO keyframes(action, layer, strip_index, channelbag, fcurve_index, '
        'frame, value, interpolation) '
        f"VALUES ('CubeAction', '{layer}', {si}, '{cb}', {fi}, 15, 3.0, 'CONSTANT')"
    )
    assert ins['ok'], ins
    n_after = client.query("SELECT COUNT(*) FROM keyframes WHERE action='CubeAction'")['rows'][0][0]
    assert n_after == n_before + 1
    chk = client.query(
        "SELECT value, interpolation FROM keyframes WHERE action='CubeAction' "
        f'AND fcurve_index={fi} AND frame=15.0'
    )
    assert chk['ok'] and chk['row_count'] == 1
    assert chk['rows'][0][0] == pytest.approx(3.0)
    assert chk['rows'][0][1] == 'CONSTANT'


def test_fcurve_insert_and_delete(client) -> None:
    base = client.query(
        "SELECT layer, strip_index, channelbag FROM fcurves WHERE action='CubeAction' LIMIT 1"
    )
    assert base['ok'] and base['row_count'] == 1, base
    layer, si, cb = base['rows'][0]
    try:
        ins = client.query(
            'INSERT INTO fcurves(action, layer, strip_index, channelbag, data_path, '
            'array_index) '
            f"VALUES ('CubeAction', '{layer}', {si}, '{cb}', 'scale', 0)"
        )
        assert ins['ok'], ins
        chk = client.query(
            "SELECT COUNT(*) FROM fcurves WHERE action='CubeAction' AND data_path='scale'"
        )
        assert chk['ok'] and chk['rows'][0][0] == 1
    finally:
        client.query("DELETE FROM fcurves WHERE action='CubeAction' AND data_path='scale'")
    chk = client.query(
        "SELECT COUNT(*) FROM fcurves WHERE action='CubeAction' AND data_path='scale'"
    )
    assert chk['ok'] and chk['rows'][0][0] == 0


# --------------------------------------------------------------------------- gp_layers


@pytest.fixture
def _gp_fixture(client):
    _bpy_exec(
        client,
        'gp = bpy.data.grease_pencils.new("SqlGP")\n'
        'lay = gp.layers.new("SqlLayer")\n'
        'lay.opacity = 1.0',
    )
    yield
    _bpy_exec(
        client,
        'gp = bpy.data.grease_pencils.get("SqlGP")\n'
        'if gp is not None: bpy.data.grease_pencils.remove(gp)',
    )


def test_gp_layer_update(client, _gp_fixture) -> None:
    upd = client.query(
        "UPDATE gp_layers SET opacity=0.4, blend_mode='ADD', translation_x=2.0, hide=1 "
        "WHERE gp='SqlGP' AND name='SqlLayer'"
    )
    assert upd['ok'], upd
    chk = client.query(
        'SELECT opacity, blend_mode, translation_x, hide FROM gp_layers '
        "WHERE gp='SqlGP' AND name='SqlLayer'"
    )
    assert chk['ok'], chk
    op, bm, tx, hide = chk['rows'][0]
    assert op == pytest.approx(0.4)
    assert bm == 'ADD'
    assert tx == pytest.approx(2.0)
    assert hide == 1


def test_gp_layer_rename(client, _gp_fixture) -> None:
    upd = client.query(
        "UPDATE gp_layers SET name='SqlLayerRenamed' WHERE gp='SqlGP' AND name='SqlLayer'"
    )
    assert upd['ok'], upd
    chk = client.query("SELECT COUNT(*) FROM gp_layers WHERE gp='SqlGP' AND name='SqlLayerRenamed'")
    assert chk['ok'] and chk['rows'][0][0] == 1


def test_gp_layer_insert_rejected(client, _gp_fixture) -> None:
    r = client.query("INSERT INTO gp_layers(gp, name) VALUES ('SqlGP', 'Nope')")
    assert r['ok'] is False, r
    assert 'gp_add_layer' in r.get('error', '')


def test_gp_stroke_delete(client) -> None:
    _bpy_exec(
        client,
        'gp = bpy.data.grease_pencils.new("SqlGPS")\n'
        'lay = gp.layers.new("L")\n'
        'fr = lay.frames.new(1)\n'
        'fr.drawing.add_strokes([3, 4])',
    )
    try:
        chk = client.query("SELECT COUNT(*) FROM gp_strokes WHERE gp='SqlGPS'")
        assert chk['ok'] and chk['rows'][0][0] == 2
        dlt = client.query('DELETE FROM gp_strokes WHERE gp=\'SqlGPS\' AND "index"=0')
        assert dlt['ok'], dlt
        chk = client.query("SELECT COUNT(*) FROM gp_strokes WHERE gp='SqlGPS'")
        assert chk['ok'] and chk['rows'][0][0] == 1
    finally:
        _bpy_exec(
            client,
            'gp = bpy.data.grease_pencils.get("SqlGPS")\n'
            'if gp is not None: bpy.data.grease_pencils.remove(gp)',
        )


# --------------------------------------------------------------------------- material_gp_settings


def test_material_gp_settings_update(client) -> None:
    _bpy_exec(
        client,
        'm = bpy.data.materials.new("SqlGpMat")\n'
        'bpy.data.materials.create_gpencil_data(m)\n'
        'm.grease_pencil.fill_color = (0.8, 0.7, 0.1, 1.0)',
    )
    try:
        chk = client.query("SELECT COUNT(*) FROM material_gp_settings WHERE material='SqlGpMat'")
        assert chk['ok'] and chk['rows'][0][0] == 1

        upd = client.query(
            'UPDATE material_gp_settings SET fill_color_r=0.2, fill_color_g=0.3, fill_color_b=0.9, '
            "show_fill=1, fill_style='SOLID' WHERE material='SqlGpMat'"
        )
        assert upd['ok'], upd
        row = client.query(
            'SELECT ROUND(fill_color_r,3), ROUND(fill_color_g,3), ROUND(fill_color_b,3), show_fill, fill_style '
            "FROM material_gp_settings WHERE material='SqlGpMat'"
        )
        assert row['ok'] and row['rows'][0] == [0.2, 0.3, 0.9, 1, 'SOLID']

        # material column is read-only on UPDATE
        ro = client.query(
            "UPDATE material_gp_settings SET material='Other' WHERE material='SqlGpMat'"
        )
        assert ro['ok'] is False and 'read-only' in ro.get('error', '').lower()

        # INSERT / DELETE are not supported
        ins = client.query(
            "INSERT INTO material_gp_settings(material, mode) VALUES ('Nope', 'LINE')"
        )
        assert ins['ok'] is False and 'not supported' in ins.get('error', '').lower()
        dlt = client.query("DELETE FROM material_gp_settings WHERE material='SqlGpMat'")
        assert dlt['ok'] is False and 'not supported' in dlt.get('error', '').lower()
    finally:
        _bpy_exec(
            client,
            'm = bpy.data.materials.get("SqlGpMat")\n'
            'if m is not None: bpy.data.materials.remove(m)',
        )
