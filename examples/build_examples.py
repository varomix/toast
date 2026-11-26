# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Build the example .blend files from the Toast code in examples/src.

Run with the Toast fork of Blender:
  blender -b --factory-startup --python examples/build_examples.py [-- name ...]

Each example is one scene: an object whose Geometry Nodes modifier holds the Toast nodes, a
camera, lights, and materials that show the attributes the code writes. The code lives in the
.blend as texts (and in examples/src for reading on GitHub). Simulations are not baked: press
Play in Blender.
"""

import math
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
sys.path.insert(0, str(HERE.parent))

import toast  # noqa: E402
from toast import blender_addon  # noqa: E402

RUN_OVER = {"points": "POINTS", "faces": "FACES", "edges": "EDGES", "corners": "CORNERS",
            "curves": "CURVES", "instances": "INSTANCES", "geometry": "GEOMETRY"}  # fmt: skip


# --- Scene helpers ---------------------------------------------------------------------------


def new_file(frames, fps=24):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    toast.register()
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = frames
    scene.render.fps = fps
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.view_settings.view_transform = "AgX"
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.02, 0.022, 0.03, 1)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world
    return scene


def camera(location, look_at, lens=50):
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    cam.data.lens = lens
    cam.location = location
    direction = (look_at[0] - location[0], look_at[1] - location[1], look_at[2] - location[2])
    from mathutils import Vector

    cam.rotation_euler = Vector(direction).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def light(kind, location, energy, rotation=(0, 0, 0), size=1.0, color=(1, 1, 1)):
    data = bpy.data.lights.new(kind.title(), kind)
    data.energy = energy
    data.color = color
    if kind == "AREA":
        data.size = size
    if kind == "SUN":
        data.angle = math.radians(size)
    obj = bpy.data.objects.new(data.name, data)
    obj.location = location
    obj.rotation_euler = [math.radians(a) for a in rotation]
    bpy.context.scene.collection.objects.link(obj)
    return obj


def material(name, attribute=None, attr_type="GEOMETRY", color=(0.8, 0.8, 0.8), roughness=0.5,
             emission=0.0, ramp=None, metallic=0.0):  # fmt: skip
    """Principled material; with `attribute`, its base color comes from that attribute (through a
    color ramp if `ramp` = [(position, rgb)...])."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    if attribute:
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_name = attribute
        attr.attribute_type = attr_type
        attr.location = (-600, 200)
        out = attr.outputs["Color"]
        if ramp:
            cr = nt.nodes.new("ShaderNodeValToRGB")
            cr.location = (-350, 200)
            nt.links.new(attr.outputs["Fac"], cr.inputs["Fac"])
            els = cr.color_ramp.elements
            els[0].position, els[0].color = ramp[0][0], (*ramp[0][1], 1)
            els[1].position, els[1].color = ramp[-1][0], (*ramp[-1][1], 1)
            for pos, rgb in ramp[1:-1]:
                e = els.new(pos)
                e.color = (*rgb, 1)
            out = cr.outputs["Color"]
        nt.links.new(out, bsdf.inputs["Base Color"])
        if emission:
            nt.links.new(out, bsdf.inputs["Emission Color"])
            bsdf.inputs["Emission Strength"].default_value = emission
    return mat


def mesh_object(name, mesh=None):
    obj = bpy.data.objects.new(name, mesh or bpy.data.meshes.new(name))
    bpy.context.scene.collection.objects.link(obj)
    return obj


# --- Node helpers ----------------------------------------------------------------------------


class Tree:
    """A Geometry Nodes tree being built left to right."""

    def __init__(self, obj, name):
        self.tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
        self.tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        self.tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        self.nodes, self.links = self.tree.nodes, self.tree.links
        self.input = self.nodes.new("NodeGroupInput")
        self.output = self.nodes.new("NodeGroupOutput")
        self.input.location = (-400, 0)
        mod = obj.modifiers.new("Toast example", "NODES")
        mod.node_group = self.tree

    def node(self, idname, loc, label=None, **inputs):
        n = self.nodes.new(idname)
        n.location = loc
        if label:
            n.label = label
        for key, value in inputs.items():
            n.inputs[key.replace("_", " ")].default_value = value
        return n

    def link(self, a, b):
        self.links.new(a, b)

    def toast(self, src, loc, run_over=None, label=None, params=None):
        """A Toast node running examples/src/<src>.py. Run Over comes from the code's header."""
        path = SRC / f"{src}.py"
        code = path.read_text()
        if run_over is None:
            run_over = "points"
            for key in RUN_OVER:
                if f"Run Over: {key.title()}" in code.split("\n", 1)[0]:
                    run_over = key
        text = bpy.data.texts.get(path.name) or bpy.data.texts.new(path.name)
        text.clear()
        text.write(code)
        text.cursor_set(0)
        n = self.nodes.new("GeometryNodeToast")
        n.location = loc
        n.label = label or path.stem.replace("_", " ").title()
        n.width = 200
        n.run_over = RUN_OVER[run_over]
        n.text = text
        blender_addon.update_node(n, force=True)
        if n.error:
            raise RuntimeError(f"{src}: {n.error}")
        for key, value in (params or {}).items():
            n.inputs[key].default_value = value
        return n

    def sim_zone(self, x_in, x_out, y=0):
        sin = self.node("GeometryNodeSimulationInput", (x_in, y))
        sout = self.node("GeometryNodeSimulationOutput", (x_out, y))
        sin.pair_with_output(sout)
        return sin, sout

    def repeat_zone(self, x_in, x_out, iterations, y=0):
        rin = self.node("GeometryNodeRepeatInput", (x_in, y))
        rout = self.node("GeometryNodeRepeatOutput", (x_out, y))
        rin.pair_with_output(rout)
        rin.inputs["Iterations"].default_value = iterations
        return rin, rout

    def finish(self, socket, x):
        self.output.location = (x, 0)
        self.link(socket, self.output.inputs[0])


def library(name):
    """A text toast_lib.<name> from examples/src/<dir>/lib_<name>.py."""
    path = next(SRC.glob(f"*/lib_{name}.py"))
    text = bpy.data.texts.new(f"toast_lib.{name}")
    text.write(path.read_text())
    return text


def note(lines):
    """A text named README shown first, explaining the example."""
    text = bpy.data.texts.new("README")
    text.write("\n".join(lines) + "\n")
    return text


def show_text_in_ui(text):
    # Background mode has no screens to set up; the text opens from the Text Editor's list.
    pass


def save(name):
    path = HERE / f"{name}.blend"
    bpy.context.scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=True)
    print("SAVED", path)


# --- Examples --------------------------------------------------------------------------------


def flocking():
    scene = new_file(400)
    obj = mesh_object("Flock")
    t = Tree(obj, "Flocking")
    pts = t.node("GeometryNodePoints", (-200, 0), Count=3000)
    seed = t.toast("flocking/seed", (0, 0))
    t.link(pts.outputs[0], seed.inputs["Geometry"])
    sin, sout = t.sim_zone(300, 800)
    flock = t.toast("flocking/flock", (500, 0))
    t.link(seed.outputs[0], sin.inputs["Geometry"])
    t.link(sin.outputs["Geometry"], flock.inputs["Geometry"])
    t.link(sin.outputs["Delta Time"], flock.inputs["delta_time"])
    t.link(flock.outputs[0], sout.inputs["Geometry"])
    cone = t.node("GeometryNodeMeshCone", (800, -300), Vertices=6, Radius_Bottom=0.35, Depth=1.6)
    setmat = t.node("GeometryNodeSetMaterial", (1000, -300))
    setmat.inputs["Material"].default_value = material(
        "Boid", attribute="fast", attr_type="INSTANCER", roughness=0.35,
        ramp=[(0.0, (0.05, 0.25, 0.8)), (0.5, (0.85, 0.85, 0.9)), (1.0, (1.0, 0.35, 0.05))])
    t.link(cone.outputs["Mesh"], setmat.inputs["Geometry"])
    iop = t.node("GeometryNodeInstanceOnPoints", (1000, 0))
    t.link(sout.outputs["Geometry"], iop.inputs["Points"])
    t.link(setmat.outputs[0], iop.inputs["Instance"])
    orient = t.toast("flocking/orient", (1200, 0))
    t.link(iop.outputs[0], orient.inputs["Geometry"])
    t.finish(orient.outputs[0], 1500)
    obj.data.materials.append(setmat.inputs["Material"].default_value)

    camera((0, -19, 3), (0, 0, 0), lens=40)
    light("SUN", (0, 0, 10), 3.0, rotation=(40, 10, 30), size=3)
    light("AREA", (-6, -4, 6), 600, rotation=(50, 0, -50), size=6, color=(0.6, 0.75, 1.0))
    note([
        "Flocking: 3000 boids, Toast in a Simulation Zone. Press Play.",
        "",
        "seed.py    (Points)     random start positions and velocities",
        "flock.py   (Points)     boids: separation, alignment, cohesion with nearby_points()",
        "orient.py  (Instances)  turns each cone where its boid flies (@transform), and",
        "                        stores how fast it goes (@fast) for the material",
        "",
        "Try: more boids (Points > Count, 20000+), view_radius, the three weights.",
    ])
    save("01_flocking")


def reaction_diffusion():
    new_file(500)
    obj = mesh_object("Coral")
    t = Tree(obj, "Reaction diffusion")
    ico = t.node("GeometryNodeMeshIcoSphere", (-200, 0), Radius=1.0, Subdivisions=7)
    seed = t.toast("reaction_diffusion/seed", (0, 0))
    t.link(ico.outputs["Mesh"], seed.inputs["Geometry"])
    sin, sout = t.sim_zone(250, 1050)
    rin, rout = t.repeat_zone(450, 850, 24)
    rin.label = "Steps per frame"
    step = t.toast("reaction_diffusion/step", (620, 0))
    t.link(seed.outputs[0], sin.inputs["Geometry"])
    t.link(sin.outputs["Geometry"], rin.inputs["Geometry"])
    t.link(rin.outputs["Geometry"], step.inputs["Geometry"])
    t.link(step.outputs[0], rout.inputs["Geometry"])
    t.link(rout.outputs["Geometry"], sout.inputs["Geometry"])
    smooth = t.node("GeometryNodeSetShadeSmooth", (1250, 0))
    t.link(sout.outputs["Geometry"], smooth.inputs["Mesh"])
    shade = t.toast("reaction_diffusion/shade", (1450, 0))
    t.link(smooth.outputs[0], shade.inputs["Geometry"])
    setmat = t.node("GeometryNodeSetMaterial", (1700, 0))
    setmat.inputs["Material"].default_value = material("Reaction", attribute="Color", roughness=0.4)
    t.link(shade.outputs[0], setmat.inputs["Geometry"])
    t.finish(setmat.outputs[0], 1900)

    camera((0, -5.0, 1.4), (0, 0, 0), lens=50)
    light("SUN", (0, 0, 10), 4.0, rotation=(50, 0, 40), size=2)
    light("AREA", (-3, -2, 2), 300, rotation=(60, 0, -60), size=4, color=(0.5, 0.7, 1.0))
    note([
        "Reaction-diffusion: Gray-Scott on a 40962-point sphere. Press Play.",
        "Patterns take a few hundred frames to grow.",
        "",
        "seed.py   (Points)  chemical A everywhere, drops of B",
        "step.py   (Points)  one diffusion + reaction step with point_neighbors();",
        "                    a Repeat Zone runs it 24 times per frame",
        "shade.py  (Points)  raises the surface and colors it where B is",
        "",
        "Feed and kill change from bottom to top: spots, worms and mazes on one sphere.",
        "Try: Ico Sphere subdivisions 8 (163842 points), the feed/kill params.",
    ])
    save("02_reaction_diffusion")


def hair():
    new_file(240)
    # The ball that sweeps through the hair (Input 1 of the simulation).
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.55, location=(-3.2, -0.2, 1.1), segments=48, ring_count=24)
    ball = bpy.context.active_object
    ball.name = "Ball"
    bpy.ops.object.shade_smooth()
    ball.data.materials.append(material("Ball", color=(0.9, 0.25, 0.1), roughness=0.3))
    for frame, x in ((1, -3.2), (70, 3.2), (140, -3.2), (210, 3.2)):
        ball.location.x = x
        ball.keyframe_insert("location", index=0, frame=frame)

    bpy.ops.mesh.primitive_ico_sphere_add(radius=1.0, subdivisions=4)
    head = bpy.context.active_object
    head.name = "Head"
    bpy.ops.object.shade_smooth()
    head.data.materials.append(material("Skin", color=(0.25, 0.2, 0.35), roughness=0.6))

    # Hair is a Curves object: Blender renders curves from those (not from mesh objects).
    obj = bpy.data.objects.new("Hair", bpy.data.hair_curves.new("Hair"))
    bpy.context.scene.collection.objects.link(obj)
    t = Tree(obj, "Hair")
    head_info = t.node("GeometryNodeObjectInfo", (-600, 0))
    head_info.inputs["Object"].default_value = head
    head_info.transform_space = "RELATIVE"
    scalp = t.toast("hair/scalp", (-400, -200))
    t.link(head_info.outputs["Geometry"], scalp.inputs["Geometry"])
    dist = t.node("GeometryNodeDistributePointsOnFaces", (-150, 0), Density=600.0)
    t.link(scalp.outputs[0], dist.inputs["Mesh"])  # The output field lives on this geometry.
    t.link(scalp.outputs["scalp"], dist.inputs["Selection"])
    line = t.node("GeometryNodeCurvePrimitiveLine", (-150, -350), End=(0, 0, 1.3))
    resample = t.node("GeometryNodeResampleCurve", (50, -350), Count=24)
    t.link(line.outputs[0], resample.inputs["Curve"])
    iop = t.node("GeometryNodeInstanceOnPoints", (250, 0))
    t.link(dist.outputs["Points"], iop.inputs["Points"])
    t.link(resample.outputs[0], iop.inputs["Instance"])
    t.link(dist.outputs["Rotation"], iop.inputs["Rotation"])
    realize = t.node("GeometryNodeRealizeInstances", (450, 0))
    t.link(iop.outputs[0], realize.inputs["Geometry"])
    rest = t.toast("hair/rest", (650, 0))
    t.link(realize.outputs[0], rest.inputs["Geometry"])
    info = t.node("GeometryNodeObjectInfo", (650, -300))
    info.inputs["Object"].default_value = ball
    info.transform_space = "RELATIVE"
    sin, sout = t.sim_zone(900, 1400)
    sim = t.toast("hair/simulate", (1100, 0))
    t.link(rest.outputs[0], sin.inputs["Geometry"])
    t.link(sin.outputs["Geometry"], sim.inputs["Geometry"])
    t.link(info.outputs["Geometry"], sim.inputs["Input 1"])
    t.link(sin.outputs["Delta Time"], sim.inputs["delta_time"])
    t.link(sim.outputs[0], sout.inputs["Geometry"])
    radius = t.node("GeometryNodeSetCurveRadius", (1600, 0), Radius=0.006)
    t.link(sout.outputs["Geometry"], radius.inputs["Curve"])
    hair_mat = t.node("GeometryNodeSetMaterial", (1800, 0))
    hair_mat.inputs["Material"].default_value = material("Hair", color=(0.95, 0.75, 0.35), roughness=0.35)
    t.link(radius.outputs[0], hair_mat.inputs["Geometry"])
    t.finish(hair_mat.outputs[0], 2000)
    obj.data.materials.append(hair_mat.inputs["Material"].default_value)

    camera((0, -7.5, 2.0), (0, 0, 0.6), lens=45)
    light("SUN", (0, 0, 10), 3.5, rotation=(45, 0, 30), size=3)
    light("AREA", (3, -3, 3), 400, rotation=(50, 0, 45), size=4, color=(0.7, 0.8, 1.0))
    note([
        "Hair: ~4000 strands of 24 points, simulated per strand. Press Play.",
        "",
        "scalp.py     (Faces)   output(): which faces grow hair (a Selection for Distribute)",
        "rest.py      (Points)  stores the groomed shape",
        "simulate.py  (Curves)  per strand: copy points into lists, Verlet, wind (curl_noise),",
        "                       keep segment lengths (follow the leader), collide with the",
        "                       head and with the Ball object (closest_point on Input 1)",
        "",
        "The Hair object (Curves) grows from the Head object. Move or animate the Ball:",
        "the hair reacts. Sculpt the Head: the hair follows (it reads the Head's mesh).",
    ])
    save("03_hair")


def growth_object(name, x, parallel, ribbon):
    """One growing loop at `x`: grow.py alone (one core), or move.py + rebuild.py (all cores)."""
    obj = mesh_object(name)
    obj.location.x = x
    t = Tree(obj, name)
    circle = t.node("GeometryNodeMeshCircle", (-200, 0), Vertices=60, Radius=0.25)
    sin, sout = t.sim_zone(0, 1000)
    rin, rout = t.repeat_zone(200, 800, 4)
    rin.label = "Steps per frame"
    t.link(circle.outputs[0], sin.inputs["Geometry"])
    t.link(sin.outputs["Geometry"], rin.inputs["Geometry"])
    if parallel:
        move = t.toast("growth/move", (380, 0))
        rebuild = t.toast("growth/rebuild", (600, 0))
        # One split length for both nodes.
        split = t.node("ShaderNodeValue", (380, -300), label="Split Length")
        split.outputs[0].default_value = 0.035
        t.link(split.outputs[0], move.inputs["split_length"])
        t.link(split.outputs[0], rebuild.inputs["split_length"])
        t.link(rin.outputs["Geometry"], move.inputs["Geometry"])
        t.link(move.outputs[0], rebuild.inputs["Geometry"])
        last = rebuild
    else:
        last = t.toast("growth/grow", (380, 0))
        t.link(rin.outputs["Geometry"], last.inputs["Geometry"])
    t.link(last.outputs[0], rout.inputs["Geometry"])
    t.link(rout.outputs["Geometry"], sout.inputs["Geometry"])
    shade = t.toast("growth/shade", (1200, 0))
    t.link(sout.outputs["Geometry"], shade.inputs["Geometry"])
    to_curve = t.node("GeometryNodeMeshToCurve", (1450, 0))
    t.link(shade.outputs[0], to_curve.inputs["Mesh"])
    # Normals pointing up, and a profile along the normal: an upright ribbon that doesn't twist.
    normal = t.node("GeometryNodeSetCurveNormal", (1650, 0), Mode="Z Up")
    t.link(to_curve.outputs[0], normal.inputs["Curve"])
    profile = t.node("GeometryNodeCurvePrimitiveLine", (1650, -250), End=(0.12, 0, 0))
    to_mesh = t.node("GeometryNodeCurveToMesh", (1850, 0))
    t.link(normal.outputs[0], to_mesh.inputs["Curve"])
    t.link(profile.outputs[0], to_mesh.inputs["Profile Curve"])
    setmat = t.node("GeometryNodeSetMaterial", (2050, 0))
    setmat.inputs["Material"].default_value = ribbon
    t.link(to_mesh.outputs[0], setmat.inputs["Geometry"])
    t.finish(setmat.outputs[0], 2250)
    return obj


def growth():
    new_file(600)
    ribbon = material("Ribbon", attribute="Color", roughness=0.45)
    growth_object("Growth (one core)", -3.6, False, ribbon)
    growth_object("Growth (all cores)", 3.6, True, ribbon)

    # A floor to cast shadows on.
    bpy.ops.mesh.primitive_plane_add(size=30)
    bpy.context.active_object.data.materials.append(material("Floor", color=(0.05, 0.05, 0.06), roughness=0.8))
    camera((0, -9.5, 11), (0, 0, 0), lens=35)
    light("SUN", (0, 0, 10), 4.0, rotation=(35, 0, 30), size=2)
    note([
        "Differential growth: a closed line that buckles as it grows. Press Play.",
        "Two objects grow the same shape, written two ways:",
        "",
        "Growth (one core), left:",
        "  grow.py     (Geometry)  once per step, on one core: moves every point (attraction to",
        "                          its neighbors, repulsion from nearby_points()), splits long",
        "                          edges, and rebuilds the loop with add_point/add_edge/remove_point",
        "",
        "Growth (all cores), right: the same work split in two nodes",
        "  move.py     (Points)    the expensive part, each point's neighbors, once per point on",
        "                          every core; stores where the point goes (@next)",
        "  rebuild.py  (Geometry)  the sequential part, cheap: one walk along the loop to split",
        "                          long edges and reconnect it",
        "",
        "shade.py      (Points)    a color along the loop",
        "",
        "Compare them: node editor > Overlays > Timings shows each node's time, or hide one",
        "object and play. Run Over Geometry runs once, so it can't use more than one core: keep",
        "only the part that must be sequential in it.",
        "",
        "They stop splitting at max_points (12000). Raise it on both to see the gap grow.",
    ])
    save("04_differential_growth")


def fluid():
    new_file(300)
    bpy.ops.mesh.primitive_monkey_add(size=0.8, location=(0.45, 0, 0.4))
    monkey = bpy.context.active_object
    monkey.name = "Obstacle"
    bpy.ops.object.shade_smooth()
    monkey.data.materials.append(material("Obstacle", color=(0.85, 0.5, 0.15), roughness=0.35))
    # The tank, as a wireframe.
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 1.5), scale=(1.2, 0.45, 1.5))
    tank = bpy.context.active_object
    tank.name = "Tank"
    tank.modifiers.new("Wire", "WIREFRAME").thickness = 0.015
    tank.data.materials.append(material("Tank", color=(0.6, 0.6, 0.65), roughness=0.3, metallic=1.0))

    obj = mesh_object("Fluid")
    t = Tree(obj, "Fluid")
    pts = t.node("GeometryNodePoints", (-200, 0), Count=18 * 18 * 36)
    seed = t.toast("fluid/seed", (0, 0))
    t.link(pts.outputs[0], seed.inputs["Geometry"])
    info = t.node("GeometryNodeObjectInfo", (300, -350))
    info.inputs["Object"].default_value = monkey
    info.transform_space = "RELATIVE"
    sin, sout = t.sim_zone(250, 1500)
    rin, rout = t.repeat_zone(450, 1300, 6)
    rin.label = "Substeps"
    predict = t.toast("fluid/predict", (650, 0))
    density = t.toast("fluid/density", (870, 0))
    relax = t.toast("fluid/relax", (1090, 0))
    t.link(seed.outputs[0], sin.inputs["Geometry"])
    t.link(sin.outputs["Geometry"], rin.inputs["Geometry"])
    t.link(rin.outputs["Geometry"], predict.inputs["Geometry"])
    t.link(predict.outputs[0], density.inputs["Geometry"])
    t.link(density.outputs[0], relax.inputs["Geometry"])
    t.link(info.outputs["Geometry"], relax.inputs["Input 1"])
    t.link(relax.outputs[0], rout.inputs["Geometry"])
    t.link(rout.outputs["Geometry"], sout.inputs["Geometry"])
    shade = t.toast("fluid/shade", (1700, 0))
    t.link(sout.outputs["Geometry"], shade.inputs["Geometry"])
    radius = t.node("GeometryNodeSetPointRadius", (1900, 0), Radius=0.03)
    t.link(shade.outputs[0], radius.inputs["Points"])
    setmat = t.node("GeometryNodeSetMaterial", (2100, 0))
    setmat.inputs["Material"].default_value = material("Water", attribute="Color", roughness=0.15)
    t.link(radius.outputs[0], setmat.inputs["Geometry"])
    t.finish(setmat.outputs[0], 2300)

    camera((0, -5.6, 2.2), (0, 0, 0.75), lens=40)
    light("SUN", (0, 0, 10), 3.5, rotation=(40, 0, 25), size=3)
    light("AREA", (-3, -3, 4), 400, rotation=(45, 0, -45), size=5, color=(0.7, 0.85, 1.0))
    note([
        "Fluid: 11664 particles, position-based (double density relaxation). Press Play.",
        "",
        "seed.py     (Points)  a block of particles",
        "In the Simulation Zone, 6 substeps (Repeat Zone) of three chained Toast nodes:",
        "predict.py  (Points)  gravity, move ahead",
        "density.py  (Points)  crowding and pressure from nearby_points()",
        "relax.py    (Points)  push apart, collide with the Obstacle (Input 1) and the tank",
        "shade.py    (Points)  color by speed",
        "",
        "Try: Points > Count 50000+ (the column gets taller) to find your machine's limit.",
    ])
    save("05_fluid")


def mandelbulb():
    new_file(240)
    scene = bpy.context.scene
    scene.render.resolution_x = 900
    scene.render.resolution_y = 900
    obj = mesh_object("Mandelbulb")
    t = Tree(obj, "Mandelbulb")
    library("fractal")
    grid = t.node("GeometryNodeMeshGrid", (-400, 0), Size_X=3.2, Size_Y=3.2, Vertices_X=400, Vertices_Y=400)
    to_pts = t.node("GeometryNodeMeshToPoints", (-200, 0))
    t.link(grid.outputs["Mesh"], to_pts.inputs["Mesh"])
    march = t.toast("mandelbulb/march", (0, 0), params={"pixel": 3.2 / 400})
    t.link(to_pts.outputs[0], march.inputs["Geometry"])
    setmat = t.node("GeometryNodeSetMaterial", (300, 0))
    setmat.inputs["Material"].default_value = material("Bulb", attribute="Color", emission=1.0,
                                                       color=(0, 0, 0), roughness=1.0)  # fmt: skip
    t.link(march.outputs[0], setmat.inputs["Geometry"])
    t.finish(setmat.outputs[0], 500)
    # The camera sits at the code's eye and sees the grid edge to edge.
    cam = camera((0, -3.2, 0), (0, 0, 0))
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.angle = 2 * math.atan(1.6 / 2.6)  # the code's grid half-size / focal
    note([
        "Mandelbulb: 160000 points, each one ray-marches a fractal. It animates (the power",
        "wobbles with time), so every frame recomputes everything.",
        "",
        "march.py (Points)  per point: up to 96 distance estimates of up to 8 fractal",
        "                   iterations, 6 more for the normal; misses are removed",
        "toast_lib.fractal  the distance estimate, as a library",
        "",
        "Look through the camera (Numpad 0). Try: Grid vertices 800 x 800 (640000 points),",
        "iterations 12, max_steps 200.",
    ])
    save("06_mandelbulb")


def tree():
    new_file(200)
    obj = mesh_object("Tree")
    t = Tree(obj, "Tree")
    library("tree")
    grow = t.toast("tree/tree", (0, 0))
    t.link(t.input.outputs[0], grow.inputs["Geometry"])
    to_curve = t.node("GeometryNodeMeshToCurve", (250, 0))
    t.link(grow.outputs[0], to_curve.inputs["Mesh"])
    radius_attr = t.node("GeometryNodeInputNamedAttribute", (250, -250))
    radius_attr.data_type = "FLOAT"
    radius_attr.inputs["Name"].default_value = "radius"
    profile = t.node("GeometryNodeCurvePrimitiveCircle", (250, -400), Resolution=8, Radius=1.0)
    to_mesh = t.node("GeometryNodeCurveToMesh", (500, 0), Fill_Caps=True)
    t.link(to_curve.outputs[0], to_mesh.inputs["Curve"])
    t.link(profile.outputs[0], to_mesh.inputs["Profile Curve"])
    t.link(radius_attr.outputs["Attribute"], to_mesh.inputs["Scale"])
    bark = t.node("GeometryNodeSetMaterial", (700, 0))
    bark.inputs["Material"].default_value = material("Bark", color=(0.25, 0.16, 0.1), roughness=0.8)
    t.link(to_mesh.outputs[0], bark.inputs["Geometry"])
    smooth = t.node("GeometryNodeSetShadeSmooth", (900, 0))
    t.link(bark.outputs[0], smooth.inputs["Mesh"])

    leaf_attr = t.node("GeometryNodeInputNamedAttribute", (250, -650))
    leaf_attr.data_type = "BOOLEAN"
    leaf_attr.inputs["Name"].default_value = "leaf"
    leaf_mesh = t.node("GeometryNodeMeshGrid", (250, -850), Size_X=1.0, Size_Y=0.6)
    leaf_mat = t.node("GeometryNodeSetMaterial", (450, -850))
    leaf_mat.inputs["Material"].default_value = material("Leaf", color=(0.25, 0.6, 0.12), roughness=0.5)
    t.link(leaf_mesh.outputs["Mesh"], leaf_mat.inputs["Geometry"])
    iop = t.node("GeometryNodeInstanceOnPoints", (500, -600))
    t.link(grow.outputs[0], iop.inputs["Points"])
    t.link(leaf_attr.outputs["Attribute"], iop.inputs["Selection"])
    t.link(leaf_mat.outputs[0], iop.inputs["Instance"])
    leaves = t.toast("tree/leaves", (700, -600))
    t.link(iop.outputs[0], leaves.inputs["Geometry"])
    join = t.node("GeometryNodeJoinGeometry", (1100, 0))
    t.link(smooth.outputs[0], join.inputs[0])
    t.link(leaves.outputs[0], join.inputs[0])
    t.finish(join.outputs[0], 1300)
    for m in (bark, leaf_mat):
        obj.data.materials.append(m.inputs["Material"].default_value)

    bpy.ops.mesh.primitive_plane_add(size=30)
    bpy.context.active_object.data.materials.append(material("Ground", color=(0.12, 0.1, 0.08), roughness=0.9))
    camera((0, -13, 3.2), (0, 0, 2.8), lens=35)
    light("SUN", (0, 0, 10), 4.0, rotation=(40, 0, 35), size=2)
    light("AREA", (-4, -4, 5), 500, rotation=(45, 0, -45), size=6, color=(0.7, 0.85, 1.0))
    note([
        "Tree: a whole tree grown by one Toast node (Run Over Geometry). Scrub the timeline:",
        "it grows one level of branches every 20 frames.",
        "",
        "tree.py          a stack in lists (positions, rotations, lengths...) walks the",
        "                 branches; add_point/add_edge build them, set_point_attr() gives",
        "                 each new point its radius",
        "toast_lib.tree   helpers: child rotation (golden angle), reaching for the light",
        "leaves.py        (Instances) random turn and size for each leaf",
        "",
        "Try: depth 8 or 9, children 4, spread, seed.",
    ])
    save("07_tree")


EXAMPLES = {
    "flocking": flocking,
    "reaction_diffusion": reaction_diffusion,
    "hair": hair,
    "growth": growth,
    "fluid": fluid,
    "mandelbulb": mandelbulb,
    "tree": tree,
}

if __name__ == "__main__":
    names = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else list(EXAMPLES)
    for name in names:
        EXAMPLES[name]()
