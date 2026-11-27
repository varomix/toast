# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Toast shader node (EEVEE) checks, run inside Blender:

    blender -b --factory-startup --enable-autoexec --python tests/blender_shader_check.py -- OUT
    blender -b --factory-startup --python tests/blender_shader_check.py -- OUT untrusted
    (add "cycles" after OUT for Cycles on the CPU)

Renders a plane (seen from above, orthographic, 32x32, one sample) whose material emits the
Toast node's output, and the same with Blender's own nodes where there is one, and prints one
JSON line per case: {"case", "max_diff", "error", ...}. test_toast.py checks the numbers.
"""

import json
import sys
from pathlib import Path

import addon_utils
import bpy

addon_utils.enable("toast", default_set=True)
from toast import blender_addon as ba  # noqa: E402

ARGS = sys.argv[sys.argv.index("--") + 1:]
OUT = Path(ARGS[0])
# "cycles": render with Cycles on the CPU instead of EEVEE.
CYCLES = "cycles" in ARGS
OUT.mkdir(parents=True, exist_ok=True)
RES = 32

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
if CYCLES:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.cycles.pixel_filter_type = "BOX"
    scene.cycles.filter_width = 0.01
    scene.cycles.seed = 0
else:
    scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = scene.render.resolution_y = RES
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 1
scene.view_settings.view_transform = "Standard"
scene.render.image_settings.file_format = "OPEN_EXR"
scene.render.image_settings.color_depth = "32"
world = bpy.data.worlds.new("w")
scene.world = world

bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
# A float point attribute for @wear: the vertex's x (-1 or 1), interpolated across the plane.
wear = plane.data.attributes.new("wear", "FLOAT", "POINT")
for i, v in enumerate(plane.data.vertices):
    wear.data[i].value = v.co.x
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = 2.0
cam.location = (0, 0, 5)
scene.collection.objects.link(cam)
scene.camera = cam

_count = 0


def render():
    """Render and return the pixels as a list of RES*RES (r, g, b, a)."""
    global _count
    _count += 1
    path = OUT / f"r{_count}.exr"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(str(path))
    px = list(img.pixels)
    bpy.data.images.remove(img)
    return [tuple(px[i:i + 4]) for i in range(0, len(px), 4)]


def material(build):
    """A new material on the plane: build(nodes, links) returns the socket to emit."""
    mat = bpy.data.materials.new("m")
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    emit = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(build(nt.nodes, nt.links), emit.inputs["Color"])
    nt.links.new(emit.outputs[0], out.inputs["Surface"])
    plane.data.materials.clear()
    plane.data.materials.append(mat)
    return mat


def toast_node(nodes, code, name="t"):
    node = nodes.new("ShaderNodeToast")
    text = bpy.data.texts.new(name + ".py")
    text.write(code)
    node.text = text
    ba.update_node(node, force=True)
    return node


def diff(a, b, channels=3):
    return max(abs(x[c] - y[c]) for x, y in zip(a, b) for c in range(channels))


def report(case, **values):
    print("TOASTSHADER " + json.dumps({"case": case, **values}), flush=True)


def compare(case, code, reference, socket="c", setup=None):
    """Toast code (output socket `socket`) against a node setup building the same values."""
    errors = []

    def build_toast(nodes, links):
        node = toast_node(nodes, code)
        errors.append(node.error)
        if node.error:
            report(case, error=node.error)
            raise SystemExit(f"{case}: {node.error}")
        if setup:
            setup(node, nodes, links)
        return node.outputs[socket]

    material(build_toast)
    a = render()
    material(reference)
    b = render()
    report(case, max_diff=diff(a, b), error=errors[0], mean=sum(p[0] for p in a) / len(a))


def tex_noise(detail=0.0, roughness=0.5, lacunarity=2.0, scale=4.0, output="Fac"):
    def build(nodes, links):
        n = nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        n.inputs["Roughness"].default_value = roughness
        n.inputs["Lacunarity"].default_value = lacunarity
        n.inputs["Distortion"].default_value = 0.0
        return n.outputs[output]
    return build


def tex_voronoi(output, scale=5.0, randomness=0.8):
    def build(nodes, links):
        n = nodes.new("ShaderNodeTexVoronoi")
        n.inputs["Scale"].default_value = scale
        n.inputs["Randomness"].default_value = randomness
        return n.outputs[output]
    return build


def generated_rg(b):
    def build(nodes, links):
        tc = nodes.new("ShaderNodeTexCoord")
        sep = nodes.new("ShaderNodeSeparateXYZ")
        comb = nodes.new("ShaderNodeCombineColor")
        links.new(tc.outputs["Generated"], sep.inputs[0])
        links.new(sep.outputs["X"], comb.inputs[0])
        links.new(sep.outputs["Y"], comb.inputs[1])
        comb.inputs[2].default_value = b
        return comb.outputs[0]
    return build


def attribute(name):
    def build(nodes, links):
        n = nodes.new("ShaderNodeAttribute")
        n.attribute_name = name
        return n.outputs["Fac"]
    return build


def constant(rgb):
    def build(nodes, links):
        n = nodes.new("ShaderNodeRGB")
        n.outputs[0].default_value = (*rgb, 1.0)
        return n.outputs[0]
    return build


if "untrusted" in ARGS:
    # Run without --enable-autoexec: the code doesn't run.
    node = []
    material(lambda nodes, links: (node.append(toast_node(nodes, 'output("c", vec3(0.5))\n')),
                                   node[0].outputs["c"])[1])  # fmt: skip
    px = render()
    # The code would give 0.5; without it the emission gets the outputs' default (EEVEE) or
    # its own Color (Cycles, which leaves the node out).
    report("untrusted", ran=diff(px, [(0.5, 0.5, 0.5, 1.0)] * len(px)) < 1e-6, error=node[0].error)
    print("TOASTSHADER done", flush=True)
    sys.exit(0)

compare("generated", 'output("c", vec4(@generated.x, @generated.y, param("b", 0.25), 1.0))\n',
        generated_rg(0.25))  # fmt: skip
compare("noise", 'n = noise(@generated * 4.0)\noutput("c", vec4(n, n, n, 1.0))\n', tex_noise())
compare("fbm", 'output("c", fbm(@generated * 4.0, 3.5, 0.6, 2.2))\n',
        tex_noise(detail=3.5, roughness=0.6, lacunarity=2.2))  # fmt: skip
compare("voronoi_color", 'output("c", voronoi(@generated * 5.0, 0.8).color)\n',
        tex_voronoi("Color"))  # fmt: skip
compare("voronoi_distance", 'output("c", voronoi(@generated * 5.0, 0.8).distance)\n',
        tex_voronoi("Distance"))  # fmt: skip
def _wear_ref(nodes, links):
    attr = attribute("wear")(nodes, links)
    m = nodes.new("ShaderNodeMath")
    m.operation = "MULTIPLY_ADD"
    links.new(attr, m.inputs[0])
    m.inputs[1].default_value = 0.5
    m.inputs[2].default_value = 0.5
    return m.outputs[0]


compare("attribute", "@wear: float\noutput(\"c\", @wear * 0.5 + 0.5)\n", _wear_ref)


def set_params(node, nodes, links):
    node.inputs["k"].default_value = 2
    node.inputs["flip"].default_value = False
    node.inputs["v"].default_value = (0.1, 0.2, 0.3)


compare("params", '''k = param("k", 3)
v = param("v", (0.5, 0.5, 0.5))
flip = param("flip", True)
output("c", vec3(1.0) - v if flip else v * float(k))
''', constant((0.2, 0.4, 0.6)), setup=set_params)


def link_value(node, nodes, links):
    val = nodes.new("ShaderNodeValue")
    val.outputs[0].default_value = 0.375
    links.new(val.outputs[0], node.inputs["x"])


compare("linked_param", 'output("c", vec3(param("x", 0.0)))\n', constant((0.375,) * 3),
        setup=link_value)  # fmt: skip

compare("helpers_loops", '''def tri(x: float) -> float:
    return abs(frac(x) - 0.5) * 2.0
s = 0.0
for i in range(4):
    s += tri(0.125 * float(i) + param("o", 0.0))
c = vec3(s / 4.0, 0.0, 0.0)
c.y = 0.5
if s > 100.0:
    c.z = 1.0
output("c", c)
''', constant(((1.0 + 0.75 + 0.5 + 0.25) / 4.0, 0.5, 0.0)))

scene.frame_set(7)
compare("frame", 'output("c", vec3(@frame / 100.0))\n', constant((0.07,) * 3))
scene.frame_set(1)


# Two Toast nodes in one material (different code), plus the same code twice: one definition.
def two_nodes(nodes, links):
    a = toast_node(nodes, 'output("c", vec3(0.25, 0.0, 0.0))\n', "a")
    b = toast_node(nodes, 'output("c", vec3(0.0, 0.5, 0.0))\n', "b")
    b2 = toast_node(nodes, 'output("c", vec3(0.0, 0.5, 0.0))\n', "b2")
    add = nodes.new("ShaderNodeMix")
    add.data_type = "RGBA"
    add.blend_type = "ADD"
    add.inputs["Factor"].default_value = 1.0
    links.new(a.outputs["c"], add.inputs[6])
    mix2 = nodes.new("ShaderNodeMix")
    mix2.data_type = "RGBA"
    mix2.blend_type = "ADD"
    mix2.inputs["Factor"].default_value = 0.5
    links.new(b.outputs["c"], mix2.inputs[6])
    links.new(b2.outputs["c"], mix2.inputs[7])
    links.new(mix2.outputs[2], add.inputs[7])
    report("two_nodes_errors", error=a.error + b.error + b2.error)
    return add.outputs[2]


material(two_nodes)
a = render()
material(constant((0.25, 0.75, 0.0)))
report("two_nodes", max_diff=diff(a, render()), error="")


# A Toast height into the Bump node: the code is evaluated at offset positions too, so the bumped
# normal must match the one from the same noise made with Blender's nodes.
def bumped(height):
    def build(nodes, links):
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 1.0
        bump.inputs["Distance"].default_value = 0.2
        links.new(height(nodes, links), bump.inputs["Height"])
        # Normal (in -1..1) shown as a color in 0..1.
        m = nodes.new("ShaderNodeVectorMath")
        m.operation = "MULTIPLY_ADD"
        links.new(bump.outputs["Normal"], m.inputs[0])
        m.inputs[1].default_value = (0.5, 0.5, 0.5)
        m.inputs[2].default_value = (0.5, 0.5, 0.5)
        return m.outputs[0]
    return build


def toast_height(nodes, links):
    t = toast_node(nodes, 'output("h", fbm(@position * 3.0, 2.0))\n', "bump")
    report("bump_errors", error=t.error)
    return t.outputs["h"]


def nodes_height(nodes, links):
    geo = nodes.new("ShaderNodeNewGeometry")
    n = nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 3.0
    n.inputs["Detail"].default_value = 2.0
    n.inputs["Distortion"].default_value = 0.0
    links.new(geo.outputs["Position"], n.inputs["Vector"])
    return n.outputs["Fac"]


material(bumped(toast_height))
a = render()
material(bumped(nodes_height))
b = render()
report("bump", max_diff=diff(a, b), spread=max(p[0] for p in a) - min(p[0] for p in a), error="")

# An error keeps the material working (the node's outputs fall back to defaults).
material(lambda nodes, links: toast_node(nodes, 'output("c", nope(1))\n', "bad").outputs.get("c")
         or nodes.new("ShaderNodeRGB").outputs[0])  # fmt: skip
bad = next(n for n in plane.data.materials[0].node_tree.nodes if n.bl_idname == "ShaderNodeToast")
render()
report("error", error=bad.error)


# World shader: a Toast node in the world, seen where the plane isn't.
plane.hide_render = True
wt = world.node_tree
for n in list(wt.nodes):
    wt.nodes.remove(n)
wnode = toast_node(wt.nodes, 'output("c", vec3(0.5, 0.25, param("b", 0.125)))\n', "world")
bg = wt.nodes.new("ShaderNodeBackground")
wout = wt.nodes.new("ShaderNodeOutputWorld")
wt.links.new(wnode.outputs["c"], bg.inputs["Color"])
wt.links.new(bg.outputs[0], wout.inputs["Surface"])
px = render()
report("world", max_diff=diff(px, [(0.5, 0.25, 0.125, 1.0)] * len(px)), error=wnode.error)

print("TOASTSHADER done", flush=True)
