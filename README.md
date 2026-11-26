# Toast frontend

Python goes in, native code pops out. **Using Toast: see [docs/guide.md](docs/guide.md)** (language, builtins, cookbook),
also as a page to open in a browser: `docs/guide.html` (rebuild it with `python3 docs/build_guide.py`
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
- ABI 5: adds `ncurves`, `curve_points`, `cmd_remove_curve`, the curve and instance domain
  codes, and the `quat` (w, x, y, z) and `mat4` (column-major 4x4) attribute types. The node runs
  Points on each of the mesh, point cloud and curves; input 0 is then only that component.
  Instance `@position` is bound as a copy of the transforms' translation and written back after
  `@transform`, so it wins. On curves, `remove_point`/`remove_curve` use
  `curves_copy_point_selection` (curves without points go).

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

Compile of this kernel: ~0.1 s with the fork's built-in compiler (0.4 s with g++); reopening a
file with the kernel cached costs a few ms.
Read attributes are bound as views of Blender's arrays (copies only for snapshots, type
conversions and an input-0 KD-tree, made in parallel). Before that change the 2.6M-point case
took 14.6 ms. Toast now scales ~12x on 32 threads; the rest is work any node does around the
kernel (un-sharing positions for writing, creating the new attribute, vertex normals).

## License

GPL-2.0-or-later, like Blender (see `LICENSE`).
