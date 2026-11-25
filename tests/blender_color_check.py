# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""@color mapping in the fork: run inside Blender, prints one JSON line starting with RESULT.

  blender -b --factory-startup --enable-autoexec --python blender_color_check.py -- <repo>
"""

import json
import sys

import bpy

REPO = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, REPO)
import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()


def run(code, setup=None):
    bpy.ops.mesh.primitive_plane_add(size=2)
    obj = bpy.context.active_object
    if setup:
        setup(obj.data)
    tree = bpy.data.node_groups.new("t", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    i, o = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    node = tree.nodes.new("GeometryNodeToast")
    text = bpy.data.texts.new("t")
    text.write(code)
    node.text = text
    blender_addon.update_node(node, force=True)
    tree.links.new(i.outputs[0], node.inputs[0])
    tree.links.new(node.outputs[0], o.inputs[0])
    obj.modifiers.new("t", "NODES").node_group = tree
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    out = {"attrs": {}, "active": mesh.color_attributes.active_color_name}
    for a in mesh.attributes:
        if a.name.startswith(".") or a.name == "position":
            continue
        n = len(a.data)
        if a.data_type in ("FLOAT_COLOR", "BYTE_COLOR"):
            vals = [0.0] * (4 * n)
            a.data.foreach_get("color", vals)
            vals = [vals[k:k + 4] for k in range(0, len(vals), 4)]
        elif a.data_type == "FLOAT":
            vals = [0.0] * n
            a.data.foreach_get("value", vals)
        else:
            continue
        out["attrs"][a.name] = {"type": a.data_type, "domain": a.domain, "values": vals}
    errors = []
    for mod in obj.modifiers:
        errors += [getattr(e, "message", str(e)) for e in mod.node_warnings]
    out["node_error"] = node.error
    out["modifier_warnings"] = errors
    bpy.data.objects.remove(obj)
    return out


def add_float_color(mesh):
    attr = mesh.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    attr.data.foreach_set("color", [0.8, 0.6, 0.4, 0.3] * len(mesh.vertices))
    mesh.color_attributes.active_color = attr


def add_byte_corner_color(mesh):
    attr = mesh.color_attributes.new("Bytes", "BYTE_COLOR", "CORNER")
    mesh.color_attributes.active_color = attr


results = {
    "create": run("@color = (@position.x, 0.5, 1.0)\n"),
    "existing": run("@color *= 0.5\n", add_float_color),
    "byte_read": run("@r = @color.x + 1.0\n", add_byte_corner_color),
    "byte_write": run("@color = (1, 0, 0)\n", add_byte_corner_color),
}
print("RESULT " + json.dumps(results))
