# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Benchmark: noise displace as a Toast node vs the equivalent node tree, in the fork.

  blender -b --factory-startup --enable-autoexec [-t N] --python bench_blender.py -- <repo> [subdiv]

Both variants compute, per point: n = noise(P * freq); height = n; P += N * n * amp.
The node tree is the efficient hand-built version: Store Named Attribute (height) evaluated on
the input positions, then Set Position with offset N * height * amp.
Prints median modifier evaluation times and checks both give the same bits.
"""

import statistics
import struct
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
REPO = argv[0]
SUBDIV = int(argv[1]) if len(argv) > 1 else 8
RUNS = 9
sys.path.insert(0, REPO)

import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()

CODE = """amp = param("amp", 0.2)
freq = param("freq", 4.0)
n = noise(@position * freq)
@position += @normal * n * amp
@height = n
"""


def new_tree(name):
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    return tree, tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")


def tree_passthrough():
    tree, n_in, n_out = new_tree("passthrough")
    tree.links.new(n_in.outputs[0], n_out.inputs[0])
    return tree, lambda v: None


def tree_toast():
    tree, n_in, n_out = new_tree("toast")
    node = tree.nodes.new("GeometryNodeToast")
    text = bpy.data.texts.new("bench")
    text.write(CODE)
    node.text = text
    t0 = time.perf_counter()
    blender_addon.update_node(node, force=True)
    print(f"toast compile+set (maybe cached): {time.perf_counter() - t0:.3f} s")
    assert not node.error, node.error
    tree.links.new(n_in.outputs[0], node.inputs["Geometry"])
    tree.links.new(node.outputs["Geometry"], n_out.inputs[0])

    def set_amp(v):
        node.inputs["amp"].default_value = v

    return tree, set_amp


def tree_nodes():
    tree, n_in, n_out = new_tree("nodes")
    L = tree.links.new
    pos = tree.nodes.new("GeometryNodeInputPosition")
    normal = tree.nodes.new("GeometryNodeInputNormal")
    scale_p = tree.nodes.new("ShaderNodeVectorMath")
    scale_p.operation = "SCALE"
    scale_p.inputs["Scale"].default_value = 4.0
    L(pos.outputs[0], scale_p.inputs[0])
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.noise_dimensions = "3D"
    noise.noise_type = "FBM"
    noise.normalize = True
    noise.inputs["Scale"].default_value = 1.0
    noise.inputs["Detail"].default_value = 0.0
    noise.inputs["Distortion"].default_value = 0.0
    L(scale_p.outputs[0], noise.inputs["Vector"])
    store = tree.nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type = "FLOAT"
    store.domain = "POINT"
    store.inputs["Name"].default_value = "height"
    L(n_in.outputs[0], store.inputs["Geometry"])
    L(noise.outputs["Factor"], [s for s in store.inputs if s.name == "Value" and s.enabled][0])
    height = tree.nodes.new("GeometryNodeInputNamedAttribute")
    height.data_type = "FLOAT"
    height.inputs["Name"].default_value = "height"
    s1 = tree.nodes.new("ShaderNodeVectorMath")
    s1.operation = "SCALE"
    L(normal.outputs[0], s1.inputs[0])
    L([s for s in height.outputs if s.enabled and s.name == "Attribute"][0], s1.inputs["Scale"])
    s2 = tree.nodes.new("ShaderNodeVectorMath")
    s2.operation = "SCALE"
    s2.inputs["Scale"].default_value = 0.2
    L(s1.outputs[0], s2.inputs[0])
    setpos = tree.nodes.new("GeometryNodeSetPosition")
    L(store.outputs[0], setpos.inputs["Geometry"])
    L(s2.outputs[0], setpos.inputs["Offset"])
    L(setpos.outputs[0], n_out.inputs[0])

    def set_amp(v):
        s2.inputs["Scale"].default_value = v

    return tree, set_amp


def tree_cpp():
    tree, n_in, n_out = new_tree("cpp")
    node = tree.nodes.new("GeometryNodeToastNoiseDisplaceCpp")
    tree.links.new(n_in.outputs[0], node.inputs["Geometry"])
    tree.links.new(node.outputs["Geometry"], n_out.inputs[0])

    def set_amp(v):
        node.inputs["Amp"].default_value = v

    return tree, set_amp


def bits(mesh, attr, comp):
    n = len(mesh.vertices)
    vals = [0.0] * (n * comp)
    a = mesh.attributes.get(attr)
    if a is None:
        return None
    a.data.foreach_get("vector" if comp == 3 else "value", vals)
    return struct.pack(f"<{len(vals)}f", *vals)


bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=SUBDIV, radius=1.0)
obj = bpy.context.active_object
print(f"points: {len(obj.data.vertices):,}")

results = {}
outputs = {}
variants = [("passthrough", tree_passthrough), ("toast", tree_toast), ("nodes", tree_nodes)]
if hasattr(bpy.types, "GeometryNodeToastNoiseDisplaceCpp"):
    variants.append(("cpp", tree_cpp))
for name, make in variants:
    tree, set_amp = make()
    mod = obj.modifiers.new(name, "NODES")
    mod.node_group = tree
    times = []
    for k in range(RUNS + 1):
        set_amp(0.2 + k * 1e-6 if k < RUNS else 0.2)
        obj.update_tag(refresh={"DATA"})
        t0 = time.perf_counter()
        bpy.context.view_layer.update()
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
        times.append(time.perf_counter() - t0)
    results[name] = statistics.median(times[1:RUNS])
    outputs[name] = (bits(ev, "position", 3), bits(ev, "height", 1))
    obj.modifiers.remove(mod)

base = results["passthrough"]
print(f"{'variant':12} {'total ms':>10} {'minus base ms':>14}")
for name, t in results.items():
    print(f"{name:12} {t * 1000:10.2f} {(t - base) * 1000:14.2f}")
print(f"speedup toast vs nodes (minus base): {(results['nodes'] - base) / (results['toast'] - base):.2f}x")
for other in [n for n in outputs if n not in ("passthrough", "toast")]:
    print(f"same bits as {other}: P {outputs['toast'][0] == outputs[other][0]}, "
          f"height {outputs['toast'][1] == outputs[other][1]}")
if "cpp" in results:
    print(f"toast vs hand C++ (minus base): {(results['toast'] - base) / (results['cpp'] - base):.2f}x the time")
