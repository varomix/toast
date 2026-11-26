# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Benchmark: one reaction-diffusion step (examples/src/reaction_diffusion/step.py) as a Toast node
vs a node tree doing the same with Blur Attribute, in the fork.

  blender -b --factory-startup --enable-autoexec [-t N] --python bench_reaction_diffusion.py -- \
      <repo> [subdiv]

Unlike bench_blender.py this exercises point_neighbors(). Blur Attribute averages a point with its
neighbors while step.py averages the neighbors only, so the results differ slightly: this
compares speed, not bits. Prints median modifier evaluation times minus a pass-through.
"""

import random
import statistics
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
REPO = argv[0]
SUB = int(argv[1]) if len(argv) > 1 else 8
sys.path.insert(0, REPO)

import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

toast.register()

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=SUB)
obj = bpy.context.active_object
n = len(obj.data.vertices)
rng = random.Random(0)
for name in ("a", "b"):
    attr = obj.data.attributes.new(name, "FLOAT", "POINT")
    values = [1.0] * n if name == "a" else [float(rng.random() < 0.1) for _ in range(n)]
    attr.data.foreach_set("value", values)


def group(name):
    tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    return tree, tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")


def toast_tree():
    tree, gin, gout = group("toast")
    node = tree.nodes.new("GeometryNodeToast")
    text = bpy.data.texts.new("step")
    text.write(open(REPO + "/examples/src/reaction_diffusion/step.py").read())
    node.text = text
    blender_addon.update_node(node, force=True)
    assert not node.error, node.error
    tree.links.new(gin.outputs[0], node.inputs[0])
    tree.links.new(node.outputs[0], gout.inputs[0])
    return tree


def node_tree():
    """step.py with nodes: laplacian = Blur Attribute - value, then the same reaction math."""
    tree, gin, gout = group("nodes")
    nodes, links = tree.nodes, tree.links

    def math(op, *inputs):
        m = nodes.new("ShaderNodeMath")
        m.operation = op
        for k, v in enumerate(inputs):
            if isinstance(v, (int, float)):
                m.inputs[k].default_value = v
            else:
                links.new(v, m.inputs[k])
        return m.outputs[0]

    def named(name):
        node = nodes.new("GeometryNodeInputNamedAttribute")
        node.data_type = "FLOAT"
        node.inputs["Name"].default_value = name
        return node.outputs["Attribute"]

    def blur(value):
        node = nodes.new("GeometryNodeBlurAttribute")
        node.data_type = "FLOAT"
        links.new(value, node.inputs["Value"])
        node.inputs["Iterations"].default_value = 1
        return node.outputs[0]

    def clamp01(v):
        return math("MINIMUM", math("MAXIMUM", v, 0.0), 1.0)

    def store(geometry, name, value):
        node = nodes.new("GeometryNodeStoreNamedAttribute")
        node.data_type = "FLOAT"
        node.inputs["Name"].default_value = name
        links.new(geometry, node.inputs[0])
        links.new(value, node.inputs["Value"])
        return node.outputs[0]

    a, b = named("a"), named("b")
    lap_a, lap_b = math("SUBTRACT", blur(a), a), math("SUBTRACT", blur(b), b)
    position = nodes.new("GeometryNodeInputPosition")
    xyz = nodes.new("ShaderNodeSeparateXYZ")
    links.new(position.outputs[0], xyz.inputs[0])
    t = clamp01(math("MULTIPLY_ADD", xyz.outputs["Z"], 0.5, 0.5))
    feed = math("MULTIPLY_ADD", t, 0.025, 0.030)
    kill = math("MULTIPLY_ADD", t, 0.005, 0.057)
    reaction = math("MULTIPLY", a, math("MULTIPLY", b, b))
    new_a = clamp01(math("ADD", a, math("ADD", math("SUBTRACT", lap_a, reaction),
                                        math("MULTIPLY", feed, math("SUBTRACT", 1.0, a)))))
    new_b = clamp01(math("ADD", b, math("SUBTRACT", math("ADD", math("MULTIPLY", lap_b, 0.5), reaction),
                                        math("MULTIPLY", math("ADD", kill, feed), b))))
    # Both new values must come from the old ones: b goes to a temporary first.
    geometry = store(gin.outputs[0], "b_new", new_b)
    geometry = store(geometry, "a", new_a)
    geometry = store(geometry, "b", named("b_new"))
    links.new(geometry, gout.inputs[0])
    return tree


def passthrough():
    tree, gin, gout = group("pass")
    tree.links.new(gin.outputs[0], gout.inputs[0])
    return tree


def bench(tree, runs=15):
    mod = obj.modifiers.new(tree.name, "NODES")
    mod.node_group = tree
    times = []
    for _ in range(runs):
        mod.show_viewport = False
        bpy.context.evaluated_depsgraph_get()
        mod.show_viewport = True
        t0 = time.perf_counter()
        bpy.context.evaluated_depsgraph_get()
        times.append((time.perf_counter() - t0) * 1000)
    obj.modifiers.remove(mod)
    return statistics.median(times)


base = bench(passthrough())
toast_ms = bench(toast_tree()) - base
nodes_ms = bench(node_tree()) - base
print(f"points: {n:,}")
print(f"toast  {toast_ms:7.2f} ms")
print(f"nodes  {nodes_ms:7.2f} ms")
print(f"speedup toast vs nodes: {nodes_ms / toast_ms:.2f}x")
