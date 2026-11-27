# Toast guide

Toast lets you write the inside of a geometry node in Python syntax. The code runs once per point
(or face, edge, corner, curve, instance), on every CPU core, compiled to native code: no Python
runs while Blender evaluates the node tree.

```toast
amp = param("amp", 0.2)
n = noise(@position * param("freq", 4.0))
@position += @normal * n * amp
@height: float = n
```

## Setting up

1. Use the Blender build from the `toast` fork branch ([building it](building.md)), and enable the **Toast** add-on
   (Preferences > Add-ons).
2. Allow **Auto Run Python Scripts** (Preferences > Save & Load), or trust the file. Toast code
   in a `.blend` runs native code, so it follows the same rule as Python drivers.
3. In a Geometry Nodes tree, add **Toast > Toast**. In the sidebar (N) > Node > Toast, press
   **New** to create a text with starter code, or pick one from **Templates**.

The node recompiles a moment after you stop typing: Blender's built-in compiler turns the code
into native code in about 0.1 s, and reopening a file reuses the compiled code. To compile right
away, press **Ctrl+Enter** (**Cmd+Enter** on macOS) in the Text Editor, or use **Compile**: in the
Text Editor header and its Text menu, on the Toast node, and in the node's Toast panel. Don't
press Run Script: Toast code isn't plain Python.

For complete scenes (flocking, hair, fluid, reaction-diffusion, growth, fractals, a tree), open
the [example files](https://github.com/varomix/toast/tree/main/examples).

### Editing

- **Auto Compile** (on by default, in the Toast panels and the add-on preferences): turn it off
  when the code is heavy and you don't want it to run while you type. Then edits compile only
  with **Ctrl+Enter** / **Cmd+Enter** or a **Compile** button, and the panels say when the code
  has changed but isn't compiled. Opening a file still compiles what its nodes need.
- **Follow Active Node** (on by default, in the Toast panel and the add-on preferences): selecting
  a Toast node shows its code in the Text Editor of the same window, and an empty Text Editor
  always shows the selected node's code. Turn it off to keep the Text Editor on whatever you are
  editing.
- **Templates**: starter code for common jobs (noise, smoothing, scattering onto a surface,
  curves, instances...). In the node's Toast panel, a template is used by the node and sets its
  Run Over; in the Text Editor (Templates > Toast) it only creates the text.
- **Errors** show on the node header, in the node's Toast panel and in the Text Editor's sidebar
  (N) > Toast, with **Go to Error**, which puts the cursor on the line (also inside a library).
- **Status**: the Toast panels say whether the code is up to date, waiting for you to stop
  typing, or reused from an earlier compile.
- **Toast Guide** opens this guide in a web browser: Help > Toast Guide, the **?** button in the
  node's Toast panel, the Text Editor's sidebar (N) > Toast, and Templates > Toast.

## The node

| Socket | Meaning |
| --- | --- |
| Geometry | The geometry the code runs on and writes to (input 0). |
| Selection | Elements to run on (a boolean field). Others are left unchanged. |
| Input 1 | Another geometry the code can read: `point_attr(1, ...)`, `ray_cast(1, ...)`. Its points are those of its mesh, else its point cloud, curves or instances. |
| *params* | One socket per `param()` in the code. |

**Run Over** sets what the code runs once for:

| Run Over | Runs once per | `@` attributes live on |
| --- | --- | --- |
| Points | point of the mesh, point cloud and curves | points |
| Faces | face | faces (`@position` reads the face center) |
| Edges | edge | edges |
| Face Corners | face corner | corners |
| Curves | curve | curves (`@position` reads the average of its points) |
| Instances | instance of the top-level geometry | instances (`@position`, `@transform`) |
| Voxels | active voxel of the volume's grids | grids: each `@name` is a grid (`@position` reads the voxel's center) |
| Geometry | once for the whole geometry | (none) |

With Points, the code runs separately on each part that has points: the mesh, the point cloud and
the curves. Input 0 is then the part being run on: `point_count(0)` and `nearby_points(0, ...)`
see only its points.

**Grease Pencil:** each layer's strokes on the current frame are curves to Toast. Points and
Curves run on every layer, one layer at a time (input 0 is that layer's strokes), and so does
Geometry when the code makes curves: `add_curve()` then draws new strokes into each layer.
Grease Pencil attributes have their Blender names: `@radius`, `@opacity`, `@vertex_color`
(`vec4`), and your own. Input 1 doesn't read Grease Pencil yet.

**Volumes:** with Voxels, every `@name` the code uses is a grid of the volume: reading `@density`
reads the "density" grid at the voxel, writing `@velocity` writes the "velocity" grid, and a
grid that doesn't exist yet is made. Grids hold `float`, `int`, `bool` or `vec3` (annotate a new
vector grid, `@velocity` is one already). The code runs once per voxel that is active in any of
the grids it uses (in all the volume's grids when none of those exist yet), and grids it writes
gain those voxels. Make a box of voxels with Cube Grid Topology and Store Named Grid, or start
from any volume. Grids on another voxel size or place than the first one are left out, with a
warning. `@voxel` is the voxel's index (a vec3 of whole numbers) and `@voxel_size` its size along
each axis. Read a neighbor with `grid_voxel(0, "pressure", @voxel + vec3(1, 0, 0))`, or a grid
anywhere (where smoke came from) with `sample_grid()`; both read the grids as they were before
the run. Reading input 0 at `@voxel`, or one step from it along one axis (`@voxel + vec3(0, 0, 1)`,
also through a variable only ever set to `@voxel`), reads arrays instead of asking the node: the
fast way to read neighbors. `activate_voxel()` and `deactivate_voxel()` change which voxels
exist, so a simulation's grid can follow its smoke. Commands (`add_point()`, `set_point_attr()`...)
and `output()` don't work with Voxels.

Every element runs independently and in parallel. Writing `@name` changes the current element
only; to change other elements, use `set_point_attr()` and the topology functions below, which
are applied after the run in element order. The result never depends on the number of threads.

## Language

Toast is a statically typed subset of Python.

- **Types:** `float`, `int`, `bool`, `vec2`, `vec3`, `vec4`, `quat` (a rotation), `mat4` (a
  transform) and lists. A variable's type is fixed by its first assignment; annotate to choose
  one: `x: float = 1`. Tuples of 2 to 4 numbers are vectors: `(0, 0, 1)`.
- **Vectors:** `v.x`, `v.xy`, `v.zyx`, `v[0]`; `v.x = 1` sets one component. `+ - * /` work
  between vectors of the same size and between a vector and a number.
- **Control flow:** `if/elif/else`, `while`, `for i in range(...)`, `break`, `continue`,
  `x if cond else y`, `and/or/not`, comparison chains like `0 < x < 1`. `return` at the top level
  ends the current element.
- **Numbers:** `%`, `//` and `/` follow Python (`7 / 2` is `3.5`). Integer division by zero gives
  0 instead of crashing Blender.
- **Not supported:** classes, dicts, growing lists, strings (except as names), recursion,
  `*args`, imports other than `math` and Toast libraries.

### Lists

Lists have a size known when the code compiles: a fixed size, or a growable list's capacity
(up to 1048576 values; a list written out value by value holds at most 4096):

```toast
d = [0.0] * 8                 # 8 floats, all 0
weights = [0.25, 0.5, 0.25]   # 3 floats
corners: list[vec3] = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
d[0] = 1.5
d[-1] += 2                    # -1 is the last value, as in Python
total = 0.0
for w in weights:
    total += w
@n: int = len(d)
```

Reading outside the list gives 0 and writing outside it does nothing, so a wrong index never
crashes Blender. Lists are values, like vectors: `b = a` and passing `a` to a helper make a copy
(unlike Python), so return a changed list from a helper. A list can't be stored in an attribute.
Where a vector is expected, a list of numbers is a vector: `@position = [0, 0, 1]`.

A **growable list** is declared with its type and capacity, starts empty, and has `append()`,
`pop()` and `clear()`; `len()` and `for` loops see only the values in it:

```toast
close: list[int, 256] = []
for j in nearby_points(0, @position, 0.5, 4096):
    if j != @index:
        close.append(j)
@neighbors: int = len(close)
last = close.pop()            # removes and returns the last value (0 when empty)
```

Appending to a full list does nothing. Lists bigger than 256 KB (65536 floats, 21845 vec3s) live
on the heap instead of the stack: they work the same but cost an allocation per element, so keep
big lists for Run Over Geometry or a few elements.

### Rotations and transforms

`quat` is a rotation and `mat4` a 4x4 transform, the same as Blender's Rotation and Matrix
sockets and attributes.

```toast
q = quat_axis_angle((0, 0, 1), math.pi / 2)
v = rotate(q, (1, 0, 0))                      # (0, 1, 0)
m = mat4_compose((1, 2, 3), q, 2.0)           # location, rotation, scale
p = transform_point(m, (1, 0, 0))             # (1, 4, 3)
back = transform_point(inverse(m), p)
@spin: quat = q * quat_euler((0.1, 0, 0))     # combine rotations with *
@xform: mat4 = m * mat4_translation((0, 0, 1))
location = m.translation                      # also m.rotation, m.scale
```

| Function | Returns |
| --- | --- |
| `quat()`, `quat(w, x, y, z)` | No rotation, or a quaternion from components (`.w .x .y .z` read them). |
| `quat_axis_angle(axis, angle)`, `quat_euler(xyz)`, `quat_between(a, b)` | A rotation around an axis, from XYZ Euler angles (radians), or the smallest rotation turning direction `a` into `b`. |
| `rotate(q, v)`, `slerp(a, b, t)`, `to_euler(q)`, `normalize(q)` | Rotate a vector; blend rotations; Euler angles of a rotation. |
| `mat4()`, `mat4_translation(v)`, `mat4_rotation(q)`, `mat4_scale(s)`, `mat4_compose(location, rotation, scale)` | Transforms (`s` is a number or vec3). |
| `transform_point(m, p)`, `transform_direction(m, d)` | Transform a point, or a direction (ignoring the location). |
| `inverse(q or m)`, `transpose(m)` | A transform that can't be inverted gives a zero matrix. |
| `m.translation`, `m.rotation`, `m.scale` | The parts of a transform (read-only). |

`*` combines two rotations or two transforms; to apply them to a vector, use `rotate()` or
`transform_point()`.

### Attributes

`@name` is an attribute of the current element. Toast uses Blender's attribute names:

| Attribute | Type | Notes |
| --- | --- | --- |
| `@position` | vec3 | Point positions. In Faces/Edges/Corners mode, reading interpolates. |
| `@normal` | vec3 | Vertex, face or corner normals (or an attribute named `normal`). |
| `@color` | vec3 | The mesh's active color attribute, created as "Color" if missing. |
| `@velocity` | vec3 | |
| `@radius` | float | |
| `@id` | int | |
| `@transform` | mat4 | With Run Over Instances: the instance's transform. |
| `@index` | int | Index of the current element (read-only). |
| `@count` | int | Number of elements in the Run Over domain (read-only). |
| `@frame`, `@time` | float | Scene frame and time in seconds (read-only). |
| `@voxel`, `@voxel_size` | vec3 | With Run Over Voxels: the voxel's index and size (read-only). |

Any other name is your own attribute. Its type comes from an annotation, or from its first
assigned value, or is `float`:

```toast
@height: float = 0.5          # declared and written
@flag: bool                   # declared only
@offset = (0, 0, 1)           # a vec3, from the value
@flag = @height > 0.3
```

Writing an attribute that doesn't exist creates it on the Run Over domain.

To read an attribute that another node made, give it its type: `@previous: vec3`. Without one it
is read as a float, and when that loses data (a vector read as a float, a float as an int), the
node shows a warning naming the type to use.

With Run Over Instances, `@position` is the location of the instance's transform: writing it
moves the instance. When the code writes both `@transform` and `@position`, the location comes
from `@position`.

### Parameters

`param(name, default, min=, max=)` adds a socket to the node; its type comes from the default.
The same name always refers to the same socket.

```toast
amount = param("amount", 0.5, min=0, max=1)
count = param("count", 3)
flip = param("flip", False)
offset = param("offset", (0.0, 0.0, 1.0))
@position += offset * amount * count
if flip:
    @position.z = -@position.z
```

### Outputs

`output(name, value)` adds an output socket to the node, with `value` for each element of the
Run Over domain: a field, like the Top and Side outputs of Extrude Mesh. Connect it to any field
input after the node: a Boolean output is a selection, a Float can drive a Set Position offset or
a Store Named Attribute.

```toast
cell = voronoi(@position * 4)
output("distance", cell.distance)          # Float socket
output("cell_color", cell.color)           # Vector socket
output("inside", cell.distance < 0.3)      # Boolean socket: a selection
```

The socket type comes from the value: `float`, `int`, `bool`, `vec3` (Vector), `vec4` (Color),
`quat` (Rotation) or `mat4` (Matrix). Elements that don't reach the `output()` call (inside an
`if`) get 0 or False. Outputs are not stored on the geometry under their name, so they don't
clutter the attribute list; use `@name = ...` for that. Run Over Geometry has no elements, so it
can't have outputs.

### Helpers and libraries

`def` helpers are compiled once for each combination of argument types they are called with:

```toast
def bump(p: vec3, amount):
    return p + (0, 0, amount)

def sq(x):
    return x * x

@position = bump(@position, sq(@index * 0.01))
```

Inside a helper, `param()`, math, noise, `nearby_points()` and the writing functions work;
`@` attributes and `point_attr()` don't (pass the values as arguments).

Put shared helpers in a **library**: a Text named `toast_lib.<name>` (or a file `<name>.py` in
`~/.config/toast/lib` or `$TOAST_LIB_PATH`) containing only `def`s and imports.

```python
# Text "toast_lib.shapes"
def sphere(p: vec3, radius):
    return length(p) - radius
```

```python
# Node code
from toast_lib.shapes import sphere
@inside = sphere(@position, 1.0) < 0
```

Editing a library recompiles every node that uses it.

## Builtins

### Math

| Function | Notes |
| --- | --- |
| `sin cos tan asin acos atan sinh cosh tanh exp log log2 log10 sqrt` | Numbers and vectors (per component). |
| `len(list)` | The size of a list (or a vector). |
| `floor ceil trunc abs frac sign radians degrees` | Same. `math.floor/ceil/trunc` return int, as in Python. |
| `pow(x, y)`, `atan2(y, x)`, `fmod(x, y)`, `min`, `max` | |
| `clamp(x, lo, hi)` | |
| `lerp(a, b, t)` | `a + (b - a) * t` |
| `map_range(x, from_min, from_max, to_min, to_max)` | Like Blender's Map Range (linear, clamped). |
| `smoothstep(edge0, edge1, x)` | |
| `dot(a, b)`, `cross(a, b)`, `length(v)`, `distance(a, b)`, `normalize(v)` | `normalize` keeps zero vectors at zero. |
| `vec2(...)`, `vec3(...)`, `vec4(...)`, `int(x)`, `float(x)`, `bool(x)` | |
| `math.pi`, `math.tau`, `math.e` | |

### Noise and random

These match Blender's nodes exactly (bit for bit). Put the scale in the position.

| Function | Equals |
| --- | --- |
| `noise(p)` | Noise Texture factor (scale 1, detail 0), in 0..1. `p` is a float or vec2/3/4. |
| `signed_noise(p)` | The same noise in -1..1. |
| `fbm(p, detail=2, roughness=0.5, lacunarity=2)` | Noise Texture (fBM, normalized). |
| `voronoi(p, randomness=1)` | Voronoi Texture (3D, F1, Euclidean). Returns a cell with `.distance`, `.color`, `.position`. |
| `random(id, seed)` | Random Value node (Float, 0..1). |
| `hash01(x)` | A hash of `x` in 0..1 (int, float or vector). |
| `curl_noise(p)` | A swirling vec3 field (the curl of three noises): moving points along it looks like smoke or water. Toast's own, there is no Blender node for it. |

### Reading geometry

`input` is a constant: 0 for the node's Geometry, 1 for Input 1.

| Function | Returns |
| --- | --- |
| `point_attr(input, "name", index)` | An attribute of a point. Annotate for its type: `v: vec3 = point_attr(1, "velocity", j)`. |
| `face_attr(input, "name", index)` | An attribute of a face. |
| `curve_attr(input, "name", index)`, `instance_attr(input, "name", index)` | An attribute of a curve or an instance. |
| `point_count(input)`, `face_count(input)`, `curve_count(input)` | Element counts. |
| `nearest_point(input, position, radius)` | The closest point within `radius`, or -1. |
| `corner_point(input, corner)`, `corner_face(input, corner)` | The point and face of a face corner, or -1. |
| `ray_cast(input, origin, direction, max_distance)` | A hit: `.hit`, `.position`, `.normal`, `.distance`, `.face` (-1 without a hit). |
| `closest_point(input, position)` | The closest point on the surface, as a hit. |
| `random_surface_point(input, id, seed=0)` | A random point on the surface, area weighted, as a hit (position, normal, face). The same `id` and `seed` give the same point: for emitting particles. |
| `sample_nearest_surface(input, "name", position)` | A point attribute interpolated at the closest surface point. |
| `sample_grid(input, "name", position)` | A volume grid's value at a position, trilinear: a float, or a vec3 for a vector grid (`velocity`, a declared `@name: vec3`, or annotate: `v: vec3 = sample_grid(0, "flow", p)`). 0 where the grid is missing. With any Run Over. |
| `grid_voxel(input, "name", index)` | A grid's value at a voxel index (rounded), no interpolation: the fast way to read neighbors, `grid_voxel(0, "density", @voxel + vec3(0, 0, 1))`. |
| `voxel_at(input, "name", position)` | The index of a grid's voxel nearest to a position (a vec3 of whole numbers): where a point is, for `activate_voxel()`. |
| `grid_gradient(input, "name", position)` | The gradient of a float grid (vec3), by central differences one voxel apart: points up the slope of a density or out of an SDF. |

Loops over related elements take a constant maximum count:

| Loop | Visits |
| --- | --- |
| `for j in nearby_points(input, position, radius, max_count):` | Points within `radius`, closest first. |
| `for p in face_points(input, face, max_count):` | The points of a face, in order. |
| `for p in curve_points(input, curve, max_count):` | The points of a curve, from root to tip. |
| `for f in point_faces(input, point, max_count):` | The faces using a point. |
| `for q in point_neighbors(input, point, max_count):` | Points sharing an edge with a point. |

Reading input 0 with these functions sees the geometry as it was before the run, even for
attributes the code is writing.

### Changing geometry

| Function | Does |
| --- | --- |
| `add_point(position)` | Adds a point and returns it, for `add_edge`/`add_face`/`add_curve` in the same run. |
| `add_edge(a, b)` | Adds an edge. |
| `add_face((a, b, c, ...))` | Adds a face through 3 or more points. |
| `remove_point(p)` | Removes a point and the edges and faces using it. |
| `remove_face(f)` | Removes a face and keeps its points (like Delete Geometry, Only Faces). |
| `add_curve((a, b, ...))`, `add_curve(points, n)` | Adds a curve through points made with `add_point()`, in order: a tuple, or the first `n` point numbers of a list of ints. Each new point must be in exactly one new curve. New curves are poly curves. |
| `extend_curve(c, position)` | Adds a point at the tip of curve `c` and returns it (for `set_point_attr()`). The new point copies the tip's other attributes, like its radius. |
| `remove_curve(c)` | Removes a curve and its points. |
| `remove_instance(i)` | Removes an instance (Run Over Instances). |
| `activate_voxel(index, radius=0)` | After the run, the voxels within `radius` of a voxel index (a cube) exist in every grid of the geometry's volume, holding the background if they're new. Any Run Over: outside Voxels, the index is in the volume's first grid's voxels (see `voxel_at()`). |
| `deactivate_voxel(index)` | After the run, the voxel is gone from every grid (it reads as the background), unless something activated it in the same run. |
| `set_point_attr(index, "name", value)`, `set_face_attr(...)` | Writes another element's attribute. `set_point_attr()` also writes points added in the same run: pass what `add_point()` returned, or the point's number (see the grid example below). |

These are applied after the run in element order: new elements are numbered by the element that
created them, and when several elements write the same attribute, the highest index wins.
Removing the last point of a curve removes the curve.

On curves, new points are stored with their curve: the input's curves come first, each followed
by the points `extend_curve()` added to it, then the new curves. Inside a run, use the numbers
described under "Build a grid from scratch" (`point_count(0)` on, in the order added); after it,
points are renumbered curve by curve. With Run Over Geometry, code that makes curves runs on the
geometry's curves, and creates them if there are none (a mesh next to them is left as it is).

## Cookbook

### Thin out points at random

```toast
keep = param("keep", 0.5, min=0, max=1)
if random(@index, param("seed", 0)) > keep:
    remove_point(@index)
```

### Smooth a mesh

Each point moves toward the average of its neighbors (run it a few times for more).

```toast
total = vec3(0, 0, 0)
count = 0
for q in point_neighbors(0, @index, 32):
    total += point_attr(0, "position", q)
    count += 1
if count > 0:
    @position = lerp(@position, total / count, param("strength", 0.5))
```

### Drop points onto a surface

Connect the ground mesh to Input 1.

```toast
hit = ray_cast(1, @position, (0, 0, -1), 1000.0)
if hit.hit:
    @position = hit.position
    @normal_up: vec3 = hit.normal
```

### Shrink-wrap to the closest surface

```toast
target = closest_point(1, @position)
@position = lerp(@position, target.position, param("factor", 1.0))
```

### Transfer a color from another mesh

```toast
@color = sample_nearest_surface(1, "Color", @position)
```

### Color by Voronoi cell

```toast
cell = voronoi(@position * param("scale", 4.0))
@color = cell.color
@edge_distance: float = cell.distance
```

### Grow hairs along the normal

```toast
length_ = param("length", 0.2)
tip = add_point(@position + @normal * length_ * (0.5 + random(@index, 3)))
add_edge(@index, tip)
```

### Delete faces that point down (Run Over: Faces)

```toast faces
if @normal.z < param("threshold", -0.5):
    remove_face(@index)
```

### Build a grid from scratch (Run Over: Geometry)

```toast geometry
size = param("size", 5)
base = point_count(0)
for y in range(size):
    for x in range(size):
        add_point((x * 0.1, y * 0.1, 0))
for y in range(size - 1):
    for x in range(size - 1):
        a = base + y * size + x
        add_face((a, a + 1, a + size + 1, a + size))
```

Point numbers from `point_count(0)` on are the points added in this run, in the order they are
added (element by element, then in the order each element adds them). That is how the result
numbers them, so with Run Over Geometry you can compute them, as here.

### Swirl points with curl noise

```toast
@position += curl_noise(@position * param("freq", 1.5) + (0, 0, @time * 0.2)) * 0.1
```

### Randomize instances (Run Over: Instances)

```toast instances
angle = random(@index, 0) * math.tau
s = map_range(random(@index, 1), 0, 1, 0.5, 1.5)
@transform = @transform * mat4_compose((0, 0, 0), quat_axis_angle((0, 0, 1), angle), s)
```

### Keep half of the curves (Run Over: Curves)

```toast curves
if random(@index, param("seed", 0)) > 0.5:
    remove_curve(@index)
```

### Grow every curve from its tip (Run Over: Curves)

Inside a Simulation Zone, the curves get longer every frame: trails, vines, hair growing out.

```toast curves
tip = 0
for p in curve_points(0, @index, 4096):
    tip = p
here: vec3 = point_attr(0, "position", tip)
step = curl_noise(here * param("scale", 1.5)) * param("speed", 0.05)
extend_curve(@index, here + step)
```

### Draw curves from scratch (Run Over: Geometry)

```toast geometry
count = param("curves", 12)
size = min(param("points", 40), 64)   # points per curve, at most the list's 64
pts = [0] * 64
n = point_count(0)
for c in range(count):
    p = vec3(float(c) * 0.2, 0, 0)
    for k in range(size):
        add_point(p)
        pts[k] = n
        n += 1
        p += (0, 0.05, 0) + curl_noise(p * 2) * 0.02
    add_curve(pts, size)
```

### Emit particles from a surface (Run Over: Geometry)

Inside a Simulation Zone, with the emitter mesh on Input 1 and a Points node (velocity, age,
removal) after it:

```toast geometry
rate = param("rate", 100)
for k in range(rate):
    pid = int(@frame) * rate + k          # the same frame emits the same particles
    h = random_surface_point(1, pid)
    if not h.hit:
        break
    p = add_point(h.position)
    set_point_attr(p, "velocity", h.normal * param("speed", 2.0))
    set_point_attr(p, "id", pid)
@velocity: vec3
@id: int
```

### Move smoke along its velocity (Run Over: Voxels)

On a volume with "density" and "velocity" grids, in a Simulation Zone: each voxel takes the
smoke from where it came from (semi-Lagrangian advection). The smoke example adds the pressure
solve that makes it swirl.

```toast voxels
dt = param("delta_time", 0.0417)
back = @position - @velocity * dt
@density = sample_grid(0, "density", back)
@velocity = sample_grid(0, "velocity", back) + vec3(0, 0, param("buoyancy", 2.0) * @density * dt)
```

The Simulation Zone's Delta Time is 0 on its first frame. Multiplying by it is fine; to divide by
it (a rate per second, like the fire example's `@flame`), use `max(dt, 1e-4)`, or 0 / 0 makes NaN
that stays in the grids.

### A grid that follows the smoke (Run Over: Voxels)

At the end of a smoke step: voxels with smoke keep three voxels around them, empty ones go. The
volume then holds only where the smoke is, wherever it drifts.

```toast voxels
if @density > param("keep", 0.02):
    activate_voxel(@voxel, 3)
else:
    deactivate_voxel(@voxel)
```

### Points that make room in a volume (Run Over: Points)

Particles with a volume in the same geometry (join them): each switches on the voxels around it.
A Voxels node after this can fill them, e.g. with a density from `nearby_points(1, ...)`.

```toast
activate_voxel(voxel_at(0, "density", @position), 2)
```

### Points that follow a volume (Run Over: Points)

Points with a volume on Input 1: move along its "velocity" grid, or stick to an SDF's surface.

```toast
v: vec3 = sample_grid(1, "velocity", @position)
@position += v * param("step", 0.05)
```

### Select with code, then use the selection in other nodes

```toast
output("top", @normal.z > param("threshold", 0.7))
```

Connect **top** to the Selection of Extrude Mesh, Delete Geometry or Set Material.

### Mark where faces touch each point (Run Over: Faces)

```toast faces
@touched: int
for p in face_points(0, @index, 16):
    set_point_attr(p, "touched", @index)
```

## Shader node

The shader editor has a Toast node too (Add > Toast > Toast): code that runs for **every shading
point** and gives values to the material, for patterns and textures drawn with code. It doesn't
make shaders: connect its outputs to Principled BSDF, Bump, Mix and the other nodes.

```toast shader
scale = param("scale", 5.0)
p = @generated * scale
cell = voronoi(p)
n = fbm(p, 4.0)
c = lerp(cell.color, vec3(n), 0.5)
output("color", vec4(c.x, c.y, c.z, 1.0))
output("height", n)
```

- `param()` makes an input socket. Unlike the geometry node, it can be linked to other nodes,
  so its value can change from point to point.
- `output(name, value)` makes an output socket: float, int, bool, vec3 (Vector) or vec4 (Color).
- `@` attributes are what the shading point has, read-only:

| Attribute | Type | Same as |
| --- | --- | --- |
| `@position` `@normal` `@true_normal` `@incoming` `@parametric` `@backfacing` | vec3 (backfacing: float) | Geometry node |
| `@generated` `@uv` `@object` `@camera` `@window` `@reflection` | vec3 | Texture Coordinate node |
| `@color` | vec3 | Color Attribute node (the active one) |
| `@time` `@frame` | float | Scene Time node |
| any other `@name` | float, or as declared: `@name: vec3`, `@name: vec4` | Attribute node (Fac, Vector, Color with its alpha) |

- Math, vectors, `noise`, `signed_noise`, `fbm`, `voronoi`, `hash01`, `random`, `curl_noise`,
  `def` helpers, libraries, `if`, `while` and `for i in range(...)` work as in the geometry node.
  `noise`, `fbm` and `voronoi` give exactly the values of the Noise and Voronoi Texture nodes.
- There is no geometry at a shading point: geometry reads and changes, lists, quat and mat4 are
  geometry node only.
- The node feeds Bump like any texture: the code runs again at the offset positions.
- **EEVEE, the viewport, and Cycles on the CPU.** In Cycles the code is compiled to native
  code like the geometry node's (the built-in compiler, the first time a render uses it). On a
  GPU device (Metal, CUDA, ...) its outputs are zero for now, and with Open Shading Language on
  they are their default values. Cycles colors have no alpha: a vec4 parameter's alpha is 1 and
  an output's alpha is dropped.
- Like the geometry node, the code only runs in trusted files (Auto Run Python Scripts).

## Errors

Errors name the line, and spellings from earlier Toast versions tell you the new name:

| You wrote | Toast says |
| --- | --- |
| `x = 1` then `x = 1.5` | `can't assign a float to 'x', which is a int (its type was fixed on line 1)` |
| `@P` | `@P is now @position (Toast uses Blender's attribute names)` |
| `ch("amp", 1)` | `ch() is now param()` |
| `f@height = 1` | `type prefixes are not used in Toast, annotate the type instead` |

## Limits

- The shader node works in EEVEE, the viewport and Cycles on the CPU, not yet on Cycles GPUs.
- Meshes, point clouds, curves, instances, Grease Pencil and volumes (grids of float, int, bool
  and vec3; Run Over Voxels and `sample_grid()`).
- Run Over Instances changes the instances of the top-level geometry only, like Blender's
  instance nodes; geometry inside instances runs with the other modes.
- Linux and macOS (the node loads compiled code with `dlopen`).
- No compiler needs to be installed on Linux: the fork has a built-in one. Elsewhere, or with
  the add-on's Compiler preference set to External, Toast uses g++ or clang++ (`TOAST_CXX` picks
  one).
