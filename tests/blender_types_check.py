# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Curves, instances, quat/mat4 attributes and lists in the fork: prints RESULT <json>.

  blender -b --factory-startup --enable-autoexec --python blender_types_check.py -- <repo> <cases.json>

Each case runs a Toast node on one input ("grid": a 4x3 grid mesh, "curves": two hair curves of
3 and 4 points, "instances": 4 cube instances on a line) and dumps the output: positions,
topology and every attribute, floats as their bits.
"""

import json
import struct
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
REPO, CASES = argv
sys.path.insert(0, REPO)
import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()

CURVE_POINTS = [(0, 0, 0), (1, 0, 0), (2, 0.5, 0), (0, 1, 0), (1, 1, 0.5), (2, 1, 0), (3, 1.5, 0)]
CURVE_SIZES = [3, 4]

# Attribute data type -> (foreach_get key, floats per element, is float)
LAYOUT = {
    "FLOAT": ("value", 1, True), "INT": ("value", 1, False), "BOOLEAN": ("value", 1, False),
    "FLOAT_VECTOR": ("vector", 3, True), "FLOAT2": ("vector", 2, True),
    "FLOAT_COLOR": ("color", 4, True), "QUATERNION": ("value", 4, True),
    "FLOAT4X4": ("value", 16, True),
}  # fmt: skip


def bits(values):
    return [struct.unpack("<I", struct.pack("<f", v))[0] for v in values]


def dump_attributes(attributes, skip=()):
    out = {}
    for a in attributes:
        if a.name.startswith(".") or a.name in skip or a.data_type not in LAYOUT:
            continue
        key, comps, is_float = LAYOUT[a.data_type]
        v = [0.0 if is_float else 0] * (comps * len(a.data))
        a.data.foreach_get(key, v)
        out[a.name] = {"domain": a.domain, "type": a.data_type,
                       "values": bits(v) if is_float else [int(x) for x in v]}  # fmt: skip
    return out


def make_input(kind):
    if kind == "grid":
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=3, size=2)
        return bpy.context.active_object
    if kind == "curves":
        curves = bpy.data.hair_curves.new("c")
        curves.add_curves(CURVE_SIZES)
        for p, co in zip(curves.points, CURVE_POINTS):
            p.position = co
        obj = bpy.data.objects.new("c", curves)
        bpy.context.scene.collection.objects.link(obj)
        return obj
    # instances: an empty mesh whose node tree builds the instances before the Toast node.
    obj = bpy.data.objects.new("i", bpy.data.meshes.new("i"))
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_tree(case):
    tree = bpy.data.node_groups.new("t", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    i, o = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    node = tree.nodes.new("GeometryNodeToast")
    node.run_over = case["run_over"]
    text = bpy.data.texts.new("t")
    text.write(case["code"])
    node.text = text
    blender_addon.update_node(node, force=True)
    source = i.outputs[0]
    if case["input"] == "instances":
        line = tree.nodes.new("GeometryNodeMeshLine")
        line.inputs["Count"].default_value = 4
        line.inputs["Offset"].default_value = (1.0, 0.0, 0.0)
        cube = tree.nodes.new("GeometryNodeMeshCube")
        inst = tree.nodes.new("GeometryNodeInstanceOnPoints")
        tree.links.new(line.outputs[0], inst.inputs["Points"])
        tree.links.new(cube.outputs[0], inst.inputs["Instance"])
        source = inst.outputs[0]
    tree.links.new(source, node.inputs[0])
    # Toast outputs: "store" = [[output, data type, domain, attribute name], ...] stored with Store
    # Named Attribute; "delete" = a Boolean output used as Delete Geometry's selection.
    last = node.outputs[0]
    for output, data_type, domain, name in case.get("store", []):
        store = tree.nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type = data_type
        store.domain = domain
        store.inputs["Name"].default_value = name
        tree.links.new(last, store.inputs["Geometry"])
        tree.links.new(node.outputs[output], store.inputs["Value"])
        last = store.outputs[0]
    if case.get("delete"):
        delete = tree.nodes.new("GeometryNodeDeleteGeometry")
        delete.domain = case.get("delete_domain", "POINT")
        tree.links.new(last, delete.inputs["Geometry"])
        tree.links.new(node.outputs[case["delete"]], delete.inputs["Selection"])
        last = delete.outputs[0]
    tree.links.new(last, o.inputs[0])
    return tree, node


def dump(obj, kind):
    geo = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    if kind == "grid":
        mesh = geo.mesh
        pos = [0.0] * (3 * len(mesh.vertices))
        mesh.attributes["position"].data.foreach_get("vector", pos)
        return {"P": bits(pos), "faces": [list(f.vertices) for f in mesh.polygons],
                "attrs": dump_attributes(mesh.attributes, ("position",))}  # fmt: skip
    if kind == "curves":
        curves = geo.curves
        if curves is None:
            return {"P": [], "curves": [], "attrs": {}}
        pos = [0.0] * (3 * len(curves.points))
        curves.attributes["position"].data.foreach_get("vector", pos)
        sizes = [c.points_length for c in curves.curves]
        return {"P": bits(pos), "curves": sizes,
                "attrs": dump_attributes(curves.attributes, ("position",))}  # fmt: skip
    cloud = geo.instances_pointcloud()
    return {"count": len(cloud.points), "attrs": dump_attributes(cloud.attributes)}


result = {}
for case in json.load(open(CASES)):
    obj = make_input(case["input"])
    tree, node = build_tree(case)
    mod = obj.modifiers.new("t", "NODES")
    mod.node_group = tree
    out = dump(obj, case["input"])
    out["outputs"] = [(s.name, s.type) for s in node.outputs]
    out["error"] = node.error
    out["warnings"] = [getattr(w, "message", str(w)) for w in mod.node_warnings]
    result[case["name"]] = out
    bpy.data.objects.remove(obj)
print("RESULT " + json.dumps(result))
