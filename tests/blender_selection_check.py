# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Toast node's Selection input in the fork: prints RESULT <json>.

  blender -b --factory-startup --enable-autoexec --python blender_selection_check.py -- <repo> <cases>
cases: [[run_over, domain, code], ...]; the selection is a boolean attribute "sel" on that domain:
x > 0 of the element's position (face centers for faces).
"""

import json
import struct
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
REPO, CASES = argv[0], json.loads(argv[1])
sys.path.insert(0, REPO)
import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()


def bits(values):
    return [struct.unpack("<I", struct.pack("<f", v))[0] for v in values]


result = []
for run_over, domain, code in CASES:
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=5, y_subdivisions=4, size=2)
    obj = bpy.context.active_object
    mesh = obj.data
    if domain == "POINT":
        sel = [v.co.x > 0 for v in mesh.vertices]
    else:
        sel = [p.center.x > 0 for p in mesh.polygons]
    mesh.attributes.new("sel", "BOOLEAN", domain).data.foreach_set("value", sel)
    pos = [0.0] * (3 * len(mesh.vertices))
    mesh.attributes["position"].data.foreach_get("vector", pos)
    inp = {"P": bits(pos), "faces": [list(p.vertices) for p in mesh.polygons], "sel": sel}

    tree = bpy.data.node_groups.new("t", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    i, o = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    named = tree.nodes.new("GeometryNodeInputNamedAttribute")
    named.data_type = "BOOLEAN"
    named.inputs["Name"].default_value = "sel"
    node = tree.nodes.new("GeometryNodeToast")
    node.run_over = run_over
    text = bpy.data.texts.new("t")
    text.write(code)
    node.text = text
    blender_addon.update_node(node, force=True)
    tree.links.new(i.outputs[0], node.inputs["Geometry"])
    tree.links.new([s for s in named.outputs if s.enabled and s.name == "Attribute"][0],
                   node.inputs["Selection"])  # fmt: skip
    tree.links.new(node.outputs[0], o.inputs[0])
    mod = obj.modifiers.new("t", "NODES")
    mod.node_group = tree
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    out = {"input": inp, "error": node.error, "warnings": [w.message for w in mod.node_warnings],
           "faces": [list(p.vertices) for p in ev.polygons], "attrs": {}}
    pos = [0.0] * (3 * len(ev.vertices))
    ev.attributes["position"].data.foreach_get("vector", pos)
    out["P"] = bits(pos)
    for a in ev.attributes:
        if a.data_type == "INT" and not a.name.startswith("."):
            v = [0] * len(a.data)
            a.data.foreach_get("value", v)
            out["attrs"][a.name] = v
    result.append(out)
    bpy.data.objects.remove(obj)
print("RESULT " + json.dumps(result))
