# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Evaluate Blender's own Noise Texture and Random Value nodes on given points.

Run inside Blender:
  blender -b --factory-startup --python blender_noise_ref.py -- <in.json> <out.json>

in.json:  {"position": [[x, y, z], ...], "cases": [{"name", "kind": "noise"|"random", ...}]}
out.json: {"position": evaluated positions, "<name>": [values...]}
Values are written as float32 bit patterns so the comparison can be exact.
"""

import json
import struct
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
IN_PATH, OUT_PATH = argv[0], argv[1]
data = json.load(open(IN_PATH))


def find_input(node, name, socket_type=None):
    for s in node.inputs:
        if s.name == name and s.enabled and (socket_type is None or s.type == socket_type):
            return s
    raise KeyError(f"{node.bl_idname}: no enabled input {name!r} ({socket_type})")


def find_output(node, name):
    for s in node.outputs:
        if s.name == name and s.enabled:
            return s
    raise KeyError(f"{node.bl_idname}: no enabled output {name!r}")


mesh = bpy.data.meshes.new("pts")
mesh.from_pydata([tuple(p) for p in data["position"]], [], [])
obj = bpy.data.objects.new("pts", mesh)
bpy.context.scene.collection.objects.link(obj)

tree = bpy.data.node_groups.new("ref", "GeometryNodeTree")
tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
n_in = tree.nodes.new("NodeGroupInput")
n_out = tree.nodes.new("NodeGroupOutput")
pos = tree.nodes.new("GeometryNodeInputPosition")
index = tree.nodes.new("GeometryNodeInputIndex")

geo = n_in.outputs[0]
for case in data["cases"]:
    if case["kind"] == "noise":
        node = tree.nodes.new("ShaderNodeTexNoise")
        node.noise_dimensions = "3D"
        node.noise_type = "FBM"
        node.normalize = True
        tree.links.new(pos.outputs[0], find_input(node, "Vector"))
        find_input(node, "Scale").default_value = case["scale"]
        find_input(node, "Detail").default_value = case["detail"]
        find_input(node, "Roughness").default_value = case["roughness"]
        find_input(node, "Lacunarity").default_value = case["lacunarity"]
        find_input(node, "Distortion").default_value = 0.0
        value = find_output(node, "Factor")
    elif case["kind"] == "random":
        node = tree.nodes.new("FunctionNodeRandomValue")
        node.data_type = "FLOAT"
        find_input(node, "Min", "VALUE").default_value = 0.0
        find_input(node, "Max", "VALUE").default_value = 1.0
        tree.links.new(index.outputs[0], find_input(node, "ID"))
        find_input(node, "Seed").default_value = case["seed"]
        value = find_output(node, "Value")
    elif case["kind"] == "voronoi":
        node = tree.nodes.new("ShaderNodeTexVoronoi")
        node.voronoi_dimensions = "3D"
        node.feature = "F1"
        node.distance = "EUCLIDEAN"
        node.normalize = False
        tree.links.new(pos.outputs[0], find_input(node, "Vector"))
        find_input(node, "Scale").default_value = case["scale"]
        find_input(node, "Detail").default_value = 0.0
        find_input(node, "Randomness").default_value = case["randomness"]
        value = find_output(node, case["output"])
    else:
        raise ValueError(case["kind"])
    vector = case.get("comps", 1) == 3
    store = tree.nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type = "FLOAT_VECTOR" if vector else "FLOAT"
    store.domain = "POINT"
    find_input(store, "Name").default_value = case["name"]
    tree.links.new(geo, find_input(store, "Geometry"))
    tree.links.new(value, find_input(store, "Value", "VECTOR" if vector else "VALUE"))
    geo = store.outputs[0]
tree.links.new(geo, n_out.inputs[0])

mod = obj.modifiers.new("ref", "NODES")
mod.node_group = tree

dg = bpy.context.evaluated_depsgraph_get()
ev = obj.evaluated_get(dg).data


def bits(values):
    return [struct.unpack("<I", struct.pack("<f", v))[0] for v in values]


n = len(ev.vertices)
out = {}
flat = [0.0] * (3 * n)
ev.attributes["position"].data.foreach_get("vector", flat)
out["position"] = bits(flat)
for case in data["cases"]:
    comps = case.get("comps", 1)
    vals = [0.0] * (n * comps)
    ev.attributes[case["name"]].data.foreach_get("vector" if comps == 3 else "value", vals)
    out[case["name"]] = bits(vals)
json.dump(out, open(OUT_PATH, "w"))
print("WROTE", OUT_PATH)
