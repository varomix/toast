# Toast guide

Toast lets you write the inside of a geometry node in Python syntax. The code runs once per point
(or face, edge, corner), on every CPU core, compiled to native code: no Python runs while Blender
evaluates the node tree.

```toast
amp = param("amp", 0.2)
n = noise(@position * param("freq", 4.0))
@position += @normal * n * amp
@height: float = n
```

## Setting up

1. Use the Blender build from the `toast` fork branch, and enable the **Toast** add-on
   (Preferences > Add-ons).
2. Allow **Auto Run Python Scripts** (Preferences > Save & Load), or trust the file. Toast code
   in a `.blend` runs native code, so it follows the same rule as Python drivers.
3. In a Geometry Nodes tree, add **Toast > Toast**. In the sidebar (N) > Node > Toast, press
   **New** to create a text with starter code, and **Edit Code** to show it in a Text Editor.

The node recompiles a moment after you stop typing (about 0.4 s with g++). Don't press Run
Script in the Text Editor: Toast code isn't plain Python. Errors show on the node header and in
the Toast panel, with the line number.

## The node

| Socket | Meaning |
| --- | --- |
| Geometry | The geometry the code runs on and writes to (input 0). |
| Selection | Elements to run on (a boolean field). Others are left unchanged. |
| Input 1 | Another geometry the code can read: `point_attr(1, ...)`, `ray_cast(1, ...)`. |
| *params* | One socket per `param()` in the code. |

**Run Over** sets what the code runs once for:

| Run Over | Runs once per | `@` attributes live on |
| --- | --- | --- |
| Points | point | points |
| Faces | face | faces (`@position` reads the face center) |
| Edges | edge | edges |
| Face Corners | face corner | corners |
| Geometry | once for the whole geometry | (none) |

Every element runs independently and in parallel. Writing `@name` changes the current element
only; to change other elements, use `set_point_attr()` and the topology functions below, which
are applied after the run in element order. The result never depends on the number of threads.

## Language

Toast is a statically typed subset of Python.

- **Types:** `float`, `int`, `bool`, `vec2`, `vec3`, `vec4`. A variable's type is fixed by its
  first assignment; annotate to choose one: `x: float = 1`. Tuples of 2 to 4 numbers are
  vectors: `(0, 0, 1)`.
- **Vectors:** `v.x`, `v.xy`, `v.zyx`, `v[0]`; `v.x = 1` sets one component. `+ - * /` work
  between vectors of the same size and between a vector and a number.
- **Control flow:** `if/elif/else`, `while`, `for i in range(...)`, `break`, `continue`,
  `x if cond else y`, `and/or/not`, comparison chains like `0 < x < 1`. `return` at the top level
  ends the current element.
- **Numbers:** `%`, `//` and `/` follow Python (`7 / 2` is `3.5`). Integer division by zero gives
  0 instead of crashing Blender.
- **Not supported:** classes, lists and dicts, strings (except as names), recursion, `*args`,
  imports other than `math` and Toast libraries.

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
| `@index` | int | Index of the current element (read-only). |
| `@count` | int | Number of elements in the Run Over domain (read-only). |
| `@frame`, `@time` | float | Scene frame and time in seconds (read-only). |

Any other name is your own attribute. Its type comes from an annotation, or from its first
assigned value, or is `float`:

```toast
@height: float = 0.5          # declared and written
@flag: bool                   # declared only
@offset = (0, 0, 1)           # a vec3, from the value
@flag = @height > 0.3
```

Writing an attribute that doesn't exist creates it on the Run Over domain.

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

### Reading geometry

`input` is a constant: 0 for the node's Geometry, 1 for Input 1.

| Function | Returns |
| --- | --- |
| `point_attr(input, "name", index)` | An attribute of a point. Annotate for its type: `v: vec3 = point_attr(1, "velocity", j)`. |
| `face_attr(input, "name", index)` | An attribute of a face. |
| `point_count(input)`, `face_count(input)` | Element counts. |
| `nearest_point(input, position, radius)` | The closest point within `radius`, or -1. |
| `corner_point(input, corner)`, `corner_face(input, corner)` | The point and face of a face corner, or -1. |
| `ray_cast(input, origin, direction, max_distance)` | A hit: `.hit`, `.position`, `.normal`, `.distance`, `.face` (-1 without a hit). |
| `closest_point(input, position)` | The closest point on the surface, as a hit. |
| `sample_nearest_surface(input, "name", position)` | A point attribute interpolated at the closest surface point. |

Loops over related elements take a constant maximum count:

| Loop | Visits |
| --- | --- |
| `for j in nearby_points(input, position, radius, max_count):` | Points within `radius`, closest first. |
| `for p in face_points(input, face, max_count):` | The points of a face, in order. |
| `for f in point_faces(input, point, max_count):` | The faces using a point. |
| `for q in point_neighbors(input, point, max_count):` | Points sharing an edge with a point. |

Reading input 0 with these functions sees the geometry as it was before the run, even for
attributes the code is writing.

### Changing geometry

| Function | Does |
| --- | --- |
| `add_point(position)` | Adds a point and returns it, for `add_edge`/`add_face` in the same run. |
| `add_edge(a, b)` | Adds an edge. |
| `add_face((a, b, c, ...))` | Adds a face through 3 or more points. |
| `remove_point(p)` | Removes a point and the edges and faces using it. |
| `remove_face(f)` | Removes a face and keeps its points (like Delete Geometry, Only Faces). |
| `set_point_attr(index, "name", value)`, `set_face_attr(...)` | Writes another element's attribute. |

These are applied after the run in element order: new elements are numbered by the element that
created them, and when several elements write the same attribute, the highest index wins.

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

### Mark where faces touch each point (Run Over: Faces)

```toast faces
@touched: int
for p in face_points(0, @index, 16):
    set_point_attr(p, "touched", @index)
```

## Errors

Errors name the line, and spellings from earlier Toast versions tell you the new name:

| You wrote | Toast says |
| --- | --- |
| `x = 1` then `x = 1.5` | `can't assign a float to 'x', which is a int (its type was fixed on line 1)` |
| `@P` | `@P is now @position (Toast uses Blender's attribute names)` |
| `ch("amp", 1)` | `ch() is now param()` |
| `f@height = 1` | `type prefixes are not used in Toast, annotate the type instead` |

## Limits

- Points, faces, edges and corners of meshes; points of point clouds. Curves and instances are
  not supported yet.
- Linux and macOS (the node loads compiled code with `dlopen`).
- A C++ compiler (g++ or clang++) must be installed; set `TOAST_CXX` to choose one.
