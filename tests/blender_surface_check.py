# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""ray_cast / closest_point / sample_nearest_surface in the fork, on an ico sphere fed to both
inputs. Prints RESULT <json>.

  blender -b --factory-startup --enable-autoexec --python blender_surface_check.py -- <repo> '[[run_over, code], ...]'
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


def floats(mesh, name, comps):
    a = mesh.attributes[name]
    v = [0.0] * (comps * len(a.data))
    a.data.foreach_get("vector" if comps == 3 else "value", v)
    return bits(v)


result = {"runs": []}
for run_over, code in CASES:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0)
    obj = bpy.context.active_object
    mesh = obj.data
    w = mesh.attributes.new("w", "FLOAT", "POINT")
    w.data.foreach_set("value", [v.co.x * 2 + v.co.z for v in mesh.vertices])
    result["input"] = {"P": floats(mesh, "position", 3), "w": floats(mesh, "w", 1),
                       "faces": [list(p.vertices) for p in mesh.polygons]}
    tree = bpy.data.node_groups.new("t", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    i, o = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    node = tree.nodes.new("GeometryNodeToast")
    node.run_over = run_over
    text = bpy.data.texts.new("t")
    text.write(code)
    node.text = text
    blender_addon.update_node(node, force=True)
    tree.links.new(i.outputs[0], node.inputs["Geometry"])
    tree.links.new(i.outputs[0], node.inputs["Input 1"])
    tree.links.new(node.outputs[0], o.inputs[0])
    mod = obj.modifiers.new("t", "NODES")
    mod.node_group = tree
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    out = {"error": node.error, "warnings": [x.message for x in mod.node_warnings], "attrs": {}}
    for a in ev.attributes:
        if a.name.startswith("."):
            continue
        if a.data_type == "FLOAT_VECTOR":
            out["attrs"][a.name] = floats(ev, a.name, 3)
        elif a.data_type == "FLOAT":
            out["attrs"][a.name] = floats(ev, a.name, 1)
        elif a.data_type in ("INT", "BOOLEAN"):
            v = [0] * len(a.data)
            a.data.foreach_get("value", v)
            out["attrs"][a.name] = [int(x) for x in v]
    result["runs"].append(out)
    bpy.data.objects.remove(obj)
print("RESULT " + json.dumps(result))
