# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""point_neighbors() after a topology change, with the node's neighbor table cache warm.

Toast A (neighbor count) -> Delete Geometry (one point) -> Toast B (neighbor count), evaluated
on several frames: B must see the new topology, never a cached table of A's mesh.

  blender -b --factory-startup --enable-autoexec --python blender_neighbors_cache_check.py -- <repo>
Prints RESULT {"frames": [{"points", "ok"}...]}.
"""

import json
import sys

import bpy

REPO = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, REPO)

import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()
bpy.ops.mesh.primitive_grid_add(x_subdivisions=6, y_subdivisions=6)
obj = bpy.context.active_object
tree = bpy.data.node_groups.new("t", "GeometryNodeTree")
tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
gin, gout = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
CODE = "k = 0\nfor q in point_neighbors(0, @index, 16):\n    k += 1\n@{} = k\n"


def toast_node(name):
    node = tree.nodes.new("GeometryNodeToast")
    text = bpy.data.texts.new(name)
    text.write(CODE.format(name))
    node.text = text
    blender_addon.update_node(node, force=True)
    assert not node.error, node.error
    return node


a, b = toast_node("na"), toast_node("nb")
delete = tree.nodes.new("GeometryNodeDeleteGeometry")
index = tree.nodes.new("GeometryNodeInputIndex")
equal = tree.nodes.new("FunctionNodeCompare")
equal.data_type = "INT"
equal.operation = "EQUAL"
tree.links.new(index.outputs[0], equal.inputs[0])
equal.inputs[1].default_value = 7
tree.links.new(equal.outputs[0], delete.inputs["Selection"])
tree.links.new(gin.outputs[0], a.inputs[0])
tree.links.new(a.outputs[0], delete.inputs[0])
tree.links.new(delete.outputs[0], b.inputs[0])
tree.links.new(b.outputs[0], gout.inputs[0])
obj.modifiers.new("m", "NODES").node_group = tree

frames = []
for frame in (1, 2, 3):
    bpy.context.scene.frame_set(frame)
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    counts = [d.value for d in mesh.attributes["nb"].data]
    expect = [0] * len(mesh.vertices)
    for e in mesh.edges:
        expect[e.vertices[0]] += 1
        expect[e.vertices[1]] += 1
    frames.append({"points": len(mesh.vertices), "ok": counts == expect})
print("RESULT " + json.dumps({"frames": frames}))
