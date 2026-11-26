# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Volumes in the fork (Run Over Voxels, sample_grid): prints RESULT <json>.

  blender -b --factory-startup --enable-autoexec --python blender_volume_check.py -- <repo> <cases.json>

The input volume is made with Blender's nodes: Cube Grid Topology (12 x 4 x 4 voxels of 0.25,
index x -4..7 and z 6..9, so it spans two leaves along x and z), then Field to Grid makes
"density" (float) and "vel" (vector) from the voxel positions, stored with Store Named Grid. With
"input": "topology", the volume has only the topology, as a bool grid "topo". With "points": n,
a point cloud of n points is joined to the volume (for Run Over Points with sample_grid()).
With "input": "vdb:<path>", the input is a Volume object reading that VDB file.

Each case is evaluated three times: with the Toast node muted and with it on, the grids named in
"grids" dumped through Grid to Points (voxel index, value bits, transform, background); and with
it on, the point cloud dumped (positions and attributes, floats as bits).
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

SOCKET = {"FLOAT": "FLOAT", "VECTOR": "VECTOR", "INT": "INT", "BOOLEAN": "BOOLEAN"}
GRID_TYPE = {"FLOAT": "FLOAT", "VECTOR": "VECTOR_FLOAT", "INT": "INT", "BOOLEAN": "BOOLEAN"}
ATTR_TYPE = {"FLOAT": "FLOAT", "VECTOR": "FLOAT_VECTOR", "INT": "INT", "BOOLEAN": "BOOLEAN"}
LAYOUT = {"FLOAT": ("value", 1, True), "INT": ("value", 1, False), "BOOLEAN": ("value", 1, False),
          "FLOAT_VECTOR": ("vector", 3, True), "FLOAT4X4": ("value", 16, True)}  # fmt: skip


def bits(values):
    return [struct.unpack("<I", struct.pack("<f", v))[0] for v in values]


def attr_values(attributes, name):
    a = attributes.get(name)
    if a is None:
        return None
    key, comps, is_float = LAYOUT[a.data_type]
    v = [0.0 if is_float else 0] * (comps * len(a.data))
    a.data.foreach_get(key, v)
    return bits(v) if is_float else [int(x) for x in v]


def node(tree, idname, **inputs):
    n = tree.nodes.new(idname)
    for k, v in inputs.items():
        n.inputs[k].default_value = v
    return n


def link(tree, a, b):
    tree.links.new(a, b)


def make_volume(tree, kind):
    topo = node(tree, "GeometryNodeCubeGridTopology", **{
        "Bounds Min": (-1.0, 0.0, 1.5), "Bounds Max": (2.0, 1.0, 2.5),
        "Resolution X": 12, "Resolution Y": 4, "Resolution Z": 4,
        "Min X": -4, "Min Y": 0, "Min Z": 6})  # fmt: skip
    if kind == "topology":
        store = node(tree, "GeometryNodeStoreNamedGrid", Name="topo")
        store.data_type = "BOOLEAN"
        link(tree, topo.outputs[0], store.inputs["Grid"])
        return store.outputs[0]
    f2g = tree.nodes.new("GeometryNodeFieldToGrid")
    f2g.data_type = "BOOLEAN"
    f2g.grid_items.new("FLOAT", "density")
    f2g.grid_items.new("VECTOR", "vel")
    link(tree, topo.outputs[0], f2g.inputs["Topology"])
    pos = tree.nodes.new("GeometryNodeInputPosition")
    dot = tree.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = (0.5, 1.25, -0.75)
    link(tree, pos.outputs[0], dot.inputs[0])
    link(tree, dot.outputs["Value"], f2g.inputs["density"])
    cross = tree.nodes.new("ShaderNodeVectorMath")
    cross.operation = "CROSS_PRODUCT"
    cross.inputs[1].default_value = (0.0, 0.0, 1.0)
    link(tree, pos.outputs[0], cross.inputs[0])
    link(tree, cross.outputs["Vector"], f2g.inputs["vel"])
    last = None
    for name, data_type in (("density", "FLOAT"), ("vel", "VECTOR")):
        store = node(tree, "GeometryNodeStoreNamedGrid", Name=name)
        store.data_type = GRID_TYPE[data_type]
        if last is not None:
            link(tree, last, store.inputs["Volume"])
        link(tree, f2g.outputs[name], store.inputs["Grid"])
        last = store.outputs[0]
    return last


def add_points(tree, volume, count):
    pts = node(tree, "GeometryNodePoints", Count=count)
    rnd = tree.nodes.new("FunctionNodeRandomValue")
    rnd.data_type = "FLOAT_VECTOR"
    rnd.inputs["Min"].default_value = (-1.6, -0.3, 1.2)
    rnd.inputs["Max"].default_value = (2.4, 1.3, 2.8)
    link(tree, rnd.outputs["Value"], pts.inputs["Position"])
    join = tree.nodes.new("GeometryNodeJoinGeometry")
    link(tree, pts.outputs[0], join.inputs[0])
    link(tree, volume, join.inputs[0])
    return join.outputs[0]


def dump_grids(tree, volume, grids):
    """Grid to Points of each grid k, with v<k> (value), ix/iy/iz, g (= k), m and bg<k>."""
    join = tree.nodes.new("GeometryNodeJoinGeometry")
    for k, (name, data_type) in enumerate(grids):
        get = node(tree, "GeometryNodeGetNamedGrid", Name=name)
        get.data_type = SOCKET[data_type]
        link(tree, volume, get.inputs["Volume"])
        to_points = tree.nodes.new("GeometryNodeGridToPoints")
        to_points.data_type = SOCKET[data_type]
        link(tree, get.outputs["Grid"], to_points.inputs["Grid"])
        info = tree.nodes.new("GeometryNodeGridInfo")
        info.data_type = SOCKET[data_type]
        link(tree, get.outputs["Grid"], info.inputs["Grid"])
        last = to_points.outputs["Points"]
        # Values and backgrounds per grid (v0, bg0, ...): Join Geometry would give one "v" the
        # widest type of all the grids.
        stores = [(f"v{k}", ATTR_TYPE[data_type], to_points.outputs["Value"]),
                  ("ix", "INT", to_points.outputs["X"]), ("iy", "INT", to_points.outputs["Y"]),
                  ("iz", "INT", to_points.outputs["Z"]), ("tile", "BOOLEAN", to_points.outputs["Is Tile"]),
                  ("m", "FLOAT4X4", info.outputs["Transform"]),
                  (f"bg{k}", ATTR_TYPE[data_type], info.outputs["Background Value"]),
                  ("g", "INT", k)]  # fmt: skip
        for attr, attr_type, value in stores:
            store = tree.nodes.new("GeometryNodeStoreNamedAttribute")
            store.data_type = attr_type
            store.inputs["Name"].default_value = attr
            link(tree, last, store.inputs["Geometry"])
            if isinstance(value, int):
                store.inputs["Value"].default_value = value
            else:
                link(tree, value, store.inputs["Value"])
            last = store.outputs[0]
        link(tree, last, join.inputs[0])
    return join.outputs[0]


def build(case, phase):
    tree = bpy.data.node_groups.new("t", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    out = tree.nodes.new("NodeGroupOutput")
    if case.get("input", "").startswith("vdb:"):
        source = tree.nodes.new("NodeGroupInput").outputs[0]
    else:
        source = make_volume(tree, case.get("input", "volume"))
    if case.get("points"):
        source = add_points(tree, source, case["points"])
    toast_node = tree.nodes.new("GeometryNodeToast")
    toast_node.run_over = case["run_over"]
    text = bpy.data.texts.new("t")
    text.write(case["code"])
    toast_node.text = text
    blender_addon.update_node(toast_node, force=True)
    toast_node.mute = phase == "in"
    link(tree, source, toast_node.inputs[0])
    result = toast_node.outputs[0]
    if phase == "points":
        sep = tree.nodes.new("GeometryNodeSeparateComponents")
        link(tree, result, sep.inputs[0])
        link(tree, sep.outputs["Point Cloud"], out.inputs[0])
    else:
        link(tree, dump_grids(tree, result, case["grids"]), out.inputs[0])
    return tree, toast_node


def evaluate(case, phase):
    kind = case.get("input", "")
    if kind.startswith("vdb:"):
        data = bpy.data.volumes.new("v")
        data.filepath = kind[4:]
    else:
        data = bpy.data.meshes.new("v")
    obj = bpy.data.objects.new("v", data)
    bpy.context.scene.collection.objects.link(obj)
    tree, toast_node = build(case, phase)
    mod = obj.modifiers.new("t", "NODES")
    mod.node_group = tree
    geo = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
    cloud = geo.pointcloud
    data = {"attrs": {}}
    if cloud is not None:
        for a in cloud.attributes:
            if not a.name.startswith(".") and a.data_type in LAYOUT:
                data["attrs"][a.name] = attr_values(cloud.attributes, a.name)
    data["error"] = toast_node.error
    data["warnings"] = [getattr(w, "message", str(w)) for w in mod.node_warnings]
    bpy.data.objects.remove(obj)
    return data


result = {}
for case in json.load(open(CASES)):
    phases = ("in", "out", "points") if case.get("points") else ("in", "out")
    result[case["name"]] = {phase: evaluate(case, phase) for phase in phases}
print("RESULT " + json.dumps(result))
