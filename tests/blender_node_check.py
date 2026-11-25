# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Evaluate GeometryNodeToast in the fork on an ico sphere and dump the results.

Run inside the fork's Blender (auto-run must be on for kernels to load):
  blender -b --factory-startup --enable-autoexec --python blender_node_check.py -- \
      <repo_dir> <cases.json> <out.json>

cases.json: [{"name", "code", "input1": bool, "params": {name: value}}]
out.json: {"input": {...}, "<case>": {"P", "attrs": {name: bits}, "edges", "faces", "error"}}
Floats are written as float32 bit patterns so the comparison can be exact.
"""

import json
import struct
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
REPO, CASES_PATH, OUT_PATH = argv
sys.path.insert(0, REPO)

import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()


def bits(values):
    return [struct.unpack("<I", struct.pack("<f", v))[0] for v in values]


def dump_mesh(mesh, attr_names):
    n = len(mesh.vertices)
    out = {}
    pos = [0.0] * (3 * n)
    mesh.attributes["position"].data.foreach_get("vector", pos)
    out["P"] = bits(pos)
    out["edges"] = [list(e.vertices) for e in mesh.edges]
    out["faces"] = [list(p.vertices) for p in mesh.polygons]
    out["attrs"] = {}
    for name in attr_names:
        attr = mesh.attributes.get(name)
        if attr is None:
            continue
        if attr.data_type == "FLOAT":
            vals = [0.0] * n
            attr.data.foreach_get("value", vals)
            out["attrs"][name] = bits(vals)
        elif attr.data_type == "FLOAT_VECTOR":
            vals = [0.0] * (3 * n)
            attr.data.foreach_get("vector", vals)
            out["attrs"][name] = bits(vals)
        elif attr.data_type == "INT":
            vals = [0] * n
            attr.data.foreach_get("value", vals)
            out["attrs"][name] = vals
    return out


bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=1.0)
obj = bpy.context.active_object
src = obj.data
n = len(src.vertices)
normals = [0.0] * (3 * n)
src.vertex_normals.foreach_get("vector", normals)
result = {"input": dump_mesh(src, [])}
result["input"]["N"] = bits(normals)

for case in json.load(open(CASES_PATH)):
    tree = bpy.data.node_groups.new(case["name"], "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n_in = tree.nodes.new("NodeGroupInput")
    n_out = tree.nodes.new("NodeGroupOutput")
    node = tree.nodes.new("GeometryNodeToast")
    text = bpy.data.texts.new(case["name"])
    text.write(case["code"])
    node.text = text
    blender_addon.update_node(node, force=True)

    tree.links.new(n_in.outputs[0], node.inputs["Geometry"])
    if case.get("input1"):
        tree.links.new(n_in.outputs[0], node.inputs["Input 1"])
    tree.links.new(node.outputs["Geometry"], n_out.inputs[0])
    for name, value in case.get("params", {}).items():
        node.inputs[name].default_value = value

    mod = obj.modifiers.new(case["name"], "NODES")
    mod.node_group = tree
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    out = dump_mesh(ev.data, case.get("attrs", []))
    out["error"] = node.error
    out["sockets"] = [s.identifier for s in node.inputs]
    out["kernel_path"] = node.kernel_path
    result[case["name"]] = out
    obj.modifiers.remove(mod)

json.dump(result, open(OUT_PATH, "w"))
print("WROTE", OUT_PATH)
