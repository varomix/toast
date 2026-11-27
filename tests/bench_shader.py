# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Benchmark: the shader editor's Toast node vs the same texture built from Blender's nodes.

Run all cases (each render in its own Blender process) and print a table:

  TOAST_BLENDER=/path/to/Blender python3 tests/bench_shader.py [cpu] [metal] [eevee]

One case, inside Blender:

  blender -b --factory-startup --enable-autoexec --python tests/bench_shader.py -- \
      ENGINE WORKLOAD VARIANT OUT.exr

A plane fills a 1920x1080 frame; its material emits the texture. Emission only, so shading the
texture is nearly all the work: the best case for a faster texture. Workloads:

  flat     no texture (the cost of everything else)
  flat_tk  flat, plus a Toast material out of view: the cost of Toast's kernels alone (Metal)
  const    a Toast node returning a constant: the cost of calling a Toast function
  light    one Noise Texture (fbm, detail 2)
  heavy    a domain warp (3 noises) into an fbm of detail 8, two Voronoi, mixed (12 nodes)

Times are the best of 5 renders after a warm-up, so compiling isn't counted. Toast and node
renders are compared pixel by pixel: the same values, so the same work. On Metal,
TOAST_BENCH_OPT sets Cycles' kernel optimization level (FULL, the default, or OFF) and
TOAST_BENCH_WARM adds warm-up renders (specialized kernels are built in the background).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

SAMPLES = {"cpu": 16, "metal": 256, "eevee": 1024}
WORKLOADS = ("flat", "flat_tk", "const", "light", "heavy")

TOAST = {
    "const": """# Run Over: Shader
output("c", vec3(0.5))
""",
    "light": """# Run Over: Shader
output("c", vec3(fbm(@generated * 4.0, 2.0)))
""",
    "heavy": """# Run Over: Shader
p = @generated * 4.0
w = vec3(noise(p), noise(p + 5.0), noise(p + 9.0))
q = p + w * 2.0
n = fbm(q, 8.0)
c1 = voronoi(q * 2.0)
c2 = voronoi(q * 5.0)
c = lerp(c1.color, c2.color, n)
output("c", c * c1.distance + vec3(n) * c2.distance)
""",
}


# --- One case, inside Blender ----------------------------------------------------------------


def run_case(engine, workload, variant, out):
    import addon_utils
    import bpy

    addon_utils.enable("toast", default_set=True)
    from toast import blender_addon as ba

    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "Standard"
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "32"
    opt = os.environ.get("TOAST_BENCH_OPT", "FULL")
    if engine == "eevee":
        sc.render.engine = "BLENDER_EEVEE"
        sc.eevee.taa_render_samples = SAMPLES[engine]
    else:
        sc.render.engine = "CYCLES"
        sc.cycles.samples = SAMPLES[engine]
        sc.cycles.use_adaptive_sampling = False
        sc.cycles.use_denoising = False
        sc.cycles.seed = 0
        sc.cycles.device = "CPU"
        if engine == "metal":
            prefs = bpy.context.preferences.addons["cycles"].preferences
            prefs.compute_device_type = "METAL"
            prefs.get_devices()
            prefs.kernel_optimization_level = opt
            for d in prefs.devices:
                d.use = d.type == "METAL"
            sc.cycles.device = "GPU"
    sc.world = bpy.data.worlds.new("w")
    bpy.ops.mesh.primitive_plane_add(size=2)
    plane = bpy.context.object
    plane.scale.x = 16 / 9
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 2.0
    cam.location = (0, 0, 5)
    sc.collection.objects.link(cam)
    sc.camera = cam

    mat = bpy.data.materials.new("m")
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    for n in list(nodes):
        nodes.remove(n)
    emit = nodes.new("ShaderNodeEmission")
    links.new(emit.outputs[0], nodes.new("ShaderNodeOutputMaterial").inputs["Surface"])
    plane.data.materials.append(mat)

    def toast_node(tree, code):
        node = tree.nodes.new("ShaderNodeToast")
        text = bpy.data.texts.new("bench.py")
        text.write(code)
        node.text = text
        ba.update_node(node, force=True)
        assert not node.error, node.error
        return node

    def vmath(op, a, b=None, scale=None):
        m = nodes.new("ShaderNodeVectorMath")
        m.operation = op
        for i, v in ((0, a), (1, b)):
            if isinstance(v, tuple):
                m.inputs[i].default_value = v
            elif v is not None:
                links.new(v, m.inputs[i])
        if isinstance(scale, float):
            m.inputs["Scale"].default_value = scale
        elif scale is not None:
            links.new(scale, m.inputs["Scale"])
        return m.outputs[0]

    def noise(vec, detail, scale=1.0):
        n = nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = scale
        n.inputs["Detail"].default_value = detail
        n.inputs["Distortion"].default_value = 0.0
        links.new(vec, n.inputs["Vector"])
        return n.outputs["Fac"]

    def voronoi(vec, scale):
        v = nodes.new("ShaderNodeTexVoronoi")
        v.inputs["Scale"].default_value = scale
        v.inputs["Randomness"].default_value = 1.0
        links.new(vec, v.inputs["Vector"])
        return v

    def combine(a, b, c):
        m = nodes.new("ShaderNodeCombineXYZ")
        for i, v in enumerate((a, b, c)):
            links.new(v, m.inputs[i])
        return m.outputs[0]

    if workload in ("flat", "flat_tk"):
        emit.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1)
        if workload == "flat_tk":
            other = bpy.data.materials.new("toast")
            node = toast_node(other.node_tree, TOAST["const"])
            other.node_tree.links.new(node.outputs["c"],
                                      other.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
            bpy.ops.mesh.primitive_plane_add(size=0.01, location=(0, 0, -50))
            bpy.context.object.data.materials.append(other)
    elif variant == "toast":
        links.new(toast_node(mat.node_tree, TOAST[workload]).outputs["c"], emit.inputs["Color"])
    elif workload == "light":
        tc = nodes.new("ShaderNodeTexCoord")
        links.new(noise(tc.outputs["Generated"], 2.0, scale=4.0), emit.inputs["Color"])
    elif workload == "heavy":
        tc = nodes.new("ShaderNodeTexCoord")
        p = vmath("SCALE", tc.outputs["Generated"], scale=4.0)
        w = combine(noise(p, 0.0), noise(vmath("ADD", p, (5.0, 5.0, 5.0)), 0.0),
                    noise(vmath("ADD", p, (9.0, 9.0, 9.0)), 0.0))  # fmt: skip
        q = vmath("ADD", p, vmath("SCALE", w, scale=2.0))
        n = noise(q, 8.0)
        c1, c2 = voronoi(q, 2.0), voronoi(q, 5.0)
        mix = nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        links.new(n, mix.inputs["Factor"])
        links.new(c1.outputs["Color"], mix.inputs[6])
        links.new(c2.outputs["Color"], mix.inputs[7])
        a = vmath("SCALE", mix.outputs[2], scale=c1.outputs["Distance"])
        b = vmath("SCALE", combine(n, n, n), scale=c2.outputs["Distance"])
        links.new(vmath("ADD", a, b), emit.inputs["Color"])
    else:
        raise SystemExit(f"no node tree for {workload}")

    sc.render.filepath = out

    def render():
        t = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        return time.perf_counter() - t

    render()
    for _ in range(int(os.environ.get("TOAST_BENCH_WARM", "0"))):
        render()
    times = [render() for _ in range(5)]
    print("BENCH " + json.dumps({"engine": engine, "workload": workload, "variant": variant,
                                 "best": round(min(times), 3),
                                 "times": [round(t, 3) for t in times]}), flush=True)  # fmt: skip


def compare(a, b):
    """Max difference and means of two renders, inside Blender."""
    import bpy
    import numpy as np

    def load(path):
        im = bpy.data.images.load(path)
        px = np.array(im.pixels[:], dtype=np.float32)
        bpy.data.images.remove(im)
        return px

    x, y = load(a), load(b)
    print("COMPARE " + json.dumps({"max_diff": float(np.abs(x - y).max()),
                                   "means": [float(x.mean()), float(y.mean())]}), flush=True)  # fmt: skip


# --- All cases, from a shell -----------------------------------------------------------------


def blender_line(blender, args, tag):
    proc = subprocess.run([blender, "-b", "--factory-startup", "--enable-autoexec", "--python",
                           __file__, "--", *args], capture_output=True, text=True)  # fmt: skip
    for line in proc.stdout.splitlines():
        if line.startswith(tag + " "):
            return json.loads(line[len(tag) + 1:])
    raise SystemExit(f"{args}: no result\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")


def main(engines):
    blender = os.environ.get("TOAST_BLENDER")
    if not blender:
        raise SystemExit("set TOAST_BLENDER to the Toast build of Blender")
    out = tempfile.mkdtemp(prefix="toast_bench_")
    print("| Engine | Flat | Toast kernels only | Constant Toast node | Light: Toast / nodes | "
          "Heavy: Toast / nodes | Heavy, texture alone: nodes / Toast |")  # fmt: skip
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for engine in engines:
        t = {}
        for workload in WORKLOADS:
            variants = ("toast", "nodes") if workload in ("light", "heavy") else ("toast",)
            for variant in variants:
                exr = os.path.join(out, f"{engine}_{workload}_{variant}.exr")
                t[workload, variant] = blender_line(blender, [engine, workload, variant, exr],
                                                    "BENCH")["best"]  # fmt: skip
            if len(variants) == 2:
                c = blender_line(blender, ["compare", os.path.join(out, f"{engine}_{workload}_toast.exr"),
                                           os.path.join(out, f"{engine}_{workload}_nodes.exr")], "COMPARE")  # fmt: skip
                print(f"  {engine} {workload}: max diff {c['max_diff']:.2g}, means "
                      f"{c['means'][0]:.6f} / {c['means'][1]:.6f}", file=sys.stderr)  # fmt: skip
        flat = t["flat", "toast"]
        speedup = (t["heavy", "nodes"] - flat) / max(t["heavy", "toast"] - flat, 1e-6)
        print(f"| {engine} ({SAMPLES[engine]} samples) | {flat:.2f} s | {t['flat_tk', 'toast']:.2f} s | "
              f"{t['const', 'toast']:.2f} s | {t['light', 'toast']:.2f} / {t['light', 'nodes']:.2f} s | "
              f"{t['heavy', 'toast']:.2f} / {t['heavy', 'nodes']:.2f} s | {speedup:.1f}x |", flush=True)  # fmt: skip


if __name__ == "__main__":
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]
        if args[0] == "compare":
            compare(args[1], args[2])
        else:
            run_case(*args)
    else:
        main(sys.argv[1:] or ["cpu", "eevee"] + (["metal"] if sys.platform == "darwin" else []))
