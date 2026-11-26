# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run-over modes in the fork: prints RESULT <json>.

  blender -b --factory-startup --enable-autoexec --python blender_domains_check.py -- <repo> <cases.json>
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


def bits(values):
    return [struct.unpack("<I", struct.pack("<f", v))[0] for v in values]


def dump(mesh):
    out = {"position": None, "faces": [list(f.vertices) for f in mesh.polygons],
           "edges": [list(e.vertices) for e in mesh.edges], "attrs": {}}
    pos = [0.0] * (3 * len(mesh.vertices))
    if pos:  # A mesh without points may have no position attribute.
        mesh.attributes["position"].data.foreach_get("vector", pos)
    out["P"] = bits(pos)
    for a in mesh.attributes:
        if a.name.startswith(".") or a.name == "position":
            continue
        n = len(a.data)
        if a.data_type == "FLOAT":
            v = [0.0] * n
            a.data.foreach_get("value", v)
            v = bits(v)
        elif a.data_type == "INT":
            v = [0] * n
            a.data.foreach_get("value", v)
        elif a.data_type in ("FLOAT_VECTOR",):
            v = [0.0] * (3 * n)
            a.data.foreach_get("vector", v)
            v = bits(v)
        elif a.data_type == "FLOAT_COLOR":
            v = [0.0] * (4 * n)
            a.data.foreach_get("color", v)
            v = bits(v)
        else:
            continue
        out["attrs"][a.name] = {"domain": a.domain, "type": a.data_type, "values": v}
    return out


result = {}
for case in json.load(open(CASES)):
    if case.get("empty"):  # An object whose mesh has no elements at all.
        obj = bpy.data.objects.new("empty", bpy.data.meshes.new("empty"))
        bpy.context.scene.collection.objects.link(obj)
    else:
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=3, size=2)
        obj = bpy.context.active_object
    src = dump(obj.data)
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
    tree.links.new(i.outputs[0], node.inputs[0])
    tree.links.new(node.outputs[0], o.inputs[0])
    mod = obj.modifiers.new("t", "NODES")
    mod.node_group = tree
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    out = dump(ev)
    out["input"] = src
    out["error"] = node.error
    out["warnings"] = [getattr(w, "message", str(w)) for w in mod.node_warnings]
    result[case["name"]] = out
    bpy.data.objects.remove(obj)
print("RESULT " + json.dumps(result))
