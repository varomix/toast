# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Toast frontend tests. Run from the repo root: python3 -m unittest discover -s tests -v

Set TOAST_BLENDER to a Blender binary (default ~/blender-git/build_linux_5.3/bin/blender) for
the bit-exact comparison with Blender's Noise Texture and Random Value nodes.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ref  # noqa: E402
import toast  # noqa: E402
from toast.harness import Geometry, HarnessError, run  # noqa: E402
from toast.sugar import desugar  # noqa: E402

THREADS = (1, 4, 28)
BLENDER = os.environ.get(
    "TOAST_BLENDER", str(Path.home() / "blender-git/build_linux_5.3/bin/blender")
)

_tmp = None


def setUpModule():
    global _tmp
    _tmp = tempfile.TemporaryDirectory(prefix="toast-test-cache-")
    os.environ["TOAST_CACHE_DIR"] = _tmp.name


def tearDownModule():
    _tmp.cleanup()


def sphere_points(n, seed=0):
    rng = np.random.default_rng(seed)
    P = rng.normal(size=(n, 3)).astype(np.float32)
    N = P / np.linalg.norm(P, axis=1, keepdims=True)
    return Geometry({"position": P, "normal": N.astype(np.float32)})


def run_all_threads(test, kernel, inputs, grain=7, **kw):
    """Run at 1, 4 and 28 threads and assert the outputs are identical. Returns one output."""
    outs = [run(kernel, inputs, threads=t, grain=grain, **kw) for t in THREADS]
    first = outs[0]
    for o in outs[1:]:
        test.assertEqual(sorted(first.points), sorted(o.points))
        for name in first.points:
            np.testing.assert_array_equal(first.points[name], o.points[name], err_msg=name)
        test.assertEqual(first.prims, o.prims)
    return first


# ---------------------------------------------------------------------------- sugar


class TestSugar(unittest.TestCase):
    def test_rewrites(self):
        self.assertEqual(desugar("@position += @normal * x\n"), "_A.position += _A.normal * x\n")
        self.assertEqual(desugar("@h: float = 1\n"), "_A.h: float = 1\n")
        self.assertEqual(desugar("@vel = (1, @a.x, 0)\n"), "_A.vel = (1, _A.a.x, 0)\n")
        self.assertEqual(desugar("x = '@position'  # @position\n"), "x = '@position'  # @position\n")

    def test_line_numbers_survive(self):
        src = "a = 1\n\nb = @position\n@normal = (0, 0, 1)\n"
        self.assertEqual(desugar(src).count("\n"), src.count("\n"))

    def test_errors(self):
        for src, msg in (
            ("x = a @ b\n", "matrix multiplication"),
            ("x = v@position\n", "type prefixes are not used in Toast"),
            ("x = @ position\n", "followed directly"),
        ):
            with self.assertRaises(toast.ToastError) as cm:
                desugar(src)
            self.assertIn(msg, str(cm.exception))
            self.assertEqual(cm.exception.line, 1)


# ---------------------------------------------------------------------------- errors


class TestErrors(unittest.TestCase):
    CASES = [
        ("x = 1\nx = 1.5\n", 2, "can't assign a float to 'x', which is a int"),
        ("y = x + 1\nx = 2\n", 1, "'x' is used before it is assigned"),
        ("y = zz\n", 1, "name 'zz' is not defined"),
        ("import os\n", 1, "only 'import math'"),
        ("a = (1, 2) < (3, 4)\n", 1, "no vector comparisons"),
        ("@index = 3\n", 1, "@index is read-only"),
        ("@opinput1_position = (0, 0, 0)\n", 1, "read other inputs with point_attr"),
        ("x = @position + (1, 2)\n", 1, "sizes differ"),
        ("n = 4\nfor j in nearby_points(1, @position, 0.1, n):\n    pass\n", 2, "maximum count must be a constant"),
        ("x = nearby_points(1, @position, 0.1, 4)\n", 1, "only be used as the iterable of a for loop"),
        ("\n\nbreak\n", 3, "'break' outside a loop"),
        ("a = param('a', 1)\nb = param('a', 1.5)\n", 2, "first used with a int default"),
        ("x = @position\n@position = 1\n", 2, "@position: expected vec3, got int"),
        ("@foo = 1\n@foo = 2.0\n", 2, "used both as int and as float"),
        ("s@name = 1\n", 1, "type prefixes are not used in Toast"),
        ("@P = (0, 0, 0)\n", 1, "@P is now @position"),
        ("i = @ptnum\n", 1, "@ptnum is now @index"),
        ("x = ch('a', 1.0)\n", 1, "ch() is now param()"),
        ("x = point(0, 'position', 0)\n", 1, "point() is now point_attr()"),
        ("for j in nearpoints(0, @position, 1.0, 4):\n    pass\n", 1, "is now nearby_points()"),
        ("add_face((0, 1))\n", 1, "use add_edge(a, b) for 2"),
        ("@h: vec3 = (1, 1, 1)\n@h: float = 1.0\n", 2, "@h is declared both as vec3 and as float"),
        ("@position: float = 1.0\n", 1, "@position is a vec3, it can't be declared as float"),
        ("p = add_point(@position)\nx = p + 1\n", 2, "can't be used with a pointref"),
        ("x = 'hello'\n", 1, "strings are only supported"),
        ("if @position:\n    pass\n", 1, "vec3 can't be used as a condition"),
        ("noise = 1\n", 1, "builtin function"),
        ("x = undefined_fn(1)\n", 1, "not a Toast builtin"),
        ("x = (1,\n", 1, "syntax error"),
        ("return 1\n", 1, "return with a value"),
        ("a, b = 1, 2\n", 1, "tuple unpacking"),
        ("x = 2 ** 40\n", 1, None),  # fine: ipow wraps like int32
        ("def f(x):\n    return f(x)\ny = f(1)\n", 2, "recursion is not supported"),
        ("def f(x):\n    return @position\ny = f(1)\n", 2, "@position can't be used inside def f()"),
        ("def f(j):\n    return point_attr(0, 'position', j)\ny = f(1)\n", 2, "point_attr() can't be used inside"),
        ("def f(x):\n    if x > 0:\n        return 1\n    return 0.5\ny = f(1)\n", 4,
         "returns a int on line 3 and a float here"),
        ("def f(x):\n    return x\ny = f(1, 2)\n", 3, "f() takes 1 arguments, got 2"),
        ("def f(x):\n    return x\ny = f(x=1)\n", 3, "keyword arguments"),
        ("if True:\n    def g():\n        pass\n", 2, "must be defined at the top level"),
        ("def noise(x):\n    return x\n", 1, "is a Toast builtin"),
        ("def f(x=1):\n    return x\n", 1, "only plain positional arguments"),
        ("def f(x):\n    return x\ny = f\n", 3, "is a function, call it with ()"),
    ]

    def test_messages_and_lines(self):
        for src, line, msg in self.CASES:
            with self.subTest(src=src):
                if msg is None:
                    toast.compile_source(src)
                    continue
                with self.assertRaises(toast.ToastError) as cm:
                    toast.compile_source(src)
                self.assertIn(msg, cm.exception.message)
                self.assertEqual(cm.exception.line, line)

    def test_run_over(self):
        with self.assertRaises(toast.ToastError):
            toast.compile_source("pass\n", run_over="volumes")

    def test_domain_errors(self):
        for src, run_over, msg in (
            ("@position = (0, 0, 0)\n", "geometry", "Run Over Geometry runs once for the whole geometry"),
            ("x = @index\n", "geometry", "@index is not available with Run Over Geometry"),
        ):
            with self.subTest(src=src, run_over=run_over):
                with self.assertRaises(toast.ToastError) as cm:
                    toast.compile_source(src, run_over=run_over)
                self.assertIn(msg, cm.exception.message)

    def test_domains_in_signature(self):
        sig = toast.compile_source(
            "@color = (1, 0, 0)\n@x = point_attr(0, 'position', 0).x + face_attr(1, 'w', 0)\n", run_over="faces"
        ).signature
        self.assertEqual([(a["name"], a["input"], a["domain"]) for a in sig["attrs"]],
                         [("color", 0, "face"), ("position", 0, "point"), ("w", 1, "face"), ("x", 0, "face")])  # fmt: skip


# ---------------------------------------------------------------------------- design examples

NOISE_DISPLACE = """# Run Over: Points
amp  = param("amp", 0.2)
freq = param("freq", 4.0)

n = noise(@position * freq)
@position += @normal * n * amp
@height = n          # new float attribute
"""

CULL_AND_GROW = """# Run Over: Points
seed = param("seed", 7)
keep = param("keep", 0.6)

if hash01(@index + seed * 1000) > keep:
    remove_point(@index)
else:
    # grow a short line along the normal
    top = add_point(@position + @normal * param("len", 0.3))
    add_edge(@index, top)
"""

SMOOTH = """# Run Over: Points    Input 1: rest copy of the mesh
radius = param("radius", 0.1)
acc = vec3(0, 0, 0)
count = 0

for j in nearby_points(1, @position, radius, 16):
    acc += point_attr(1, "position", j)
    count += 1

if count > 0:
    @position = lerp(@position, acc / count, param("strength", 0.5))
"""


class TestDesignExamples(unittest.TestCase):
    def test_noise_displace(self):
        k = toast.build(NOISE_DISPLACE)
        sig = k.signature
        self.assertEqual([(p["name"], p["type"]) for p in sig["params"]],
                         [("amp", "float"), ("freq", "float")])  # fmt: skip
        self.assertEqual([(a["name"], a["access"]) for a in sig["attrs"]],
                         [("position", "rw"), ("normal", "r"), ("height", "w")])  # fmt: skip
        geo = sphere_points(5000)
        out = run_all_threads(self, k, [geo], params={"amp": 0.3})
        h = out.points["height"]
        self.assertTrue(np.all((h >= 0) & (h <= 1)))
        self.assertGreater(h.std(), 0.01)
        expect = geo.points["position"] + geo.points["normal"] * h[:, None] * np.float32(0.3)
        np.testing.assert_array_equal(out.points["position"], expect.astype(np.float32))

    def test_cull_and_grow(self):
        k = toast.build(CULL_AND_GROW)
        self.assertEqual([(p["name"], p["type"], p["default"]) for p in k.signature["params"]],
                         [("seed", "int", 7), ("keep", "float", 0.6), ("len", "float", 0.3)])  # fmt: skip
        geo = sphere_points(1000)
        out = run_all_threads(self, k, [geo])
        P, N = geo.points["position"], geo.points["normal"]
        removed = [i for i in range(1000) if ref.rand_int(np.int32(i + 7 * 1000)) > np.float32(0.6)]
        kept = [i for i in range(1000) if i not in set(removed)]
        self.assertTrue(200 < len(removed) < 600)
        # Kept originals first (in order), then one new point per kept original (in order).
        self.assertEqual(out.npoints, 2 * len(kept))
        np.testing.assert_array_equal(out.points["position"][: len(kept)], P[kept])
        tops = (P[kept] + N[kept] * np.float32(0.3)).astype(np.float32)
        np.testing.assert_array_equal(out.points["position"][len(kept):], tops)
        np.testing.assert_array_equal(out.points["normal"][len(kept):], 0)
        self.assertEqual(out.prims, [[k_, len(kept) + k_] for k_ in range(len(kept))])

    def test_smooth_from_neighbours(self):
        k = toast.build(SMOOTH)
        self.assertEqual(k.signature["uses"]["nearpoints_inputs"], [1])
        geo = sphere_points(400, seed=3)
        geo.points["position"] *= np.float32(0.3)
        rest = geo.copy()
        out = run_all_threads(self, k, [geo, rest], grain=16)
        P = rest.points["position"].astype(np.float64)
        expect = np.empty_like(P)
        for i in range(len(P)):
            d2 = ((P - P[i]) ** 2).sum(axis=1)
            idx = np.nonzero(d2 <= 0.1**2)[0]
            idx = idx[np.lexsort((idx, d2[idx]))][:16]
            avg = P[idx].mean(axis=0)
            expect[i] = P[i] + (avg - P[i]) * 0.5
        np.testing.assert_allclose(out.points["position"], expect, atol=1e-5)
        self.assertGreater(np.abs(out.points["position"] - geo.points["position"]).max(), 1e-3)


# ---------------------------------------------------------------------------- semantics


class TestSemantics(unittest.TestCase):
    def run_kernel(self, src, n=101, **kw):
        k = toast.build(src)
        geo = Geometry({"position": np.zeros((n, 3), np.float32)})
        return run_all_threads(self, k, [geo], **kw)

    def test_python_arithmetic(self):
        out = self.run_kernel(
            "x = @index - 50\n"
            "@mod = x % 7\n"
            "@fdiv = x // 7\n"
            "@div = x / 4\n"
            "@fmod = (x * 0.5) % 3\n"
            "@ffdiv = (x * 0.5) // 3\n"
            "@pw = 3 ** 4 + x * 0\n"
            "@neg = -x % -7\n"
            "@zero = x % 0 + x // 0\n"
        )
        for i in range(101):
            x = i - 50
            self.assertEqual(out.points["mod"][i], x % 7)
            self.assertEqual(out.points["fdiv"][i], x // 7)
            self.assertAlmostEqual(out.points["div"][i], x / 4, places=6)
            self.assertAlmostEqual(out.points["fmod"][i], (x * 0.5) % 3, places=5)
            self.assertAlmostEqual(out.points["ffdiv"][i], (x * 0.5) // 3, places=5)
            self.assertEqual(out.points["pw"][i], 81)
            self.assertEqual(out.points["neg"][i], -x % -7)
            self.assertEqual(out.points["zero"][i], 0)  # no crash on division by zero

    def test_control_flow(self):
        out = self.run_kernel(
            "total = 0\n"
            "for j in range(@index):\n"
            "    if j % 3 == 0:\n"
            "        continue\n"
            "    if j > 20:\n"
            "        break\n"
            "    total += j\n"
            "w = 0\n"
            "while w * w < @index:\n"
            "    w += 1\n"
            "down = 0\n"
            "for j in range(10, 0, -3):\n"
            "    down = down * 10 + j\n"
            "@total = total\n"
            "@w = w\n"
            "@down = down\n"
            "@last = j\n"
            "if @index > 90:\n"
            "    return\n"
            "@after = 1 if @index % 2 == 0 else 2\n"
        )
        for i in range(101):
            total = 0
            for j in range(i):
                if j % 3 == 0:
                    continue
                if j > 20:
                    break
                total += j
            w = 0
            while w * w < i:
                w += 1
            self.assertEqual(out.points["total"][i], total)
            self.assertEqual(out.points["w"][i], w)
            self.assertEqual(out.points["down"][i], 10741)
            self.assertEqual(out.points["last"][i], 1)
            self.assertEqual(out.points["after"][i], 0 if i > 90 else (1 if i % 2 == 0 else 2))

    def test_vectors_and_math(self):
        out = self.run_kernel(
            "import math\n"
            "v = vec3(@index, 2, 3)\n"
            "v.y = 5\n"
            "@position = v.zyx + (1, 1, 1)\n"
            "@n = normalize(v) * 2\n"
            "@len = length(v)\n"
            "@d = dot(v, (1, 0, 0)) + v[2]\n"
            "@c = cross((1, 0, 0), (0, 1, 0))\n"
            "@cl = clamp(@index * 0.1, 1, 5)\n"
            "@icl = clamp(@index, 10, 20)\n"
            "@s = math.sin(math.pi / 2) + abs(-2) + math.floor(2.7)\n"
            "@fit = map_range(@index, 0, 100, -1, 1)\n"
            "@flag = @index > 50 and not @index > 80\n"
            "@uv = v.xy\n"
            "@q = vec4(1)\n",
            n=101,
        )
        i = np.arange(101, dtype=np.float32)
        v = np.stack([i, np.full_like(i, 5), np.full_like(i, 3)], axis=1)
        np.testing.assert_allclose(out.points["position"], v[:, ::-1] + 1)
        np.testing.assert_allclose(out.points["n"], 2 * v / np.linalg.norm(v, axis=1)[:, None], rtol=1e-6)
        np.testing.assert_allclose(out.points["len"], np.linalg.norm(v, axis=1), rtol=1e-6)
        np.testing.assert_allclose(out.points["d"], i + 3)
        np.testing.assert_array_equal(out.points["c"], np.tile([0, 0, 1], (101, 1)))
        np.testing.assert_allclose(out.points["cl"], np.clip(i * np.float32(0.1), 1, 5))
        np.testing.assert_array_equal(out.points["icl"], np.clip(i, 10, 20))
        np.testing.assert_allclose(out.points["s"], 1 + 2 + 2)
        np.testing.assert_allclose(out.points["fit"], i / 50 - 1, atol=1e-6)
        np.testing.assert_array_equal(out.points["flag"], (i > 50) & ~(i > 80))
        np.testing.assert_array_equal(out.points["uv"], v[:, :2])
        np.testing.assert_array_equal(out.points["q"], 1)

    def test_def_helpers(self):
        out = self.run_kernel(
            "def sq(x):\n"
            "    return x * x\n"
            "\n"
            "def clampi(v, lo, hi):\n"
            "    if v < lo:\n"
            "        return lo\n"
            "    if v > hi:\n"
            "        return hi\n"
            "    return v\n"
            "\n"
            "def lift(p: vec3, amt):\n"
            "    return p + (0, 0, amt * param('k', 2.0))\n"
            "\n"
            "def mark(x):\n"
            "    for j in range(3):\n"
            "        if j == x:\n"
            "            return j * 10\n"
            "    return -1\n"
            "\n"
            "def first_even_above(n):\n"
            "    k = n + 1\n"
            "    while k % 2 != 0:\n"
            "        k += 1\n"
            "    return k\n"
            "\n"
            "@a = sq(@index * 0.5)\n"
            "@b = sq(@index)\n"
            "@d = clampi(@index, 10, 20)\n"
            "@position = lift(@position, 0.5)\n"
            "@m = mark(@index % 4)\n"
            "@e = first_even_above(sq(@index))\n"
            "@c = sq(sq(2.0))\n",
            n=31,
        )
        for i in range(31):
            self.assertEqual(out.points["a"][i], np.float32(i * 0.5) * np.float32(i * 0.5))
            self.assertEqual(out.points["b"][i], i * i)
            self.assertEqual(out.points["d"][i], min(max(i, 10), 20))
            self.assertEqual(out.points["m"][i], (i % 4) * 10 if i % 4 < 3 else -1)
            self.assertEqual(out.points["e"][i], i * i + 1 + (i * i + 1) % 2)
        np.testing.assert_array_equal(out.points["position"], [[0, 0, 1.0]] * 31)
        np.testing.assert_array_equal(out.points["c"], 16.0)

    def test_params(self):
        src = (
            "@a = param('f', 1.5)\n@b = param('i', 3)\n@c = param('b', True)\n"
            "@d = param('v', (1, -2, 3.5))\n@e = param('q', (0.0, 1.0, 2.0, 3.0), min=0, max=10)\n"
        )
        k = toast.build(src)
        offsets = {p["name"]: (p["type"], p["offset"]) for p in k.signature["params"]}
        self.assertEqual(offsets, {"f": ("float", 0), "i": ("int", 4), "b": ("bool", 8),
                                   "v": ("vec3", 12), "q": ("vec4", 24)})  # fmt: skip
        self.assertEqual(k.signature["params_size"], 40)
        geo = Geometry({"position": np.zeros((3, 3), np.float32)})
        out = run(k, [geo])
        np.testing.assert_array_equal(out.points["a"], 1.5)
        np.testing.assert_array_equal(out.points["b"], 3)
        np.testing.assert_array_equal(out.points["c"], True)
        np.testing.assert_array_equal(out.points["d"], [[1, -2, 3.5]] * 3)
        np.testing.assert_array_equal(out.points["e"], [[0, 1, 2, 3]] * 3)
        out = run(k, [geo], params={"f": -1, "i": -7, "b": False, "v": (9, 8, 7)})
        np.testing.assert_array_equal(out.points["a"], -1)
        np.testing.assert_array_equal(out.points["b"], -7)
        np.testing.assert_array_equal(out.points["c"], False)
        np.testing.assert_array_equal(out.points["d"], [[9, 8, 7]] * 3)
        with self.assertRaises(HarnessError):
            run(k, [geo], params={"nope": 1})

    def test_snapshot_reads(self):
        # Every point reads its neighbour's *input* position, even though P is being written.
        src = "@position = point_attr(0, 'position', (@index + 1) % @count) + (0, 0, 1)\n"
        k = toast.build(src)
        self.assertEqual([(a["name"], a["snapshot"]) for a in k.signature["attrs"]],
                         [("position", False), ("position", True)])  # fmt: skip
        geo = sphere_points(50)
        out = run_all_threads(self, k, [geo])
        expect = np.roll(geo.points["position"], -1, axis=0) + np.float32([0, 0, 1])
        np.testing.assert_array_equal(out.points["position"], expect)

    def test_out_of_range_reads_are_zero(self):
        out = self.run_kernel("@q = point_attr(0, 'position', 1000000) + point_attr(0, 'position', -1) + (1, 1, 1)\n", n=4)
        np.testing.assert_array_equal(out.points["q"], 1)

    def test_selection(self):
        k = toast.build("@w = 1.0\n@position = (1, 2, 3)\n")
        geo = Geometry({"position": np.zeros((10, 3), np.float32), "w": np.zeros(10, np.float32)})
        sel = [1, 4, 5, 9]
        out = run(k, [geo], selection=sel, threads=4, grain=1)
        np.testing.assert_array_equal(np.nonzero(out.points["w"])[0], sel)
        np.testing.assert_array_equal(out.points["position"][sel], [[1, 2, 3]] * 4)
        self.assertTrue(np.all(np.delete(out.points["position"], sel, axis=0) == 0))

    def test_missing_attribute(self):
        k = toast.build("@w = @missing\n")
        with self.assertRaises(HarnessError):
            run(k, [Geometry({"position": np.zeros((2, 3), np.float32)})])


# ---------------------------------------------------------------------------- hashes / cache


class TestRunOver(unittest.TestCase):
    def grid(self):
        # Two quads sharing an edge, plus a triangle.
        P = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0], [3, 0, 0]],
                     np.float32)  # fmt: skip
        prims = [[0, 1, 4, 3], [1, 2, 5, 4], [2, 6, 5]]
        return Geometry({"position": P}, prims, {"w": np.array([10, 20, 30], np.float32)})

    def test_faces(self):
        src = (
            "c = vec3(0, 0, 0)\n"
            "n = 0\n"
            "for pt in face_points(0, @index, 8):\n"
            "    c += point_attr(0, 'position', pt)\n"
            "    n += 1\n"
            "@center = c / n\n"
            "@corners = n\n"
            "@w2 = face_attr(0, 'w', @index) * 2 + @count + point_count(0)\n"
            "if @index == 1:\n"
            "    remove_face(@index)\n"
        )
        k = toast.build(src, run_over="faces")
        geo = self.grid()
        out = run_all_threads(self, k, [geo], grain=1)
        self.assertEqual(out.prims, [[0, 1, 4, 3], [2, 6, 5]])  # face 1 removed
        self.assertEqual(out.npoints, 7)  # its points stay
        np.testing.assert_allclose(out.prim_attrs["center"], [[0.5, 0.5, 0], [7 / 3, 1 / 3, 0]])
        np.testing.assert_array_equal(out.prim_attrs["corners"], [4, 3])
        np.testing.assert_array_equal(out.prim_attrs["w2"], [20 + 3 + 7, 60 + 3 + 7])
        np.testing.assert_array_equal(out.prim_attrs["w"], [10, 30])

    def test_set_point_attr_on_added_points(self):
        # Values land on the new points, the last write wins, and removals renumber them.
        src = (
            "@w: float\n"
            "@k: int\n"
            "prev = add_point((0, 0, 0))\n"
            "set_point_attr(prev, 'w', 0.5)\n"
            "for k in range(1, 4):\n"
            "    p = add_point((k, 0, 0))\n"
            "    add_edge(prev, p)\n"
            "    set_point_attr(p, 'w', k * 1.5)\n"
            "    set_point_attr(p, 'w', k * 2.5)\n"
            "    set_point_attr(p, 'k', k)\n"
            "    prev = p\n"
            "set_point_attr(0, 'w', 9.0)\n"
            "set_point_attr(point_count(0) + 1, 'k', 7)\n"  # the second new point, by index
            "remove_point(0)\n"
        )
        k = toast.build(src, run_over="geometry")
        geo = Geometry({"position": np.array([[5, 5, 5], [6, 6, 6]], np.float32)})
        out = run(k, [geo])
        np.testing.assert_array_equal(out.points["position"][:, 0], [6, 0, 1, 2, 3])
        np.testing.assert_array_equal(out.points["w"], [0, 0.5, 2.5, 5, 7.5])
        np.testing.assert_array_equal(out.points["k"], [0, 0, 7, 2, 3])
        self.assertEqual(out.prims, [[1, 2], [2, 3], [3, 4]])

    def test_geometry_builds_geometry(self):
        src = (
            "count = param('count', 4)\n"
            "prev = add_point((0, 0, 0))\n"
            "for k in range(1, count):\n"
            "    p = add_point((k, 0, 0))\n"
            "    add_edge(prev, p)\n"
            "    prev = p\n"
        )
        k = toast.build(src, run_over="geometry")
        out = run(k, [Geometry({"position": np.zeros((0, 3), np.float32)})], params={"count": 5})
        np.testing.assert_array_equal(out.points["position"], [[k, 0, 0] for k in range(5)])
        self.assertEqual(out.prims, [[0, 1], [1, 2], [2, 3], [3, 4]])


class TestTopologyQueries(unittest.TestCase):
    def grid(self):
        P = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [0, 1, 0], [1, 1, 0], [2, 1, 0], [3, 0, 0]],
                     np.float32)  # fmt: skip
        return Geometry({"position": P}, [[0, 1, 4, 3], [1, 2, 5, 4], [2, 6, 5]])

    def expected_topology(self, geo):
        faces = [[] for _ in range(geo.npoints)]
        nb = [set() for _ in range(geo.npoints)]
        for f, prim in enumerate(geo.prims):
            for k, p in enumerate(prim):
                faces[p].append(f)
                q = prim[(k + 1) % len(prim)]
                nb[p].add(q)
                nb[q].add(p)
        return faces, [sorted(x) for x in nb]

    def test_neighbors_and_point_faces(self):
        src = (
            "s = vec3(0, 0, 0)\n"
            "n = 0\n"
            "for q in point_neighbors(0, @index, 16):\n"
            "    s += point_attr(0, 'position', q)\n"
            "    n += 1\n"
            "@avg = s / max(n, 1)\n"
            "@nn = n\n"
            "k = 0\n"
            "first = -1\n"
            "for f in point_faces(0, @index, 8):\n"
            "    if k == 0:\n"
            "        first = f\n"
            "    k += 1\n"
            "@nf = k\n"
            "@first = first\n"
        )
        geo = self.grid()
        out = run_all_threads(self, toast.build(src), [geo], grain=2)
        faces, nb = self.expected_topology(geo)
        P = geo.points["position"]
        for i in range(geo.npoints):
            self.assertEqual(out.points["nn"][i], len(nb[i]))
            self.assertEqual(out.points["nf"][i], len(faces[i]))
            self.assertEqual(out.points["first"][i], faces[i][0])
            np.testing.assert_allclose(out.points["avg"][i], P[nb[i]].mean(axis=0), rtol=1e-6)

    def test_corner_queries(self):
        src = "@cp = corner_point(0, @index)\n@cf = corner_face(0, @index)\n"
        geo = self.grid()
        geo.points["position"] = np.zeros((11, 3), np.float32)  # 11 points = 11 corners
        geo.prims = [[0, 1, 4, 3], [1, 2, 5, 4], [2, 6, 5]]
        out = run(toast.build(src), [geo])
        corners = [(p, f) for f, prim in enumerate(geo.prims) for p in prim]
        np.testing.assert_array_equal(out.points["cp"], [c[0] for c in corners])
        np.testing.assert_array_equal(out.points["cf"], [c[1] for c in corners])
        out = run(toast.build("@x = corner_point(0, 99)\n"), [geo])
        np.testing.assert_array_equal(out.points["x"], -1)

    def test_set_point_attr_last_face_wins(self):
        src = (
            "@touched: int\n"
            "for p in face_points(0, @index, 8):\n"
            "    set_point_attr(p, 'touched', @index)\n"
            "    set_point_attr(p, 'mark', vec3(@index, 0, 1))\n"
        )
        geo = self.grid()
        out = run_all_threads(self, toast.build(src, run_over="faces"), [geo], grain=1)
        faces, _ = self.expected_topology(geo)
        for i in range(geo.npoints):
            self.assertEqual(out.points["touched"][i], faces[i][-1])
            np.testing.assert_array_equal(out.points["mark"][i], [faces[i][-1], 0, 1])

    def test_set_attr_errors(self):
        for src, msg in (
            ("set_point_attr(0, 'index', 1)\n", "is read-only"),
            ("@a: int\nset_point_attr(0, 'a', vec3(1, 2, 3))\n", "expected int, got vec3"),
            ("set_face_attr(add_point((0, 0, 0)), 'a', 1.0)\n", "not a point added"),
        ):
            with self.subTest(src=src):
                with self.assertRaises(toast.ToastError) as cm:
                    toast.compile_source(src)
                self.assertIn(msg, cm.exception.message)


class TestHashes(unittest.TestCase):
    def test_random_and_rand_match_reference(self):
        k = toast.build("@r = random(@index, 42)\n@ri = hash01(@index)\n@rf = hash01(@index * 0.37)\n")
        out = run(k, [Geometry({"position": np.zeros((300, 3), np.float32)})])
        for i in range(300):
            self.assertEqual(out.points["r"][i], ref.random(i, 42))
            self.assertEqual(out.points["ri"][i], ref.rand_int(i))
            self.assertEqual(out.points["rf"][i], ref.rand_float(np.float32(i) * np.float32(0.37)))


class TestLibraries(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.old = os.environ.get("TOAST_LIB_PATH")
        os.environ["TOAST_LIB_PATH"] = self.dir.name
        self.write("mathx", "def sq(x):\n    return x * x\n")
        self.write("shapes", '"""Shapes."""\nfrom toast_lib.mathx import sq\n\n'
                   "def sphere(p: vec3, r):\n    return length(p) - r\n\n"
                   "def ring(x):\n    return sq(x) * 2\n")
        Path(self.dir.name, "deep").mkdir()
        self.write("deep/inner", "def one():\n    return 1\n")

    def tearDown(self):
        if self.old is None:
            del os.environ["TOAST_LIB_PATH"]
        else:
            os.environ["TOAST_LIB_PATH"] = self.old
        self.dir.cleanup()

    def write(self, name, text):
        Path(self.dir.name, name + ".py").write_text(text)

    def test_imports(self):
        src = (
            "from toast_lib.shapes import sphere\n"
            "import toast_lib.shapes as shapes\n"
            "import toast_lib.deep.inner\n"
            "@d = sphere(@position, 1.0)\n"
            "@r = shapes.ring(@index)\n"
            "@o = toast_lib.deep.inner.one()\n"
        )
        P = np.array([[2, 0, 0], [0, 0.5, 0]], np.float32)
        out = run(toast.build(src), [Geometry({"position": P})])
        np.testing.assert_array_equal(out.points["d"], [1.0, -0.5])
        np.testing.assert_array_equal(out.points["r"], [0, 2])
        np.testing.assert_array_equal(out.points["o"], [1, 1])

    def test_library_edit_rebuilds(self):
        src = "from toast_lib.mathx import sq\n@a = sq(3.0)\n"
        k1 = toast.build(src)
        self.write("mathx", "def sq(x):\n    return x * x * x\n")
        k2 = toast.build(src)
        self.assertNotEqual(k1.key, k2.key)
        out = run(k2, [Geometry({"position": np.zeros((1, 3), np.float32)})])
        self.assertEqual(out.points["a"][0], 27.0)

    def test_errors(self):
        self.write("bad", "def f(x):\n    y = 1\n    return @position\n")
        self.write("stmt", "x = 1\n")
        for src, line, source, msg in (
            ("from toast_lib.nope import f\n", 1, None, "can't find library toast_lib.nope"),
            ("x = 1\nfrom toast_lib.mathx import cube\n", 2, None, "has no def cube()"),
            ("from toast_lib.bad import f\n@a = f(1)\n", 3, "toast_lib.bad", "@position can't be used"),
            ("import toast_lib.stmt\n", 1, "toast_lib.stmt", "may only contain def helpers"),
            ("import toast_lib.mathx as m\n@a = q.sq(1)\n", 2, None, "'q' is not an imported"),
        ):
            with self.subTest(src=src):
                with self.assertRaises(toast.ToastError) as cm:
                    toast.build(src)
                self.assertIn(msg, cm.exception.message)
                self.assertEqual((cm.exception.line, cm.exception.source), (line, source))


class TestCache(unittest.TestCase):
    def test_cache_hit_and_miss(self):
        src = "@x = 1.0\n"
        a = toast.build(src)
        b = toast.build(src)
        self.assertTrue(b.cached)
        self.assertEqual(a.key, b.key)
        c = toast.build(src + "@y = 2.0\n")
        self.assertNotEqual(a.key, c.key)
        self.assertTrue(a.so_path.exists() and a.cpp_path.exists())


# ---------------------------------------------------------------------------- Blender exactness


@unittest.skipUnless(Path(BLENDER).exists(), f"Blender not found at {BLENDER}")
class TestMatchesBlender(unittest.TestCase):
    """Bit-exact comparison with Blender's Noise Texture and Random Value nodes."""

    def test_noise_fbm_random(self):
        rng = np.random.default_rng(7)
        P = rng.uniform(-3, 3, size=(2000, 3)).astype(np.float32)
        P[:10] = np.round(P[:10])  # integer lattice points
        P[10:20] *= np.float32(400000.0)  # beyond the 100000 wrap and the 1e6 correction
        cases = [
            {"name": "n0", "kind": "noise", "scale": 1.0, "detail": 0.0, "roughness": 0.5, "lacunarity": 2.0},
            {"name": "n4", "kind": "noise", "scale": 4.0, "detail": 0.0, "roughness": 0.5, "lacunarity": 2.0},
            {"name": "fbm", "kind": "noise", "scale": 2.5, "detail": 2.0, "roughness": 0.5, "lacunarity": 2.0},
            {"name": "fbm2", "kind": "noise", "scale": 1.3, "detail": 3.7, "roughness": 0.65, "lacunarity": 2.2},
            {"name": "r0", "kind": "random", "seed": 0},
            {"name": "r42", "kind": "random", "seed": 42},
            {"name": "vd", "kind": "voronoi", "scale": 3.0, "randomness": 1.0, "output": "Distance"},
            {"name": "vd5", "kind": "voronoi", "scale": 1.7, "randomness": 0.5, "output": "Distance"},
            {"name": "vc", "kind": "voronoi", "scale": 3.0, "randomness": 1.0, "output": "Color", "comps": 3},
            {"name": "vp", "kind": "voronoi", "scale": 1.0, "randomness": 0.8, "output": "Position", "comps": 3},
        ]  # fmt: skip
        with tempfile.TemporaryDirectory() as d:
            inp, outp = Path(d) / "in.json", Path(d) / "out.json"
            inp.write_text(json.dumps({"position": P.tolist(), "cases": cases}))
            script = Path(__file__).resolve().parent / "blender_noise_ref.py"
            proc = subprocess.run(
                [BLENDER, "-b", "--factory-startup", "--python-exit-code", "1",
                 "--python", str(script), "--", str(inp), str(outp)],
                capture_output=True, text=True, timeout=300,
            )  # fmt: skip
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-3000:])
            bl = json.loads(outp.read_text())

        def f32(bits):
            return np.array(bits, dtype=np.uint32).view(np.float32)

        P_bl = f32(bl["position"]).reshape(-1, 3)
        np.testing.assert_array_equal(P_bl, P)

        src = (
            "@n0 = noise(@position)\n"
            "@n4 = noise(@position * 4.0)\n"
            "@fbm = fbm(@position * 2.5)\n"
            "@fbm2 = fbm(@position * 1.3, 3.7, 0.65, 2.2)\n"
            "@r0 = random(@index, 0)\n"
            "@r42 = random(@index, 42)\n"
            "@vd = voronoi(@position * 3.0).distance\n"
            "@vd5 = voronoi(@position * 1.7, 0.5).distance\n"
            "@vc = voronoi(@position * 3.0).color\n"
            "@vp = voronoi(@position, randomness=0.8).position\n"
        )
        out = run(toast.build(src), [Geometry({"position": P})], threads=8)
        for c in cases:
            with self.subTest(case=c["name"]):
                mine = np.ascontiguousarray(out.points[c["name"]], np.float32).reshape(-1)
                theirs = f32(bl[c["name"]])
                diff = np.nonzero(mine.view(np.uint32) != theirs.view(np.uint32))[0]
                self.assertEqual(
                    len(diff), 0,
                    f"{len(diff)} values differ, first at {diff[:5]}: "
                    f"toast {mine[diff[:5]]} blender {theirs[diff[:5]]}",
                )  # fmt: skip


def _blender_has_toast_node():
    if not Path(BLENDER).exists():
        return False
    proc = subprocess.run(
        [BLENDER, "-b", "--factory-startup", "--python-expr",
         "import bpy,sys; t=bpy.data.node_groups.new('x','GeometryNodeTree'); "
         "t.nodes.new('GeometryNodeToast'); print('TOAST_NODE_OK')"],
        capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    return "TOAST_NODE_OK" in proc.stdout



class TestLists(unittest.TestCase):
    def run_points(self, code, n=4):
        pos = np.zeros((n, 3), np.float32)
        return run(toast.build(code), [Geometry({"position": pos})]).points

    def test_fill_index_and_loop(self):
        out = self.run_points("a = [0] * 5\nfor k in range(5):\n    a[k] = k * k\nt = 0\n"
                              "for x in a:\n    t += x\n@t: int = t + len(a)\n")  # fmt: skip
        np.testing.assert_array_equal(out["t"], [35] * 4)

    def test_literal_types_and_negative_index(self):
        out = self.run_points("a = [1, 2.5, 3]\nb: list[int] = [4, 5]\n"
                              "@x: float = a[-1] + a[1] + float(b[-2])\n")  # fmt: skip
        np.testing.assert_array_equal(out["x"], [9.5] * 4)

    def test_out_of_range_is_safe(self):
        out = self.run_points("a = [1.0] * 3\na[@index + 1] = 7.0\n@x: float = a[@index + 5] + a[1]\n")
        np.testing.assert_array_equal(out["x"], [7, 1, 1, 1])

    def test_lists_of_vectors_and_helpers(self):
        code = ("def total(v):\n    t = vec3(0, 0, 0)\n    for x in v:\n        t += x\n    return t\n"
                "vs = [(1, 0, 0), (0, 2, 0), (0, 0, 3)]\n@s: vec3 = total(vs)\n")  # fmt: skip
        out = self.run_points(code)
        np.testing.assert_array_equal(out["s"], [[1, 2, 3]] * 4)

    def test_list_as_vector_where_a_vector_is_expected(self):
        out = self.run_points("@position = [0, 0, 1]\n")
        np.testing.assert_array_equal(out["position"], [[0, 0, 1]] * 4)

    def test_errors(self):
        for src, msg in (
            ("a = []\n", "an empty list has no size"),
            ("a = [0] * 5000\n", "between 1 and 4096"),
            ("a = [1, 2]\na.append(3)\n", "fixed size"),
            ("a = [1, (0, 0, 0)]\n", "same type"),
            ("a = [1, 2]\na = [1, 2, 3]\n", "can't assign"),
            ("a = [1.0] * 3\n@x = a\n", "can't hold"),
            ("a = [1.0] * 3\nb = a + a\n", "can't be used with"),
        ):  # fmt: skip
            with self.subTest(src=src), self.assertRaises(toast.ToastError) as cm:
                toast.compile_source(src)
            self.assertIn(msg, cm.exception.message)


class TestRotations(unittest.TestCase):
    def one(self, code):
        out = run(toast.build(code), [Geometry({"position": np.zeros((1, 3), np.float32)})])
        return out.points

    def test_rotate_compose_inverse(self):
        out = self.one(
            "q = quat_axis_angle((0, 0, 1), math.pi / 2)\n@r: vec3 = rotate(q, (1, 0, 0))\n"
            "m = mat4_compose((1, 2, 3), q, 2.0)\n@p: vec3 = transform_point(m, (1, 0, 0))\n"
            "@b: vec3 = transform_point(inverse(m), @p)\n@d: vec3 = transform_direction(m, (1, 0, 0))\n"
            "@t: vec3 = m.translation\n@s: vec3 = m.scale\n"
        )  # fmt: skip
        np.testing.assert_allclose(out["r"][0], [0, 1, 0], atol=1e-6)
        np.testing.assert_allclose(out["p"][0], [1, 4, 3], atol=1e-6)
        np.testing.assert_allclose(out["b"][0], [1, 0, 0], atol=1e-6)
        np.testing.assert_allclose(out["d"][0], [0, 2, 0], atol=1e-6)
        np.testing.assert_allclose(out["t"][0], [1, 2, 3])
        np.testing.assert_allclose(out["s"][0], [2, 2, 2], atol=1e-6)

    def test_euler_round_trip_and_slerp(self):
        out = self.one(
            "e = (0.3, -0.4, 1.2)\n@e: vec3 = to_euler(quat_euler(e))\n"
            "@m: vec3 = to_euler(mat4_rotation(quat_euler(e)).rotation)\n"
            "@h: quat = slerp(quat(), quat_axis_angle((0, 0, 1), 1.0), 0.5)\n"
            "@w: float = (quat_axis_angle((1, 0, 0), 0.4) * inverse(quat_axis_angle((1, 0, 0), 0.4))).w\n"
            "@between: vec3 = rotate(quat_between((1, 0, 0), (0, -1, 0)), (1, 0, 0))\n"
            "@opposite: vec3 = rotate(quat_between((1, 0, 0), (-1, 0, 0)), (1, 0, 0))\n"
        )  # fmt: skip
        np.testing.assert_allclose(out["e"][0], [0.3, -0.4, 1.2], atol=1e-6)
        np.testing.assert_allclose(out["m"][0], [0.3, -0.4, 1.2], atol=1e-6)
        np.testing.assert_allclose(out["h"][0], [np.cos(0.25), 0, 0, np.sin(0.25)], atol=1e-6)
        np.testing.assert_allclose(out["w"][0], 1.0, atol=1e-6)
        np.testing.assert_allclose(out["between"][0], [0, -1, 0], atol=1e-6)
        np.testing.assert_allclose(out["opposite"][0], [-1, 0, 0], atol=1e-6)

    def test_mat4_layout_is_column_major(self):
        out = self.one("@m: mat4 = mat4_translation((1, 2, 3))\n")
        np.testing.assert_array_equal(out["m"][0][3], [1, 2, 3, 1])

    def test_singular_inverse_is_zero(self):
        out = self.one("@m: mat4 = inverse(mat4_scale(0.0))\n")
        np.testing.assert_array_equal(out["m"][0], np.zeros((4, 4)))

    def test_curl_noise_is_divergence_free(self):
        pts = np.random.default_rng(1).random((64, 3)).astype(np.float32) * 4
        e = 1e-2
        offsets = [(e, 0, 0), (-e, 0, 0), (0, e, 0), (0, -e, 0), (0, 0, e), (0, 0, -e)]
        geo = Geometry({"position": np.concatenate([pts + np.float32(o) for o in offsets])})
        c = run(toast.build("@c: vec3 = curl_noise(@position)\n"), [geo]).points["c"].reshape(6, 64, 3)
        div = (c[0, :, 0] - c[1, :, 0] + c[2, :, 1] - c[3, :, 1] + c[4, :, 2] - c[5, :, 2]) / (2 * e)
        scale = np.abs(c).mean()
        self.assertLess(np.abs(div).mean(), 0.05 * scale / e * e + 0.05)

    def test_errors(self):
        for src, msg in (
            ("q = quat() * (1, 0, 0)\n", "rotate(q, v)"),
            ("m = mat4() * (1, 0, 0)\n", "transform_point"),
            ("q = quat(1, 0, 0)\n", "4 numbers"),
            ("m = mat4()\nm.translation = (1, 0, 0)\n", "read-only"),
            ("m = mat4()\nx = m.foo\n", "has no property"),
            ("q = quat() + quat()\n", "can only be multiplied"),
        ):  # fmt: skip
            with self.subTest(src=src), self.assertRaises(toast.ToastError) as cm:
                toast.compile_source(src)
            self.assertIn(msg, cm.exception.message)


class TestCurvesAndInstances(unittest.TestCase):
    def test_mode_errors(self):
        for src, run_over, msg in (
            ("add_point((0, 0, 0))\n", "instances", "doesn't work with Run Over Instances"),
            ("add_curve((0, 1))\n", "faces", "doesn't work with Run Over Faces"),
            ("extend_curve(0, (0, 0, 0))\n", "instances", "doesn't work with Run Over Instances"),
            ("x = [0.0] * 4\nadd_curve(x, 2)\n", "geometry", "list of point numbers"),
            ("remove_point(0)\n", "instances", "use remove_instance()"),
            ("x = point_attr(0, 'a', 0)\n", "instances", "only instances"),
            ("remove_face(0)\n", "curves", "no faces"),
            ("remove_instance(0)\n", "points", "doesn't work with Run Over Points"),
            ("remove_curve(0)\n", "faces", "doesn't work with Run Over Faces"),
            ("for p in curve_points(0, 0, 8):\n    pass\n", "faces", "no curves"),
        ):  # fmt: skip
            with self.subTest(src=src), self.assertRaises(toast.ToastError) as cm:
                toast.compile_source(src, run_over=run_over)
            self.assertIn(msg, cm.exception.message)

    def test_curve_attr_and_input1(self):
        curves = Geometry({"position": np.zeros((5, 3), np.float32)}, curves=[[0, 1], [2, 3, 4]],
                          curve_attrs={"radius_scale": np.array([2.0, 3.0], np.float32)})  # fmt: skip
        code = ("@k: float = curve_attr(1, 'radius_scale', @index % 2)\n"
                "n = 0\nfor p in curve_points(1, 1, 8):\n    n += 1\n@n: int = n + 10 * curve_count(1)\n")  # fmt: skip
        out = run(toast.build(code), [Geometry({"position": np.zeros((3, 3), np.float32)}), curves])
        np.testing.assert_array_equal(out.points["k"], [2, 3, 2])
        np.testing.assert_array_equal(out.points["n"], [23] * 3)

    def test_extend_curves(self):
        # Each curve grows two points from its tip; the tip's other attributes are copied.
        curves = Geometry({"position": np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 1, 0)],
                                                np.float32),
                           "w": np.array([1, 2, 3, 4, 5], np.float32)}, curves=[[0, 1], [2, 3, 4]])  # fmt: skip
        out = run_all_threads(self, toast.build(GROW_CODE, run_over="curves"), [curves], grain=1)
        self.assertEqual(out.curves, [[0, 1, 2, 3], [4, 5, 6, 7, 8]])
        np.testing.assert_array_equal(out.points["position"][[2, 3, 7, 8]],
                                      [(1, 0, 0.5), (1, 0, 1), (2, 1, 0.5), (2, 1, 1)])  # fmt: skip
        np.testing.assert_array_equal(out.points["w"], [1, 2, 2, 7, 3, 4, 5, 5, 7])

    def test_build_curves_from_nothing(self):
        out = run(toast.build(BUILD_CURVES_CODE, run_over="geometry"), [Geometry()])
        self.assertEqual([len(c) for c in out.curves], [4, 5, 6, 2])
        np.testing.assert_array_equal(out.points["position"][-2:], [(9, 9, 9), (9, 9, 10)])
        np.testing.assert_array_equal(out.points["position"][4], (0, 1, 0))

    def test_edit_curves(self):
        curves = Geometry({"position": np.arange(15, dtype=np.float32).reshape(5, 3)},
                          curves=[[0, 1], [2, 3, 4]],
                          curve_attrs={"k": np.array([10, 20], np.int32)})  # fmt: skip
        out = run(toast.build(EDIT_CURVES_CODE, run_over="geometry"), [curves])
        # Curve 0 removed; curve 1 loses its first point and gains a tip; a new curve follows.
        self.assertEqual(out.curves, [[0, 1, 2], [3, 4]])
        np.testing.assert_array_equal(out.points["position"],
                                      [(9, 10, 11), (12, 13, 14), (4, 2, 0), (5, 0, 0), (5, 1, 0)])  # fmt: skip
        np.testing.assert_array_equal(out.curve_attrs["k"], [20, 0])

    def test_curve_errors(self):
        empty = Geometry(curves=[])
        for code, msg in (("add_point((0, 0, 0))\n", "must be in one"),
                          ("a = add_point((0, 0, 0))\nadd_curve((a,))\nadd_curve((a,))\n", "must be in one"),
                          ("add_curve((0,))\n", "does not exist")):  # fmt: skip
            with self.subTest(code=code), self.assertRaises(HarnessError) as cm:
                run(toast.build(code, run_over="geometry"), [empty])
            self.assertIn(msg, str(cm.exception))

    def test_instance_position_and_transform(self):
        t = np.tile(np.eye(4, dtype=np.float32), (2, 1, 1))
        code = ("@transform = mat4_compose((5, 5, 5), quat(), 3.0)\n"
                "@position = (float(@index), 0, 0)\n")  # fmt: skip
        out = run(toast.build(code, run_over="instances"), [Geometry(instance_attrs={"transform": t})])
        m = out.instance_attrs["transform"]
        np.testing.assert_array_equal(m[:, 3, :3], [[0, 0, 0], [1, 0, 0]])  # @position wins
        np.testing.assert_array_equal(m[:, 0, 0], [3, 3])


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderNode(unittest.TestCase):
    """The fork's GeometryNodeToast gives the same bits as the harness, at any thread count."""

    CASES = [
        {"name": "displace", "code": NOISE_DISPLACE, "params": {"amp": 0.3}, "attrs": ["height"]},
        {"name": "cull", "code": CULL_AND_GROW},
        {"name": "smooth", "code": SMOOTH, "input1": True, "params": {"radius": 0.15}},
    ]

    @classmethod
    def setUpClass(cls):
        cls.results = {}
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_node_check.py"
        with tempfile.TemporaryDirectory() as d:
            cases = Path(d) / "cases.json"
            cases.write_text(json.dumps(cls.CASES))
            # All threads, one thread, and the external compiler instead of the built-in one.
            for run_name, threads, backend in (("0", "0", ""), ("1", "1", ""),
                                               ("external", "0", "external")):  # fmt: skip
                out = Path(d) / f"out{run_name}.json"
                proc = subprocess.run(
                    [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "-t", threads,
                     "--python-exit-code", "1", "--python", str(script), "--",
                     str(repo), str(cases), str(out)],
                    capture_output=True, text=True, timeout=600,
                    env={**os.environ, "TOAST_CACHE_DIR": os.environ["TOAST_CACHE_DIR"],
                         "TOAST_BACKEND": backend},
                )  # fmt: skip
                if proc.returncode != 0:
                    raise AssertionError(proc.stdout[-4000:] + proc.stderr[-4000:])
                cls.results[run_name] = json.loads(out.read_text())

    def bl(self, case):
        r = self.results["0"][case]
        self.assertEqual(r["error"], "", r["error"])
        return r

    def input_geometry(self):
        inp = self.results["0"]["input"]
        f32 = lambda b: np.array(b, dtype=np.uint32).view(np.float32).reshape(-1, 3)  # noqa: E731
        return Geometry({"position": f32(inp["P"]), "normal": f32(inp["N"])}, [list(f) for f in inp["faces"]])

    def assert_bits(self, blender_bits, values, name):
        mine = np.ascontiguousarray(values, dtype=np.float32).reshape(-1).view(np.uint32)
        theirs = np.array(blender_bits, dtype=np.uint32)
        self.assertEqual(mine.shape, theirs.shape, name)
        diff = np.nonzero(mine != theirs)[0]
        self.assertEqual(len(diff), 0, f"{name}: {len(diff)} values differ, first {diff[:5]}")

    def test_thread_count_does_not_matter(self):
        self.assertEqual(self.results["0"], self.results["1"])

    def test_builtin_and_external_compilers_agree(self):
        builtin, external = self.results["0"], self.results["external"]
        if not builtin["displace"]["kernel_path"].endswith(".cpp"):
            self.skipTest("this Blender has no built-in compiler (only Linux builds have one)")
        for case in ("displace", "cull", "smooth"):
            self.assertTrue(builtin[case]["kernel_path"].endswith(".cpp"), "built-in compiler used")
            self.assertTrue(external[case]["kernel_path"].endswith(".so"), "external compiler used")
        strip = lambda r: {k: {f: v for f, v in c.items() if f != "kernel_path"} if isinstance(c, dict) else c
                           for k, c in r.items()}  # noqa: E731
        self.assertEqual(strip(builtin), strip(external))

    def test_sockets_from_signature(self):
        self.assertEqual(self.bl("displace")["sockets"],
                         ["Geometry", "Selection", "Input 1", "p_amp", "p_freq"])

    def test_noise_displace(self):
        r = self.bl("displace")
        out = run(toast.build(NOISE_DISPLACE), [self.input_geometry()], params={"amp": 0.3})
        self.assert_bits(r["P"], out.points["position"], "P")
        self.assert_bits(r["attrs"]["height"], out.points["height"], "height")

    def test_cull_and_grow(self):
        r = self.bl("cull")
        out = run(toast.build(CULL_AND_GROW), [self.input_geometry()])
        self.assert_bits(r["P"], out.points["position"], "P")
        faces = [p for p in out.prims if len(p) > 2]
        lines = [tuple(p) for p in out.prims if len(p) == 2]
        self.assertEqual(r["faces"], faces)
        face_edges = {tuple(sorted((f[k], f[(k + 1) % len(f)]))) for f in faces for k in range(len(f))}
        # As Blender's Delete Geometry on points: edges whose two points survive are kept, even
        # when their face was removed.
        remap = {old: new for new, old in enumerate(self._kept_indices())}
        old_edges = {tuple(sorted((remap[a], remap[b])))
                     for a, b in self.results["0"]["input"]["edges"] if a in remap and b in remap}
        self.assertEqual({tuple(sorted(e)) for e in r["edges"]},
                         face_edges | {tuple(sorted(e)) for e in lines} | old_edges)  # fmt: skip

    def _kept_indices(self):
        n_in = len(self.results["0"]["input"]["P"]) // 3
        return [i for i in range(n_in) if not ref.rand_int(np.int32(i + 7 * 1000)) > np.float32(0.6)]

    def test_smooth_with_input1(self):
        r = self.bl("smooth")
        geo = self.input_geometry()
        out = run(toast.build(SMOOTH), [geo, geo.copy()], params={"radius": 0.15})
        self.assert_bits(r["P"], out.points["position"], "P")


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderColor(unittest.TestCase):
    """@color is the mesh's active color attribute (created as "Color" if there is none)."""

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_color_check.py"
        proc = subprocess.run(
            [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code", "1",
             "--python", str(script), "--", str(repo)],
            capture_output=True, text=True, timeout=300,
        )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        if proc.returncode != 0 or not line:
            raise AssertionError(proc.stdout[-3000:] + proc.stderr[-3000:])
        cls.r = json.loads(line[0][len("RESULT "):])

    def test_creates_active_color(self):
        r = self.r["create"]
        self.assertEqual(r["active"], "Color")
        color = r["attrs"]["Color"]
        self.assertEqual((color["type"], color["domain"]), ("FLOAT_COLOR", "POINT"))
        for c in color["values"]:
            self.assertEqual(c[1:], [0.5, 1.0, 1.0])
            self.assertIn(c[0], (-1.0, 1.0))

    def test_writes_existing_active_color_keeping_alpha(self):
        r = self.r["existing"]
        self.assertEqual(r["active"], "Col")
        self.assertNotIn("Color", r["attrs"])
        for c in r["attrs"]["Col"]["values"]:
            np.testing.assert_allclose(c, [0.4, 0.3, 0.2, 0.3], rtol=1e-6)

    def test_byte_corner_color_reads_but_does_not_write(self):
        np.testing.assert_allclose(self.r["byte_read"]["attrs"]["r"]["values"], 2.0)
        self.assertEqual(self.r["byte_read"]["modifier_warnings"], [])
        w = self.r["byte_write"]
        self.assertTrue(any("isn't a float color on the domain" in m for m in w["modifier_warnings"]))
        for c in w["attrs"]["Bytes"]["values"]:
            self.assertEqual(c, [1.0, 1.0, 1.0, 1.0])


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderLibraries(unittest.TestCase):
    """toast_lib libraries from Text data-blocks; editing one recompiles nodes using it."""

    def test_text_library(self):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_lib_check.py"
        proc = subprocess.run(
            [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code", "1",
             "--python", str(script), "--", str(repo)],
            capture_output=True, text=True, timeout=300,
        )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        self.assertTrue(line, proc.stdout[-3000:] + proc.stderr[-3000:])
        r = json.loads(line[0][len("RESULT "):])
        self.assertEqual(r["first_error"], "")
        self.assertEqual(r["first"], [1.0, 4.0, 9.0, 16.0])
        self.assertFalse(r["immediate"])  # debounced
        self.assertTrue(r["after_debounce"])
        self.assertEqual(r["second"], [1.0, 8.0, 27.0, 64.0])
        self.assertIn("can't find library toast_lib.mathx", r["missing_error"])


FACES_CODE = (
    "c = vec3(0, 0, 0)\n"
    "n = 0\n"
    "for pt in face_points(0, @index, 8):\n"
    "    c += point_attr(0, 'position', pt)\n"
    "    n += 1\n"
    "@center = c / n\n"
    "@noisy = noise(@position * 3.0) + @count + point_count(0)\n"
    "if @index % 3 == 1:\n"
    "    remove_face(@index)\n"
)


NEIGHBORS_CODE = (
    "s = vec3(0, 0, 0)\n"
    "n = 0\n"
    "for q in point_neighbors(0, @index, 16):\n"
    "    s += point_attr(0, 'position', q)\n"
    "    n += 1\n"
    "@avg = s / max(n, 1)\n"
    "k = 0\n"
    "for f in point_faces(0, @index, 8):\n"
    "    k += 1\n"
    "@nf = k\n"
)
NEW_POINT_SETS_CODE = (
    "@w: float\n"
    "@tag: vec3\n"
    "base = add_point((0, 0, 9))\n"
    "set_point_attr(base, 'w', 0.25)\n"
    "for k in range(4):\n"
    "    p = add_point((k, 0, 9))\n"
    "    add_edge(base, p)\n"
    "    set_point_attr(p, 'w', k + 1.5)\n"
    "    set_point_attr(p, 'tag', (k, 2 * k, 3))\n"
    "set_point_attr(0, 'w', 7.0)\n"
    "set_point_attr(point_count(0) + 2, 'w', 42.0)\n"  # the third new point, by index
    "remove_point(1)\n"
)
SETS_CODE = (
    "@touched: int\n"
    "for p in face_points(0, @index, 8):\n"
    "    set_point_attr(p, 'touched', @index)\n"
)


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderRunOver(unittest.TestCase):
    """Faces, edges, corners and geometry in the fork. Faces match the harness bit for bit."""

    CASES = [
        {"name": "faces", "run_over": "FACES", "code": FACES_CODE},
        {"name": "edges", "run_over": "EDGES",
         "code": "@mz = @position.x * 10 + @position.y\n@e = @index + 1000 * @count\n"},
        {"name": "corners", "run_over": "CORNERS",
         "code": "@vi = @index + 1000 * @count\n@nz = @normal.z\n"},
        {"name": "geometry", "run_over": "GEOMETRY",
         "code": "for k in range(3):\n    p = add_point((k, 5, 0))\n    add_edge(0, p)\n"},
        {"name": "geometry_attr", "run_over": "GEOMETRY", "code": "@position = (0, 0, 0)\n"},
        {"name": "geometry_new_attrs", "run_over": "GEOMETRY", "code": NEW_POINT_SETS_CODE},
        {"name": "geometry_from_nothing", "run_over": "GEOMETRY", "empty": True,
         "code": NEW_POINT_SETS_CODE},
        {"name": "type_warning", "run_over": "CORNERS", "code": "@u = @UVMap\n"},
        {"name": "type_warning_input", "run_over": "FACES",
         "code": "@u = point_attr(0, 'UVMap', 0)\n"},
        {"name": "type_annotated", "run_over": "CORNERS",
         "code": "@UVMap: vec2\n@u = @UVMap.x\n"},
        {"name": "neighbors", "run_over": "POINTS", "code": NEIGHBORS_CODE},
        {"name": "sets", "run_over": "FACES", "code": SETS_CODE},
        {"name": "corner_queries", "run_over": "CORNERS",
         "code": "@cp = corner_point(0, @index)\n@cf = corner_face(0, @index)\n"},
    ]  # fmt: skip

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_domains_check.py"
        with tempfile.TemporaryDirectory() as d:
            cases = Path(d) / "cases.json"
            cases.write_text(json.dumps(cls.CASES))
            proc = subprocess.run(
                [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code",
                 "1", "--python", str(script), "--", str(repo), str(cases)],
                capture_output=True, text=True, timeout=300,
            )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        if proc.returncode != 0 or not line:
            raise AssertionError(proc.stdout[-3000:] + proc.stderr[-3000:])
        cls.r = json.loads(line[0][len("RESULT "):])

    @staticmethod
    def f32(b, comps=1):
        a = np.array(b, dtype=np.uint32).view(np.float32)
        return a.reshape(-1, comps) if comps > 1 else a

    def ok(self, name):
        r = self.r[name]
        self.assertEqual((r["error"], r["warnings"]), ("", []))
        return r

    def test_faces_match_harness(self):
        r = self.ok("faces")
        inp = r["input"]
        geo = Geometry({"position": self.f32(inp["P"], 3)}, inp["faces"])
        out = run(toast.build(FACES_CODE, run_over="faces"), [geo])
        self.assertEqual(r["faces"], out.prims)
        self.assertEqual(r["P"], inp["P"])  # remove_prim keeps points
        for name, comps in (("center", 3), ("noisy", 1)):
            attr = r["attrs"][name]
            self.assertEqual(attr["domain"], "FACE")
            mine = np.ascontiguousarray(out.prim_attrs[name], np.float32).reshape(-1).view(np.uint32)
            self.assertEqual(attr["values"], mine.tolist(), name)

    def test_edges(self):
        r = self.ok("edges")
        P = self.f32(r["P"], 3)
        edges = np.array(r["edges"])
        mid = (P[edges[:, 0]] + P[edges[:, 1]]) / 2
        attr = r["attrs"]["mz"]
        self.assertEqual(attr["domain"], "EDGE")
        np.testing.assert_allclose(self.f32(attr["values"]), mid[:, 0] * 10 + mid[:, 1], atol=1e-5)
        np.testing.assert_array_equal(r["attrs"]["e"]["values"],
                                      np.arange(len(edges)) + 1000 * len(edges))  # fmt: skip

    def test_corners(self):
        r = self.ok("corners")
        n = sum(len(f) for f in r["faces"])
        self.assertEqual(r["attrs"]["vi"]["domain"], "CORNER")
        np.testing.assert_array_equal(r["attrs"]["vi"]["values"], np.arange(n) + 1000 * n)
        np.testing.assert_allclose(self.f32(r["attrs"]["nz"]["values"]), 1.0)

    def test_geometry_builds_into_mesh(self):
        r = self.ok("geometry")
        n_in = len(r["input"]["P"]) // 3
        P = self.f32(r["P"], 3)
        self.assertEqual(len(P), n_in + 3)
        np.testing.assert_array_equal(P[n_in:], [[k, 5, 0] for k in range(3)])
        for k in range(3):
            self.assertIn(sorted([0, n_in + k]), [sorted(e) for e in r["edges"]])
        self.assertEqual(len(r["faces"]), len(r["input"]["faces"]))

    def test_set_point_attr_on_added_points_matches_harness(self):
        r, out = self.harness_run("geometry_new_attrs", NEW_POINT_SETS_CODE, "geometry")
        self.assertEqual(r["P"], np.ascontiguousarray(out.points["position"], np.float32)
                         .reshape(-1).view(np.uint32).tolist())  # fmt: skip
        self.assertEqual(r["faces"], [f for f in out.prims if len(f) > 2])
        blender_edges = {tuple(sorted(e)) for e in r["edges"]}
        for e in (f for f in out.prims if len(f) == 2):
            self.assertIn(tuple(sorted(e)), blender_edges)
        for name in ("w", "tag"):
            mine = np.ascontiguousarray(out.points[name], np.float32).reshape(-1).view(np.uint32)
            self.assertEqual(r["attrs"][name]["values"], mine.tolist(), name)

    def test_set_point_attr_building_from_nothing(self):
        # On an empty mesh, the attributes the code creates survive adding the points.
        r = self.ok("geometry_from_nothing")
        out = run(toast.build(NEW_POINT_SETS_CODE, run_over="geometry"),
                  [Geometry({"position": np.zeros((0, 3), np.float32)})])  # fmt: skip
        self.assertEqual(len(r["P"]), 3 * out.npoints)
        for name in ("w", "tag"):
            mine = np.ascontiguousarray(out.points[name], np.float32).reshape(-1).view(np.uint32)
            self.assertEqual(r["attrs"][name]["values"], mine.tolist(), name)

    def test_reading_an_attribute_as_another_type_warns(self):
        # UVMap is a vec2: read without its type it would silently be a float.
        r = self.r["type_warning"]
        self.assertEqual(r["error"], "")
        self.assertEqual(r["warnings"], ['"UVMap" is a vec2 on the geometry, but the code reads it '
                                         'as a float. Give it its type: @UVMap: vec2'])  # fmt: skip
        r = self.r["type_warning_input"]
        self.assertEqual(len(r["warnings"]), 1)
        self.assertIn("x: vec2 = ..._attr(0, \"UVMap\", ...)", r["warnings"][0])
        self.ok("type_annotated")

    def harness_run(self, name, code, run_over):
        r = self.ok(name)
        inp = r["input"]
        geo = Geometry({"position": self.f32(inp["P"], 3)}, inp["faces"])
        return r, run(toast.build(code, run_over=run_over), [geo])

    def test_neighbors_and_point_faces(self):
        r, out = self.harness_run("neighbors", NEIGHBORS_CODE, "points")
        mine = np.ascontiguousarray(out.points["avg"], np.float32).reshape(-1).view(np.uint32)
        self.assertEqual(r["attrs"]["avg"]["values"], mine.tolist())
        self.assertEqual(r["attrs"]["nf"]["values"], out.points["nf"].tolist())

    def test_set_point_attr(self):
        r, out = self.harness_run("sets", SETS_CODE, "faces")
        self.assertEqual(r["attrs"]["touched"]["domain"], "POINT")
        self.assertEqual(r["attrs"]["touched"]["values"], out.points["touched"].tolist())

    def test_corner_queries(self):
        r = self.ok("corner_queries")
        corners = [(p, f) for f, face in enumerate(r["faces"]) for p in face]
        self.assertEqual(r["attrs"]["cp"]["values"], [c[0] for c in corners])
        self.assertEqual(r["attrs"]["cf"]["values"], [c[1] for c in corners])

    def test_geometry_has_no_attributes(self):
        self.assertIn("Run Over Geometry runs once", self.r["geometry_attr"]["error"])


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderStaleKernel(unittest.TestCase):
    """Regression: a kernel for another ABI used to crash Blender (call after dlclose)."""

    def test_warns_then_recompiles_on_load(self):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_stale_check.py"
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code",
                 "1", "--python", str(script), "--", str(repo), d],
                capture_output=True, text=True, timeout=300,
            )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        self.assertTrue(line, f"exit {proc.returncode}\n" + proc.stdout[-3000:] + proc.stderr[-3000:])
        r = json.loads(line[0][len("RESULT "):])
        warnings, has_attr = r["stale"]
        self.assertTrue(any("Kernel built for Toast ABI 1" in w for w in warnings), warnings)
        self.assertFalse(has_attr)
        self.assertEqual(r["after_load"], [[], True])
        self.assertTrue(r["kernel_is_new"])


SURFACE_CODE = (
    "h = ray_cast(1, @position * 2.0, -@position, 10.0)\n"
    "@hit = h.hit\n"
    "@hpos = h.position\n"
    "@hnormal = h.normal\n"
    "@hdist = h.distance\n"
    "@hface = h.face\n"
    "c = closest_point(1, @position * 1.5)\n"
    "@cpos = c.position\n"
    "@cface = c.face\n"
    "@w2 = sample_nearest_surface(1, 'w', @position * 1.3)\n"
    "miss = ray_cast(1, (5, 5, 5), (1, 0, 0), 100.0)\n"
    "@miss_face = miss.face\n"
)
SNAPSHOT_SURFACE_CODE = "@position = closest_point(0, @position * 1.5).position * 2.0\n"


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderSurface(unittest.TestCase):
    """ray_cast, closest_point and sample_nearest_surface in the fork match the harness."""

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_surface_check.py"
        proc = subprocess.run(
            [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code", "1",
             "--python", str(script), "--", str(repo),
             json.dumps([["FACES", SURFACE_CODE], ["POINTS", SNAPSHOT_SURFACE_CODE]])],
            capture_output=True, text=True, timeout=300,
        )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        if proc.returncode != 0 or not line:
            raise AssertionError(proc.stdout[-3000:] + proc.stderr[-3000:])
        cls.r = json.loads(line[0][len("RESULT "):])
        inp = cls.r["input"]
        f32 = lambda b: np.array(b, dtype=np.uint32).view(np.float32)  # noqa: E731
        cls.geo = Geometry({"position": f32(inp["P"]).reshape(-1, 3), "w": f32(inp["w"])},
                           inp["faces"])  # fmt: skip
        cls.f32 = staticmethod(f32)

    def run_harness(self, code, run_over):
        return run(toast.build(code, run_over=run_over), [self.geo.copy(), self.geo.copy()])

    def test_queries_match_harness(self):
        r = self.r["runs"][0]
        self.assertEqual((r["error"], r["warnings"]), ("", []))
        # Faces mode: queries start from each face's center, so they land inside that face.
        out = self.run_harness(SURFACE_CODE, "faces")
        a, mine = r["attrs"], out.prim_attrs
        self.assertEqual(a["hit"], mine["hit"].astype(int).tolist())
        self.assertTrue(all(a["hit"]))
        self.assertEqual(a["hface"], list(range(len(a["hit"]))))
        self.assertEqual(a["hface"], mine["hface"].tolist())
        self.assertEqual(a["cface"], mine["cface"].tolist())
        self.assertEqual(a["miss_face"], [-1] * len(a["hit"]))
        for name, comps in (("hpos", 3), ("hnormal", 3), ("hdist", 1), ("cpos", 3), ("w2", 1)):
            np.testing.assert_allclose(self.f32(a[name]), mine[name].reshape(-1), atol=2e-5,
                                       err_msg=name)  # fmt: skip

    def test_input0_queries_see_the_surface_before_the_run(self):
        r = self.r["runs"][1]
        self.assertEqual((r["error"], r["warnings"]), ("", []))
        out = self.run_harness(SNAPSHOT_SURFACE_CODE, "points")
        np.testing.assert_allclose(self.f32(r["attrs"]["position"]),
                                   out.points["position"].reshape(-1), atol=2e-5)  # fmt: skip


SELECTION_POINTS_CODE = "@position += (0, 0, 1)\n@mark = @index + 1\n@cnt = @count\n"
SELECTION_FACES_CODE = "remove_face(@index)\n"


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderSelection(unittest.TestCase):
    """The node's Selection input limits the run to selected elements, like the harness mask."""

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_selection_check.py"
        cases = [["POINTS", "POINT", SELECTION_POINTS_CODE], ["FACES", "FACE", SELECTION_FACES_CODE]]
        proc = subprocess.run(
            [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code", "1",
             "--python", str(script), "--", str(repo), json.dumps(cases)],
            capture_output=True, text=True, timeout=300,
        )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        if proc.returncode != 0 or not line:
            raise AssertionError(proc.stdout[-3000:] + proc.stderr[-3000:])
        cls.r = json.loads(line[0][len("RESULT "):])

    def harness(self, r, code, run_over):
        inp = r["input"]
        P = np.array(inp["P"], dtype=np.uint32).view(np.float32).reshape(-1, 3)
        geo = Geometry({"position": P}, inp["faces"])
        sel = np.nonzero(inp["sel"])[0]
        return run(toast.build(code, run_over=run_over), [geo], selection=sel, threads=4, grain=3)

    def test_points(self):
        r = self.r[0]
        self.assertEqual((r["error"], r["warnings"]), ("", []))
        out = self.harness(r, SELECTION_POINTS_CODE, "points")
        mine = np.ascontiguousarray(out.points["position"]).reshape(-1).view(np.uint32).tolist()
        self.assertEqual(r["P"], mine)
        self.assertEqual(r["attrs"]["mark"], out.points["mark"].tolist())
        sel = r["input"]["sel"]
        self.assertTrue(0 < sum(sel) < len(sel))
        self.assertEqual(r["attrs"]["mark"], [i + 1 if s else 0 for i, s in enumerate(sel)])
        self.assertEqual(set(r["attrs"]["cnt"]), {len(sel), 0})  # full count where it ran

    def test_faces(self):
        r = self.r[1]
        self.assertEqual((r["error"], r["warnings"]), ("", []))
        out = self.harness(r, SELECTION_FACES_CODE, "faces")
        kept = [f for f, s in zip(r["input"]["faces"], r["input"]["sel"]) if not s]
        self.assertEqual(r["faces"], kept)
        self.assertEqual(r["faces"], out.prims)



CURVES_POINTS_CODE = "@position.z += @index * 0.5\n@w: float = noise(@position)\n"
GROW_CODE = """tip = 0
for p in curve_points(0, @index, 16):
    tip = p
here: vec3 = point_attr(0, "position", tip)
extend_curve(@index, here + (0, 0, 0.5))
b = extend_curve(@index, here + (0, 0, 1.0))
set_point_attr(b, "w", 7.0)
"""
BUILD_CURVES_CODE = """base = point_count(0)
for k in range(3):
    for j in range(4 + k):
        add_point((float(j), float(k), sin(float(j))))
pts = [0] * 8
start = base
for k in range(3):
    m = 4 + k
    for j in range(m):
        pts[j] = start + j
    add_curve(pts, m)
    start += m
add_curve((add_point((9, 9, 9)), add_point((9, 9, 10))))
"""
EDIT_CURVES_CODE = """a = add_point((5, 0, 0))
b = add_point((5, 1, 0))
add_curve((a, b))
remove_curve(0)
extend_curve(1, (4, 2, 0))
remove_point(2)
"""
GP_DRAW_CODE = "add_curve((add_point((0, 0, 5)), add_point((1, 0, 5))))\n"
CURVES_CODE = """
n = 0
for p in curve_points(0, @index, 64):
    n += 1
@npts: int = n
@nc: int = curve_count(0)
@c: vec3 = @position
if @index == 0:
    remove_curve(@index)
"""
INSTANCES_CODE = """
@position += (0, 0, @index)
@spin: quat = quat_axis_angle((0, 0, 1), @index * 0.3)
@m: mat4 = mat4_translation((1, 2, 3)) * mat4_rotation(@spin)
if @index == 2:
    remove_instance(@index)
"""
OUTPUTS_CODE = """
cell = voronoi(@position * 2)
output("distance", cell.distance)
output("selected", @position.x > 0.2)
if @index % 2 == 1:
    output("n", @index * 10)
output("spin", quat_axis_angle((0, 0, 1), @position.y))
output("unused", 5.0)
output("unused_too", 1.5)
"""
GRID_TYPES_CODE = """
@q: quat = quat_euler(@position)
@m: mat4 = mat4_compose(@position, @q, 2.0)
a = [0.0] * 3
a[@index % 3] = 1.0
@a: vec3 = vec3(a[0], a[1], a[2])
@curl: vec3 = curl_noise(@position)
@e: vec3 = to_euler(@m.rotation)
"""


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderTypes(unittest.TestCase):
    """Curves, instances, quat/mat4 attributes and lists in the fork, bit for bit with the
    harness."""

    CASES = [
        {"name": "curve_points", "input": "curves", "run_over": "POINTS", "code": CURVES_POINTS_CODE},
        {"name": "curves", "input": "curves", "run_over": "CURVES", "code": CURVES_CODE},
        {"name": "curve_remove_points", "input": "curves", "run_over": "POINTS",
         "code": "if @position.x > 1.5:\n    remove_point(@index)\n"},
        {"name": "instances", "input": "instances", "run_over": "INSTANCES", "code": INSTANCES_CODE},
        {"name": "grid_types", "input": "grid", "run_over": "POINTS", "code": GRID_TYPES_CODE},
        {"name": "remove_curve_on_mesh", "input": "grid", "run_over": "POINTS",
         "code": "remove_curve(0)\n"},
        {"name": "grow_curves", "input": "curves_w", "run_over": "CURVES", "code": GROW_CODE},
        {"name": "build_curves", "input": "empty", "run_over": "GEOMETRY", "code": BUILD_CURVES_CODE},
        {"name": "edit_curves", "input": "curves_k", "run_over": "GEOMETRY", "code": EDIT_CURVES_CODE},
        {"name": "add_curve_on_mesh", "input": "grid", "run_over": "POINTS",
         "code": "if @index == 0:\n    add_curve((0, 1))\n"},
        {"name": "gp_points", "input": "gp", "run_over": "POINTS", "code": CURVES_POINTS_CODE},
        {"name": "gp_grow", "input": "gp_w", "run_over": "CURVES", "code": GROW_CODE},
        {"name": "gp_draw", "input": "gp", "run_over": "GEOMETRY", "code": GP_DRAW_CODE},
        {"name": "gp_attrs", "input": "gp", "run_over": "POINTS",
         "code": "@vertex_color: vec4 = (1, 0.5, 0, 1)\n@opacity: float = 0.25\n@radius = 0.03\n"},
        {"name": "lone_point_on_curves", "input": "curves", "run_over": "GEOMETRY",
         "code": "add_point((0, 0, 0))\nadd_curve((0, 1))\n"},
        {"name": "outputs", "input": "grid", "run_over": "POINTS", "code": OUTPUTS_CODE,
         "store": [["distance", "FLOAT", "POINT", "dist"], ["n", "INT", "POINT", "n"],
                   ["spin", "QUATERNION", "POINT", "spin"], ["unused_too", "FLOAT", "POINT", "u"]]},
        {"name": "output_selection", "input": "grid", "run_over": "POINTS", "code": OUTPUTS_CODE,
         "delete": "selected"},
        {"name": "output_faces", "input": "grid", "run_over": "FACES",
         "code": "output('up', @index % 3 == 0)\n", "delete": "up", "delete_domain": "FACE"},
        {"name": "output_with_topology", "input": "grid", "run_over": "POINTS",
         "code": "output('d', float(@index))\nif @index % 2 == 0:\n    remove_point(@index)\n",
         "store": [["d", "FLOAT", "POINT", "d"]]},
    ]  # fmt: skip
    CURVE_POINTS = np.array([(0, 0, 0), (1, 0, 0), (2, 0.5, 0), (0, 1, 0), (1, 1, 0.5), (2, 1, 0),
                             (3, 1.5, 0)], np.float32)  # fmt: skip

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_types_check.py"
        with tempfile.TemporaryDirectory() as d:
            cases = Path(d) / "cases.json"
            cases.write_text(json.dumps(cls.CASES))
            proc = subprocess.run(
                [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code",
                 "1", "--python", str(script), "--", str(repo), str(cases)],
                capture_output=True, text=True, timeout=300,
            )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        if proc.returncode != 0 or not line:
            raise AssertionError(proc.stdout[-3000:] + proc.stderr[-3000:])
        cls.r = json.loads(line[0][len("RESULT "):])

    @staticmethod
    def f32(b, shape=None):
        a = np.array(b, dtype=np.uint32).view(np.float32)
        return a.reshape(shape) if shape else a

    def ok(self, name):
        r = self.r[name]
        self.assertEqual((r["error"], r["warnings"]), ("", []))
        return r

    def curves_input(self):
        return Geometry({"position": self.CURVE_POINTS.copy()}, curves=[[0, 1, 2], [3, 4, 5, 6]])

    def assert_bits(self, got_bits, want):
        want = np.ascontiguousarray(want, dtype=np.float32).reshape(-1)
        np.testing.assert_array_equal(np.array(got_bits, np.uint32), want.view(np.uint32))

    def test_points_of_curves(self):
        r = self.ok("curve_points")
        out = run(toast.build(CURVES_POINTS_CODE), [self.curves_input()])
        self.assertEqual(r["curves"], [3, 4])
        self.assert_bits(r["P"], out.points["position"])
        self.assert_bits(r["attrs"]["w"]["values"], out.points["w"])

    def test_curves(self):
        r = self.ok("curves")
        out = run(toast.build(CURVES_CODE, run_over="curves"), [self.curves_input()])
        self.assertEqual(r["curves"], [len(c) for c in out.curves])
        self.assertEqual(r["curves"], [4])
        self.assert_bits(r["P"], out.points["position"])
        for name in ("npts", "nc"):
            self.assertEqual(r["attrs"][name]["domain"], "CURVE")
            self.assertEqual(r["attrs"][name]["values"], out.curve_attrs[name].tolist())
        self.assert_bits(r["attrs"]["c"]["values"], out.curve_attrs["c"])

    def test_remove_points_of_curves(self):
        r = self.ok("curve_remove_points")
        code = "if @position.x > 1.5:\n    remove_point(@index)\n"
        out = run(toast.build(code), [self.curves_input()])
        self.assertEqual(r["curves"], [len(c) for c in out.curves])
        self.assert_bits(r["P"], out.points["position"])

    def test_instances(self):
        r = self.ok("instances")
        transforms = np.tile(np.eye(4, dtype=np.float32), (4, 1, 1))
        transforms[:, 3, 0] = np.arange(4)
        out = run(toast.build(INSTANCES_CODE, run_over="instances"),
                  [Geometry(instance_attrs={"transform": transforms})])  # fmt: skip
        self.assertEqual(r["count"], 3)
        self.assertEqual(r["attrs"]["spin"]["type"], "QUATERNION")
        self.assertEqual(r["attrs"]["m"]["type"], "FLOAT4X4")
        self.assert_bits(r["attrs"]["instance_transform"]["values"], out.instance_attrs["transform"])
        self.assert_bits(r["attrs"]["spin"]["values"], out.instance_attrs["spin"])
        self.assert_bits(r["attrs"]["m"]["values"], out.instance_attrs["m"])

    def test_quat_mat4_and_lists_on_a_mesh(self):
        r = self.ok("grid_types")
        positions = self.f32(r["P"], (-1, 3))
        out = run(toast.build(GRID_TYPES_CODE), [Geometry({"position": positions.copy()})])
        self.assertEqual(r["attrs"]["q"]["type"], "QUATERNION")
        self.assertEqual(r["attrs"]["m"]["type"], "FLOAT4X4")
        for name in ("q", "m", "a", "curl", "e"):
            self.assert_bits(r["attrs"][name]["values"], out.points[name])

    def test_outputs(self):
        r = self.ok("outputs")
        self.assertEqual(r["outputs"], [["Geometry", "GEOMETRY"], ["distance", "VALUE"],
                                        ["selected", "BOOLEAN"], ["n", "INT"], ["spin", "ROTATION"],
                                        ["unused", "VALUE"], ["unused_too", "VALUE"]])  # fmt: skip
        positions = self.f32(r["P"], (-1, 3))
        out = run(toast.build(OUTPUTS_CODE), [Geometry({"position": positions.copy()})]).points
        self.assert_bits(r["attrs"]["dist"]["values"], out["output.distance"])
        self.assertEqual(r["attrs"]["n"]["values"], out["output.n"].tolist())
        self.assert_bits(r["attrs"]["spin"]["values"], out["output.spin"])
        self.assert_bits(r["attrs"]["u"]["values"], np.full(len(positions), 1.5))
        # Outputs are anonymous: nothing named after them stays on the geometry.
        self.assertFalse({"distance", "selected", "unused"} & set(r["attrs"]))

    def test_output_as_selection(self):
        before = self.f32(self.ok("outputs")["P"], (-1, 3))
        r = self.ok("output_selection")
        np.testing.assert_array_equal(self.f32(r["P"], (-1, 3)), before[before[:, 0] <= 0.2])

    def test_face_output_as_selection(self):
        r = self.ok("output_faces")
        self.assertEqual(len(r["faces"]), 12 - 4)

    def test_output_survives_topology_changes(self):
        r = self.ok("output_with_topology")
        self.assert_bits(r["attrs"]["d"]["values"], np.arange(1, 20, 2))

    def test_remove_curve_needs_curves(self):
        r = self.r["remove_curve_on_mesh"]
        self.assertIn("remove_curve() needs curves", " ".join(r["warnings"]))

    def curves_with(self, name, values):
        geo = self.curves_input()
        if name == "w":
            geo.points["w"] = np.array(values, np.float32)
        else:
            geo.curve_attrs["k"] = np.array(values, np.int32)
        return geo

    def test_grow_curves(self):
        r = self.ok("grow_curves")
        out = run(toast.build(GROW_CODE, run_over="curves"), [self.curves_with("w", range(1, 8))])
        self.assertEqual(r["curves"], [len(c) for c in out.curves])
        self.assert_bits(r["P"], out.points["position"])
        self.assert_bits(r["attrs"]["w"]["values"], out.points["w"])

    def test_build_curves_from_nothing(self):
        r = self.ok("build_curves")
        out = run(toast.build(BUILD_CURVES_CODE, run_over="geometry"), [Geometry()])
        self.assertEqual(r["curves"], [len(c) for c in out.curves])
        self.assert_bits(r["P"], out.points["position"])
        self.assertEqual(r["curve_types"], ["POLY"] * 4)

    def test_edit_curves(self):
        r = self.ok("edit_curves")
        out = run(toast.build(EDIT_CURVES_CODE, run_over="geometry"), [self.curves_with("k", [10, 20])])
        self.assertEqual(r["curves"], [len(c) for c in out.curves])
        self.assert_bits(r["P"], out.points["position"])
        self.assertEqual(r["attrs"]["k"]["values"], out.curve_attrs["k"].tolist())

    def test_grease_pencil_points(self):
        r = self.ok("gp_points")
        out = run(toast.build(CURVES_POINTS_CODE), [self.curves_input()])
        self.assertEqual(r["curves"], [3, 4])
        self.assert_bits(r["P"], out.points["position"])
        self.assert_bits(r["attrs"]["w"]["values"], out.points["w"])

    def test_grease_pencil_grow(self):
        r = self.ok("gp_grow")
        out = run(toast.build(GROW_CODE, run_over="curves"), [self.curves_with("w", range(1, 8))])
        self.assertEqual(r["curves"], [len(c) for c in out.curves])
        self.assert_bits(r["P"], out.points["position"])
        self.assert_bits(r["attrs"]["w"]["values"], out.points["w"])

    def test_grease_pencil_draw(self):
        # Run Over Geometry draws into the layer: no separate Curves component appears.
        r = self.ok("gp_draw")
        out = run(toast.build(GP_DRAW_CODE, run_over="geometry"), [self.curves_input()])
        self.assertEqual(r["curves"], [3, 4, 2])
        self.assert_bits(r["P"], out.points["position"])

    def test_grease_pencil_attributes(self):
        attrs = self.ok("gp_attrs")["attrs"]
        self.assertEqual(attrs["vertex_color"]["type"], "FLOAT_COLOR")
        self.assert_bits(attrs["vertex_color"]["values"], [(1, 0.5, 0, 1)] * 7)
        self.assert_bits(attrs["opacity"]["values"], [0.25] * 7)
        self.assert_bits(attrs["radius"]["values"], [0.03] * 7)

    def test_curve_errors_in_blender(self):
        self.assertIn("add_curve() needs curves", " ".join(self.r["add_curve_on_mesh"]["warnings"]))
        self.assertIn("is already in a curve", " ".join(self.r["lone_point_on_curves"]["warnings"]))



@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderNeighborCache(unittest.TestCase):
    """The node reuses point_neighbors() tables by topology: never across a topology change."""

    def test_topology_change_rebuilds_the_table(self):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_neighbors_cache_check.py"
        proc = subprocess.run(
            [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code", "1",
             "--python", str(script), "--", str(repo)],
            capture_output=True, text=True, timeout=300,
        )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        if proc.returncode != 0 or not line:
            raise AssertionError(proc.stdout[-3000:] + proc.stderr[-3000:])
        frames = json.loads(line[0][len("RESULT "):])["frames"]
        self.assertEqual(frames, [{"points": 48, "ok": True}] * 3)


@unittest.skipUnless(_blender_has_toast_node(), "Blender with GeometryNodeToast not found")
class TestBlenderEditor(unittest.TestCase):
    """Templates, error locations and compile status (headless)."""

    @classmethod
    def setUpClass(cls):
        repo = Path(__file__).resolve().parents[1]
        script = Path(__file__).resolve().parent / "blender_ui_check.py"
        proc = subprocess.run(
            [BLENDER, "-b", "--factory-startup", "--enable-autoexec", "--python-exit-code", "1",
             "--python", str(script), "--", str(repo)],
            capture_output=True, text=True, timeout=300,
        )  # fmt: skip
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
        if proc.returncode != 0 or not line:
            raise AssertionError(proc.stdout[-3000:] + proc.stderr[-3000:])
        cls.r = json.loads(line[0][len("RESULT "):])

    def test_templates(self):
        self.assertIn("01_displace_with_noise", self.r["templates"])
        self.assertTrue(self.r["template_text"])

    def test_error_locations(self):
        self.assertEqual(self.r["syntax_error"][1:], ["code", 2])
        self.assertEqual(self.r["library_error"][1:], ["toast_lib.bad", 2])

    def test_status(self):
        self.assertEqual(self.r["status"][0], "ok")
        self.assertEqual(self.r["status_again"][0], "cached")

    def test_auto_compile_off(self):
        self.assertEqual(self.r["auto_compile"], {"skipped": True, "noted": True,
                                                  "compiled_manually": True,
                                                  "missing_kernel_built": True,
                                                  "auto_on_compiles": True,
                                                  "compile_button": True})  # fmt: skip

    def test_registered(self):
        self.assertEqual(self.r["registered"], {"panel": True, "menu": True,
                                                "text_templates_menu": True, "icon": True,
                                                "text_menu": True, "text_header": True,
                                                "help_menu": True, "guide_operator": True,
                                                "guide_file": True})  # fmt: skip


if __name__ == "__main__":
    unittest.main()
