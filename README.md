<p align="center">
  <img src="images/toast_icon_256.png" alt="Toast" width="160">
</p>

<h1 align="center">Toast</h1>

<p align="center">
  Python-syntax kernels for Blender geometry nodes, compiled to native code.<br>
  <a href="docs/guide.md">User guide</a> · <a href="examples">Examples</a> · <a href="docs/building.md">Building</a> · <a href="docs/roadmap.md">Roadmap</a> ·
  <a href="https://github.com/varomix/blender/tree/toast">Blender fork</a>
</p>

## Toast frontend

Python goes in, native code pops out. **Using Toast: see [docs/guide.md](docs/guide.md)** (language, builtins, cookbook),
also as a page to open in a browser: `toast/guide.html`, which Blender opens from the Toast Guide buttons (rebuild it with `python3 docs/build_guide.py`
after editing the guide; a test checks it is up to date).
**Building Blender with Toast (Linux, macOS): see [docs/building.md](docs/building.md).**
This README is for developing Toast itself. This folder holds the Toast frontend (the future add-on)
and its runtime header. It has no Blender dependency; `harness.py` runs kernels on numpy arrays
the way the fork's `GeometryNodeToast` will. User guide: `docs/guide.md`.

```
toast/
  sugar.py          @ attributes -> _A.name on the token stream (line numbers kept)
  compiler.py       ast -> type inference -> C++ kernel + signature
  build.py          ~/.cache/toast/<key>.*: build() compiles a .so with g++/clang++ (harness,
                    External backend); build_source() writes self-contained C++ that the fork's
                    built-in compiler (libtoast_jit) compiles in memory
  harness.py        ctypes host: binding, chunks on threads, nearpoints, command merge
  shader.py         shader node code: the compiler's checks and expressions, emitted as one
                    function in Blender's portable shader dialect (EEVEE, GLSL and Metal)
  shader_lib.py     the shader functions' runtime (noise, hashes, math), as in toast_rt.h
  runtime/toast_rt.h  ABI, vector math, Blender-exact noise and hashes
tests/
  test_toast.py     python3 -m unittest discover -s tests -v
  blender_noise_ref.py  evaluates Blender's own nodes for the bit-exact test
```

```python
import toast
from toast.harness import Geometry, run
k = toast.build('n = noise(@position * param("freq", 4.0))\n@position += @normal * n * 0.2\n')
out = run(k, [Geometry({"position": P, "normal": N})], params={"freq": 2.0}, threads=8)
```

In Blender (the fork's `toast` branch): link this package as an add-on and enable it,
`ln -s ~/dev/BLENDER_DEV/toast/toast ~/.config/blender/5.3/scripts/addons/toast`. Add
Geometry Nodes > Add > Toast > Toast, then in the sidebar (N) > Node > Toast press New. Edits in
the Text Editor recompile automatically. Kernels only run with Auto Run Python Scripts allowed.

Environment: `TOAST_BACKEND` (`builtin`/`external`, overrides the add-on's Compiler
preference), `TOAST_CXX` (external compiler, default clang++ then g++), `TOAST_CACHE_DIR`,
`TOAST_BLENDER` (Blender binary for the exactness test).

## Language

Python syntax, statically typed, plus `@name` for attributes of the current element.

```python
amp = param("amp", 0.2)                  # a socket on the node
n = noise(@position * param("freq", 4.0))
@position += @normal * n * amp
@height: float = n                       # a new attribute, typed by annotation
@color = (n, 0.3, 1 - n)                 # or typed by its first value
```

Run Over (node setting): **Points**, **Faces**, **Edges**, **Face Corners**, **Curves**,
**Instances** or **Geometry** (once, for setup or building geometry). `@` attributes live on that domain: in Faces mode `@color` is
a face color and reading `@position` gives the face center (Blender's domain interpolation);
`@normal` is the vertex, face or corner normal. Geometry runs once for the whole geometry and
has no `@` attributes. The numpy harness runs points, faces, curves, instances and geometry. The node's **Selection** input
(a boolean field on the Run Over domain, evaluated before the run) limits the run to selected
elements; others are unchanged, while `@index` and `@count` keep referring to the whole domain.

- Types `float int bool vec2 vec3 vec4 quat mat4` and fixed-size lists (`[0.0] * 8`); a
  variable's type is fixed by its first assignment.
  Tuples of 2 to 4 numbers are vectors. Annotations `x: vec3 = ...` are accepted.
- Attributes use Blender's names: `@position @normal @color @velocity` (vec3), `@radius` (float),
  `@id` (int). `@color` is the mesh's active color attribute (created as a float color "Color"
  if there is none; other color types are read-only). Any other `@name` gets its type from an
  annotation (`@flag: bool`, also without a value), else from its first assigned value, else
  float. Read-only: `@index` and `@count` (the element's index and the element count of the
  run domain) and `@frame`, `@time`. Writes go to input 0, current element only.
- `if/elif/else`, `while`, `for j in range(...)`, `break`, `continue`, `return` (ends this
  element), `x if c else y`, `and/or/not`, comparison chains, swizzles (`v.xy`, `v.x = 1`),
  `v[0]`. Python semantics for `%`, `//` and int `/`; integer division by zero gives 0 instead
  of crashing.
- Builtins:
  - Parameters: `param(name, default, min=, max=)`.
  - Math: `sin` ... `sqrt floor ceil abs frac sign`, `math.*` (`math.floor` returns int),
    `min max clamp lerp smoothstep dot cross length distance normalize`,
    `map_range(x, from_min, from_max, to_min, to_max)` (Blender's Map Range, clamped).
  - Noise and random: `noise signed_noise fbm random hash01`, and
    `voronoi(position, randomness=1.0)`, a record with `.distance .color .position` of the
    nearest cell (Blender's Voronoi Texture: 3D, F1, Euclidean, detail 0, not normalized; put the
    scale in the position, and `.position` is in that scaled space).
  - Reading: `point_attr(input, name, index)`, `face_attr(input, name, index)`,
    `point_count(input)`, `face_count(input)`, `nearest_point(input, position, radius)`,
    `for j in nearby_points(input, position, radius, max_count)` (sorted by distance),
    `for p in face_points(input, face, max_count)`, `for f in point_faces(input, point,
    max_count)`, `for q in point_neighbors(input, point, max_count)` (points sharing an edge,
    ascending), `corner_point(input, corner)`, `corner_face(input, corner)`. The type of an
    attribute read comes from an annotation on the variable:
    `vel: vec3 = point_attr(1, "velocity", j)`.
  - Surfaces (the triangles of an input's mesh, through Blender's BVH):
    `ray_cast(input, origin, direction, max_distance=inf)` and
    `closest_point(input, position, max_distance=inf)` return a `hit` record with
    `.hit .position .normal .distance .face` (`.face` is -1 without a hit; the direction is
    normalized; the normal follows Blender's face winding), and
    `sample_nearest_surface(input, name, position)` interpolates a float or vector point
    attribute at the closest surface point, like Blender's Sample Nearest Surface node.
    Queries on input 0 see it as it was before the run.
  - Writing: `add_point(position)`, `add_edge(a, b)`, `add_face((a, b, c, ...))`,
    `remove_point(p)`, `remove_face(f)` (keeps its points, like Delete Geometry, Only Faces),
    `set_point_attr(index, name, value)`, `set_face_attr(index, name, value)` (write other
    elements; applied after the run in element order, so the last writer by element index wins
    whatever the thread count).
- `def` helpers at the top level: compiled once per combination of argument types (so `sq(2)`
  and `sq(0.5)` are separate int and float versions), return type from the `return`s, which must
  agree. Optional argument annotations (`def f(p: vec3)`) fix a type. Positional arguments only,
  no recursion. Inside a helper, `param()`, math, noise, `nearby_points`, `point_count`,
  `@index` and the writing calls work; `@` attributes and `point_attr()` don't (pass values in).
- Shared helpers: `from toast_lib.shapes import sphere` or `import toast_lib.shapes as shapes`
  (then `shapes.sphere(...)`). A library holds only `def`s and imports (it can import other
  libraries). In Blender it is a Text named `toast_lib.shapes` (or `toast_lib.shapes.py`);
  otherwise `shapes.py` in `$TOAST_LIB_PATH` or `~/.config/toast/lib` (`toast_lib.a.b` is
  `a/b.py`). Library sources are part of the cache key, and editing a library text recompiles
  the nodes that use it. Errors in a library name it: `toast_lib.shapes line 3: ...`.
- Older spellings (`@P`, `f@name`, `ch()`, `point()`, ...) give an error naming the new one.
- Not yet: instances, strings, matrices, Windows.

Blender equivalence (tested bit for bit against 5.3): `noise(p)` = Noise Texture (scale 1,
detail 0); `fbm(p, detail=2, roughness=0.5, lacunarity=2)` = Noise Texture fBM, normalized,
distortion 0; `random(id, seed)` = Random Value (Float, 0 to 1); `voronoi(p, r)` = Voronoi Texture (3D, F1,
Euclidean, detail 0, randomness `r`; distance, color and position outputs). Scale goes in the position:
`noise(@position * 4)` = Noise Texture with Scale 4.

## Contract for the fork's host

- Bind `signature["attrs"]` in order. `snapshot: true` means a read-only copy of input 0 from
  before the run; `create: true` means create the attribute (zeroed) if missing.
- Params: a byte buffer of `params_size`, fields at `offset` (bool as int32, vec3 12 bytes).
- Chunks have a fixed grain, `chunk_id = begin / grain`, one command buffer per chunk.
- Merge (see `harness.py` docstring): sort by (source index, emission order); new points
  appended with P set and other attributes zero; prims appended; removals last, and removing a
  point removes every prim using it. On meshes, edges between two surviving points stay, as
  with Delete Geometry on points (the harness has no edges, only prims).
- `nearpoints` returns points within radius, sorted by distance then index.
- ABI 2 (`toast_rt.h`, fork `toast_abi.h`): adds `nprims`, `primpoints`, `cmd_remove_prim` and
  the face/edge/corner domain codes. Removals: faces first (points kept), then points.
- ABI 3: adds `point_faces`, `point_neighbors`, `corner_point`, `corner_face` and
  `cmd_set_attr` (applied after the run, in element order, before topology changes).
- ABI 4: adds `ToastHit`, `ray_cast` and `closest_point` (the input's triangles before the run).
  The harness does both by brute force over a fan triangulation, so compare it with Blender on
  triangle meshes.
- Outputs (0.11, no ABI change): `output(name, value)` binds a writable attribute with
  `"output": true` in the signature's `attrs`, and the signature lists `outputs` (name, type,
  socket). The node declares them as anonymous attribute outputs and binds the anonymous
  attribute Blender gives each used socket; unused ones get a scratch buffer.
- ABI 5: adds `ncurves`, `curve_points`, `cmd_remove_curve`, the curve and instance domain
  codes, and the `quat` (w, x, y, z) and `mat4` (column-major 4x4) attribute types. The node runs
  Points on each of the mesh, point cloud and curves; input 0 is then only that component.
  Instance `@position` is bound as a copy of the transforms' translation and written back after
  `@transform`, so it wins. On curves, `remove_point`/`remove_curve` use
  `curves_copy_point_selection` (curves without points go).
- ABI 6: adds `cmd_add_curve` (a curve through points, like `cmd_add_prim`) and
  `cmd_extend_curve` (a point at a curve's tip; returns a point handle numbered with
  `cmd_add_point`'s, copies the tip's other attributes). The signature's `uses.curves` makes Run
  Over Geometry run on curves (made if missing). The node rebuilds the curves once after the run:
  input curves with their new tips, then new curves (poly), then removals; `_merge_curves` in the
  harness is the reference.
- ABI 7: adds `surface_point(input, u, v, w, hit)`: `u` picks a triangle of the input's mesh by
  cumulative area (twice the area per triangle, in double, summed in `corner_tris` order, upper
  bound), `v`/`w` are the barycentric weights of its second and third corner (folded when
  v + w > 1); position `a * (1 - v - w) + b * v + c * w` in float. Kernels draw u, v, w with
  `random(id, seed)`, `seed + 1000003`, `seed + 2000006`.
- ABI 8: adds `grid_sample(grid, mode, pos, out)`: the signature's `grids` (input, name, type),
  by slot, as they were before the run. World to index with the grid matrix inverted in double
  (from the float matrix), then trilinear over voxel values (x, then y, then z, `a + (b - a) * t`,
  just `a` when t is 0); mode 1 is the gradient of a float grid, central differences one voxel
  (the length of the matrix column) along each world axis. Run Over Voxels runs on a point cloud
  of the voxels active in any grid the code uses (all grids if none exist), tiles split, ordered
  by leaf origin then offset; written attributes go back into grids. `_run_voxels` and
  `_GridSampler` in the harness are the reference.
- ABI 9: `grid_sample` mode 2 reads the voxel at an index (each coordinate `floor(x + 0.5)`);
  adds `voxel_cmd(op, ijk, radius)`: activate a cube of `radius` (0..16) / deactivate a voxel in
  every grid of the volume with the run's transform, after the written grids are stored;
  deactivations first and only of voxels nothing activates (sets: call order doesn't matter);
  `_apply_voxel_cmds` in the harness is the reference. `@voxel`/`@voxel_size` are bound as the
  attributes `__voxel` and `__voxel_size` of the voxels' point cloud.
- ABI 10: `grid_sample` mode 3 gives the index nearest to a position (slot type "any");
  `voxel_cmd` works in every mode (outside Voxels on the transform of the volume's first grid,
  applied per real geometry after its components ran). Run Over Voxels kernels may bind
  `__grid_<name>` (the grid on the voxels, read at each voxel's index in the grid's own index
  space; zeros if missing or of the other kind) and `__n0`..`__n5` (voxel number of the +x, -x,
  +y, -y, +z, -z neighbor, or -1): signature attrs with `"grid": true`, filled by the node.

### Shader node (0.20, no ABI change)

`ShaderNodeToast` stores `signature` and `gpu_source` (written by the add-on). The signature has
`"run_over": "shader"`, `function` (`toast_<hash of the code>`), `params`, `inputs` (`name`,
`kind` "builtin" or "attribute", `type`) and `outputs` (`name`, `type`). The node calls
`function(params..., inputs..., outputs...)` through the fork's `GPU_stack_link_source`, which
puts `gpu_source` (the runtime and the function, each in an include guard) into the material's
generated shader. Built-in inputs come from the Geometry, Texture Coordinate and Scene Time
library functions; named attributes are passed as float4 and converted by the function (as the
Attribute node does). Only in trusted files.

Cycles (CPU, 0.21): the node also stores `kernel_path`, C++ (`ShaderSource.cpu`, built by
`build_shader_cpu`) exporting `toast_shader(const float *in, float *out)`: params, then inputs,
packed as floats in signature order (float/int/bool 1, vec3 3, vec4 4), outputs the same way.
The fork's `toast_shader_info()` (`NOD_toast.hh`) compiles it with the built-in compiler; the
Cycles sync makes a `ToastNode` (sockets per node, like OSL's) wired to Geometry, Texture
Coordinate, Attribute, Color Attribute and Scene Time nodes, and SVM's `NODE_TOAST` calls the
function by its address (CPU only; other devices write zeros).

Cycles Metal (0.22, linked since 0.23): the sync also gives each `ToastNode` its EEVEE function
plus a wrapper taking the packed floats. Before loading kernels, `Scene::device_update` collects
the scene's functions (`ToastNode::scene_source`: sorted, numbered, in namespace `toast_metal`,
each exported as a `[[visible]]` function) and passes them to `Device::set_toast_functions`.
Metal compiles them as a small library of its own (milliseconds). A scene with Toast nodes gets
kernels built once with `__TOAST_NODES__` (a few minutes the first time, then cached), whose
pipelines accept added binary functions; `MetalDispatchPipeline::update` links the current
functions in (`newComputePipelineStateWithAdditionalBinaryFunctions`) and fills a visible
function table that `NODE_TOAST` calls through (`MetalAncillaries::ft_toast`). New Toast code
only re-links: no kernel is built.

## Measurements (2026-11-24, 32 threads, g++ 14, fork 5.3)

Noise displace (`n = noise(@position * freq); @position += @normal * n * amp; @height: float = n`) on an ico sphere,
Toast node vs the equivalent node tree (Store Named Attribute + Set Position). Median modifier
evaluation, `tests/bench_blender.py`. Both give bit-identical positions and heights.

| Points | Threads | Toast | Hand C++ node | Node tree | Toast vs nodes |
| --- | --- | --- | --- | --- | --- |
| 164k | all | 1.3 ms | 0.8 ms | 5.4 ms | 4.0x |
| 164k | 1 | 8.9 ms | 11.0 ms | 61.6 ms | 6.9x |
| 2.6M | all | 11.3 ms | 14.1 ms | 60.7 ms | 5.4x |
| 2.6M | 1 | 131.6 ms | 182.6 ms | 950.4 ms | 7.2x |

The hand C++ node is the `toast_plugin_noise_displace` plugin in the fork, calling Blender's
`noise::perlin`. Toast is faster in three of four cases: kernels are built with `-march=native`
and the noise code inlines. Toast's fixed cost per evaluation (kernel lookup, parameters, binding,
~0.5 ms) shows on small meshes.

Reaction-diffusion step (2026-11-26, built-in compiler; `examples/src/reaction_diffusion/step.py`:
`point_neighbors()` and a few reads per point) vs the same with nodes, Blur Attribute for the neighbor average,
`tests/bench_reaction_diffusion.py`. The node reuses its neighbor table while the topology stays
the same (steps of a Repeat Zone, frames of a simulation): about 4 ms to build at 164k points
when it changes.

| Points | Threads | Toast | Node tree | Toast vs nodes |
| --- | --- | --- | --- | --- |
| 41k | all | 0.23 ms | 3.0 ms | 12.9x |
| 41k | 1 | 0.82 ms | 7.3 ms | 8.9x |
| 164k | all | 0.89 ms | 7.1 ms | 7.9x |
| 164k | 1 | 4.8 ms | 34.8 ms | 7.2x |
| 655k | all | 2.8 ms | 25.4 ms | 9.1x |
| 655k | 1 | 14.5 ms | 204.1 ms | 14.1x |

Shader node (2026-11-27, MacBook M3 Max, `tests/bench_shader.py`): a plane filling a 1920x1080
frame emits a texture, written as a Toast node and as the same tree of Blender nodes (the
renders match pixel for pixel). "Light" is one Noise Texture; "heavy" is a domain warp (3 noises)
into an fbm of detail 8 and two Voronoi, mixed (12 nodes, 8 lines of Toast). Best of 5 renders
after warming up; Metal with Cycles' default kernel optimization (FULL).

| Engine | Flat | Toast kernels only | Constant Toast node | Light: Toast / nodes | Heavy: Toast / nodes | Heavy, texture alone: nodes / Toast |
| --- | --- | --- | --- | --- | --- | --- |
| Cycles CPU (16 samples) | 0.51 s | 0.50 s | 0.57 s | 0.82 / 0.72 s | 1.73 / 2.19 s | 1.4x |
| Cycles Metal (256 samples) | 1.25 s | 1.27 s | 1.48 s | 1.55 / 1.61 s | 2.56 / 3.47 s | 1.7x |
| EEVEE (1024 samples) | 4.60 s | 4.99 s | 4.76 s | 4.81 / 4.59 s | 7.02 / 7.61 s | (noise) |

Cycles runs node trees through its SVM interpreter, one node at a time; the Toast node is one
compiled function, so the more nodes it replaces, the more it gains. A single node breaks even,
since calling Toast has a cost of its own (packing values, and on Metal a call through a
function table). EEVEE compiles both to the same kind of GPU code: no real difference (runs vary
by about 0.4 s). This is a best case: with lighting and bounces the texture is a smaller part of
the render. On Metal with kernel optimization OFF, the kernels of a scene with Toast nodes are
~1.6x slower everywhere (the default, FULL, removes that).

Compile of the noise displace kernel: ~0.1 s with the fork's built-in compiler (0.4 s with g++); reopening a
file with the kernel cached costs a few ms.
Read attributes are bound as views of Blender's arrays (copies only for snapshots, type
conversions and an input-0 KD-tree, made in parallel). Before that change the 2.6M-point case
took 14.6 ms. Toast now scales ~12x on 32 threads; the rest is work any node does around the
kernel (un-sharing positions for writing, creating the new attribute, vertex normals).

## License

GPL-2.0-or-later, like Blender (see `LICENSE`).
