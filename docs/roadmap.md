# Toast roadmap

What's next for Toast: limits to lift, and example scenes to make. Nothing here is promised or
scheduled. For what works today, see the [guide](guide.md) and the [examples](../examples).

## Limits to lift

These are the ones that block whole kinds of work. Curves, volumes, Grease Pencil and
particles come first: Blender users need all four.

### Curves: new points and new curves (done in 0.14)

`add_curve()` makes curves from points added in the run, and `extend_curve()` grows a curve at
its tip (kernel ABI 6). The trails example uses both. Still to do:

- Inserting a point inside a curve where it is (`insert_curve_point(curve, after, position)`),
  for curves that subdivide as they grow. The same idea for mesh edges is in "Run Over Geometry
  in parallel" below.
- Choosing the type of new curves (Bezier, NURBS) and writing curve attributes of new curves
  (`set_curve_attr()`); today new curves are poly with default curve attributes.

### Volumes (done in 0.17, 0.18)

Run Over Voxels runs once per active voxel, with grids as `@` attributes (float, int, bool,
vec3), `@voxel` and `@voxel_size`; `sample_grid()`, `grid_voxel()` and `grid_gradient()` read
grids from any mode; `activate_voxel()`/`deactivate_voxel()` change which voxels exist (kernel
ABI 9, 0.18). Volumes from VDB files work (tested with a file that has a tile). The smoke example
uses it all. Still to do:

- Neighbor reads without a call into the node: the voxels' point cloud could carry the index of
  each voxel's six neighbors, so `grid_voxel()` on the run's own grids reads an array.
- Activating voxels from other modes (points that leave smoke in a grid).

### Grease Pencil (done in 0.15)

Points, Curves and Geometry (when the code makes curves) run on every layer's strokes on the
current frame, and new strokes go into the layer. The sketch example uses it. Still to do:

- `@layer` (the layer's number) and layer names, so code can treat layers differently; today use
  the Selection or separate nodes.
- Reading Grease Pencil on Input 1, and Run Over Faces-like access to fills.

### Particles and long trails (mostly done in 0.16)

Lists hold up to 1048576 values (big ones on the heap), growable lists have `append()`, `pop()` and
`clear()`, query loops visit up to 1048576 points, `random_surface_point()` emits from a mesh
(kernel ABI 7), and trails are curves (`extend_curve`). The fountain and trails examples use
them. Still to do:

- List attributes: a fixed-size list stored per point (history, a neighbor cache), read back the
  next frame. Today, store a few values as separate attributes, or the history as a curve.
- `@age` / `@life` conventions with automatic removal (today: `remove_point()` in code).
- Faster `nearby_points()` for very large counts (the node keeps the nearest in a sorted
  array: fine up to thousands).

### Run Over Geometry in parallel

**Today:** Run Over Geometry runs once, on one core. The differential growth example splits
work between a parallel node and a sequential one to get around it.

**Plan:** `for i in parallel_range(n):` in Run Over Geometry, iterations on all cores, commands
merged in loop order (deterministic); the compiler rejects variables carried from one iteration to
the next. Plus inserting a point into a mesh edge in place, so growth doesn't rebuild the mesh.

## Example scenes to make

Ideas for examples that show what the current ones don't, roughly easiest first. Each note says
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
| **Diffusion-limited aggregation** (lightning, frost) | `nearest_point` on a growing cloud, Run Over Geometry, `add_curve` strokes | Nothing new |
| **Ivy crawling over a statue** | `extend_curve` growth, `closest_point` + `ray_cast` to stay on the surface, leaves as instances (`@transform`, `mat4`) | Nothing new |
| **Strange attractors** drawn as long strands | Heavy math per step, `extend_curve` histories | Nothing new |
| **Fire**: the smoke example with temperature, burning fuel and emission | A temperature grid, Blackbody in the material | Nothing new |
| **Level set** that grows or erodes a shape | Run Over Voxels on an SDF from Mesh to SDF Grid, `grid_gradient` | Nothing new |
