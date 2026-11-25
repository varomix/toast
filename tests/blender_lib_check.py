# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""toast_lib from Text data-blocks in the fork: prints RESULT <json>.

  blender -b --factory-startup --enable-autoexec --python blender_lib_check.py -- <repo>
"""

import json
import sys
import time

import bpy

REPO = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, REPO)
import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()

lib = bpy.data.texts.new("toast_lib.mathx")
lib.write("def sq(x):\n    return x * x\n")

bpy.ops.mesh.primitive_plane_add(size=2)
obj = bpy.context.active_object
tree = bpy.data.node_groups.new("t", "GeometryNodeTree")
tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
i, o = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
node = tree.nodes.new("GeometryNodeToast")
code = bpy.data.texts.new("code")
code.write("from toast_lib.mathx import sq\n@a = sq(@index + 1.0)\n")
node.text = code
tree.links.new(i.outputs[0], node.inputs[0])
tree.links.new(node.outputs[0], o.inputs[0])
obj.modifiers.new("t", "NODES").node_group = tree


def values():
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    vals = [0.0] * len(mesh.vertices)
    mesh.attributes["a"].data.foreach_get("value", vals)
    return vals


result = {}
blender_addon.update_node(node, force=True)
result["first"] = values()
result["first_error"] = node.error

# Edit the library: the node is stale, recompiles after the debounce.
lib.clear()
lib.write("def sq(x):\n    return x * x * x\n")
result["immediate"] = blender_addon.update_node(node)
time.sleep(blender_addon.DEBOUNCE_SECONDS + 0.1)
result["after_debounce"] = blender_addon.update_node(node)
result["second"] = values()

# Remove the library: an error naming it.
bpy.data.texts.remove(lib)
blender_addon.update_node(node, force=True)
result["missing_error"] = node.error
print("RESULT " + json.dumps(result))
