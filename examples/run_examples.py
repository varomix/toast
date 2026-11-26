# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Play an example file forward, time each frame, and optionally render a still.

  blender -b --enable-autoexec examples/<name>.blend --python examples/run_examples.py -- \
      --frames 120 [--render out.png] [--set "Node/param=value" ...] [--count N]

Prints one JSON line starting with RESULT: element counts and milliseconds per frame. Use it to
see how far Toast goes on your machine (raise counts with --set).
"""

import json
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
frames = 60
render = None
sets = []
k = 0
while k < len(argv):
    if argv[k] == "--frames":
        frames = int(argv[k + 1])
        k += 2
    elif argv[k] == "--render":
        render = argv[k + 1]
        k += 2
    elif argv[k] == "--set":
        sets.append(argv[k + 1])
        k += 2
    else:
        raise SystemExit(f"unknown argument {argv[k]}")

# Compile kernels missing from this machine's cache (the add-on does this on load too).
from toast import blender_addon  # noqa: E402

for node in blender_addon._toast_nodes():
    blender_addon.update_node(node, debounce=False)
errors = {n.name: n.error for n in blender_addon._toast_nodes() if n.error}

for item in sets:
    path, value = item.split("=", 1)
    tree_node, socket = path.rsplit("/", 1)
    node = None
    for tree in bpy.data.node_groups:
        node = tree.nodes.get(tree_node) or next((n for n in tree.nodes if n.label == tree_node), None)
        if node:
            break
    if node is None:
        raise SystemExit(f"no node {tree_node}")
    sock = node.inputs[socket]
    sock.default_value = type(sock.default_value)(eval(value)) if not hasattr(sock.default_value, "__len__") else eval(value)

scene = bpy.context.scene
obj = next(o for o in scene.objects if any(m.type == "NODES" for m in o.modifiers) and
           o.modifiers[0].name == "Toast example")  # fmt: skip
times = []
for f in range(scene.frame_start, scene.frame_start + frames):
    t0 = time.perf_counter()
    scene.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    geo = ev.evaluated_geometry()
    times.append((time.perf_counter() - t0) * 1000)


def counts(geo):
    out = {}
    if geo.mesh and len(geo.mesh.vertices):
        out["mesh_points"] = len(geo.mesh.vertices)
        out["mesh_faces"] = len(geo.mesh.polygons)
    if geo.pointcloud:
        out["cloud_points"] = len(geo.pointcloud.points)
    if geo.curves:
        out["curves"] = len(geo.curves.curves)
        out["curve_points"] = len(geo.curves.points)
    inst = geo.instances_pointcloud()
    if inst is not None:
        out["instances"] = len(inst.points)
    return out


warnings = sorted({getattr(w, "message", str(w)) for o in scene.objects for m in o.modifiers
                   if m.type == "NODES" for w in m.node_warnings})  # fmt: skip
result = {
    "file": bpy.data.filepath,
    "errors": errors,
    "warnings": warnings,
    "frames": frames,
    "counts": counts(geo),
    "ms_first": round(times[0], 1),
    "ms_avg": round(sum(times[1:]) / max(len(times) - 1, 1), 1),
    "ms_max": round(max(times[1:] or times), 1),
    "ms_last": round(times[-1], 1),
}
if render:
    scene.render.filepath = render
    bpy.ops.render.render(write_still=True)
print("RESULT " + json.dumps(result))
