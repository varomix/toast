# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A node whose kernel was built for another ABI (e.g. a file saved with an older Toast) must
warn, not crash, and recompile on load. Prints RESULT <json>.

  blender -b --factory-startup --enable-autoexec --python blender_stale_check.py -- <repo> <tmp>
"""

import json
import subprocess
import sys
from pathlib import Path

import bpy

REPO, TMP = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, REPO)
import toast  # noqa: E402
from toast import blender_addon  # noqa: E402
from toast.build import CXX_FLAGS, RUNTIME_DIR, find_compiler  # noqa: E402

toast.register()

bpy.ops.mesh.primitive_plane_add(size=2)
obj = bpy.context.active_object
tree = bpy.data.node_groups.new("t", "GeometryNodeTree")
tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
i, o = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
node = tree.nodes.new("GeometryNodeToast")
text = bpy.data.texts.new("t")
text.write("@a = 1.0\n")
node.text = text
tree.links.new(i.outputs[0], node.inputs[0])
tree.links.new(node.outputs[0], o.inputs[0])
mod = obj.modifiers.new("t", "NODES")
mod.node_group = tree
blender_addon.update_node(node, force=True)

# The same kernel, but claiming ABI 1, at its own path.
cpp = Path(node.kernel_path).with_suffix(".cpp").read_text()
cpp = cpp.replace("return TOAST_ABI_VERSION;", "return 1;")
src, so = Path(TMP) / "stale.cpp", Path(TMP) / "stale.so"
src.write_text(cpp)
subprocess.run([find_compiler(), *CXX_FLAGS, f"-I{RUNTIME_DIR}", str(src), "-o", str(so)],
               check=True)  # fmt: skip
node.kernel_path = str(so)
node.source_hash = "from-an-older-toast"


def evaluate():
    bpy.context.view_layer.update()
    mesh = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    return [w.message for w in mod.node_warnings], "a" in mesh.attributes


result = {}
result["stale"] = evaluate()
blender_addon._on_load(None)
result["after_load"] = evaluate()
result["kernel_is_new"] = node.kernel_path != str(so)
print("RESULT " + json.dumps(result))
