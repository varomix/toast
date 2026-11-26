# Toast roadmap

What's next for Toast: limits to lift, and example scenes to make. Nothing here is promised or
scheduled. For what works today, see the [guide](guide.md) and the [examples](../examples).

## Limits to lift

These are the ones that block whole kinds of work. Curves, volumes, Grease Pencil and
particles come first: Blender users need all four.

### Curves: new points and new curves

**Today:** Run Over Points and Curves read and move curve points, and `remove_point` /
`remove_curve` delete them. Nothing can add a point to a curve or make a new curve, so strands are
made with Blender nodes first (the hair example) and growing curves are impossible: strokes, vines,
trails, strange attractors, lightning, field lines.

**Plan:**
- `add_curve((a, b, c, ...))` in Run Over Geometry and Curves: a new curve through points made with
  `add_point()` (handles or point numbers, as `add_face` takes), plus `add_curve_point(curve,
  position)` to extend a curve at its tip. Curve type poly first; `set_curve_attr()` for
  `cyclic`, `resolution` and the user's own curve attributes.
- Inserting a point into a curve where it is (`insert_curve_point(curve, after, position)`), so a
  growing line stays one curve without rebuilding it. The same idea for mesh edges is in
  "Run Over Geometry in parallel" below.
- ABI: new commands in `ToastHost` (`cmd_add_curve`, `cmd_add_curve_point`); the node rebuilds
  the curve offsets once after the run, in element order, as it does for meshes. The harness must
  match it.
- Example to prove it: a growing vine, or particles that leave curve trails.

### Volumes

**Today:** volumes pass through untouched; there is no way to read or write a grid.

**Plan:**
- Reading: `sample_grid(input, "density", position)` (trilinear) and `grid_gradient(...)` on
  Input 0 or 1, so points can follow smoke, stick to an SDF or be colored by a density.
- Writing: Run Over Voxels, the code runs once per active voxel of a float or vector grid
  (`@density`, `@velocity`, `@position` = voxel center). Blender's volume grids are OpenVDB; the
  node would visit leaf nodes in parallel with the same fixed chunking, so results stay the same
  at any thread count.
- Making grids: a way to fill a dense box (`Run Over Voxels` on a grid made by a Blender node,
  e.g. Volume Cube or Points to SDF Grid) before Toast writes into it.
- Example to prove it: smoke advected by Toast (semi-Lagrangian), or a level set that grows.

### Grease Pencil

**Today:** Grease Pencil is ignored; Blender stores its strokes as curves (one curves geometry per
layer and frame), so most of the machinery exists.

**Plan:**
- Run Over Points and Curves visit every layer's drawing on the current frame, as Blender's own
  nodes do, with Grease Pencil attributes by their Blender names (`@radius`, `@opacity`,
  `@vertex_color`, `@fill_color`...), and `@layer` read-only.
- Topology from the curves work above applies to strokes too: new strokes from code, trimming,
  extending.
- Example to prove it: hand-drawn strokes that wiggle, boil or grow hair-like fringes.

### Particles and long trails

**Today:** particles are point clouds in a Simulation Zone, which works (flocking, fluid). The
limits are around them: a list holds at most 4096 values, `nearby_points()` visits at most 4096
points, lists can't grow and can't be stored on an element, and there are no trails.

**Plan:**
- Larger lists, allocated per element instead of on the stack, with a compile-time cap the
  user can raise; `append()` on lists declared with a maximum (`trail: list[vec3, 256]`).
- List attributes: store a fixed-size list per point (history of positions, a per-particle
  neighbor cache), read back the next frame.
- Trails as curves, once curves can grow (above).
- Emission helpers for Run Over Geometry (`emit(count)` with an age and an id), and `@age` /
  `@life` conventions with automatic removal.
- Example to prove it: fireworks with trails, or a particle system that emits from a mesh.

### Run Over Geometry in parallel

**Today:** Run Over Geometry runs once, on one core. The differential growth example splits
work between a parallel node and a sequential one to get around it.

**Plan:** `for i in parallel_range(n):` in Run Over Geometry, iterations on all cores, commands
merged in loop order (deterministic); the compiler rejects variables carried from one iteration to
the next. Plus inserting a point into a mesh edge in place, so growth doesn't rebuild the mesh.

## Example scenes to make

Ideas for examples that show what the current ten don't, roughly easiest first. Each note says
what it would show off and what it needs that Toast doesn't have yet, if anything.

| Scene | Shows | Needs |
| --- | --- | --- |
| **Cloth draping** over Suzanne: a grid of springs with rest lengths | `point_neighbors`, collisions with `closest_point` on Input 1, substeps | Nothing new |
| **Game of Life on a sphere's faces** | Run Over Faces, neighbors through `face_points`/`point_faces`, Simulation Zone; same result at any thread count | Nothing new |
| **Procedural city**: each face of a subdivided plane becomes a building with window bands | Run Over Faces, `add_point`/`add_face` per face, `random(@index, seed)`, `voronoi` for districts | Nothing new |
| **Voronoi shatter**: pieces pushed apart over time | `voronoi(...).position` as piece centers, Run Over Faces, `output()` driving Split Edges and Translate | Nothing new |
| **Crowd on terrain**: 50000 instances walking a flow field, held to the ground | Run Over Instances, `quat`, `curl_noise`, `ray_cast` to the ground, Selection to freeze stuck ones | Nothing new |
| **Caustics**: light refracting through a wavy glass sheet onto a floor | Two `ray_cast` bounces per point, a refraction helper; landing points made denser with Points to Volume | Nothing new |
| **Hydraulic erosion**: droplets carving channels in an `fbm` terrain | Run Over Geometry droplets, or the move/rebuild split from the growth example | Faster with `parallel_range` |
| **Diffusion-limited aggregation** (lightning, frost) | `nearest_point` on a growing cloud, Run Over Geometry, `output()` into Curve to Mesh | Curves that grow, for strokes |
| **Ivy crawling over a statue** | Growth in Run Over Geometry, `closest_point` + `ray_cast` to stay on the surface, leaves as instances (`@transform`, `mat4`) | Curves that grow |
| **Strange attractors** drawn as long strands | Heavy math per step, long histories | Curves that grow, longer lists |
| **Smoke** advected through a grid | Volumes | Volumes |
| **Boiling Grease Pencil lines** | Strokes that wiggle and grow | Grease Pencil |
