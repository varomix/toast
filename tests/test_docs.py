# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Every ```toast block in docs/guide.md compiles, and a few recipes run as described."""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import toast  # noqa: E402
from toast.harness import Geometry, run  # noqa: E402

BLOCK_RE = re.compile(r"```toast( (\w+))?\n(.*?)```", re.S)


def blocks():
    text = (ROOT / "docs" / "guide.md").read_text()
    return [(m.group(2) or "points", m.group(3)) for m in BLOCK_RE.finditer(text)]


class TestGuide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["TOAST_CACHE_DIR"] = cls.tmp.name

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_example_compiles(self):
        found = blocks()
        self.assertGreaterEqual(len(found), 12)
        for run_over, code in found:
            with self.subTest(code=code.splitlines()[0]):
                toast.compile_source(code, run_over=run_over)

    def test_html_guide_is_up_to_date(self):
        import subprocess

        proc = subprocess.run([sys.executable, str(ROOT / "docs" / "build_guide.py"), "--check"],
                              capture_output=True, text=True)  # fmt: skip
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_example_kernel_compiles(self):
        from toast.compiler import collect_libraries

        src = ROOT / "examples" / "src"
        libs = {f"toast_lib.{p.stem[4:]}": p.read_text() for p in src.glob("*/lib_*.py")}
        kernels = [p for p in sorted(src.glob("*/*.py")) if not p.stem.startswith("lib_")]
        self.assertGreaterEqual(len(kernels), 15)
        for path in kernels:
            code = path.read_text()
            first = code.split("\n", 1)[0]
            run_over = next((k for k in ("points", "faces", "curves", "instances", "voxels", "geometry")
                             if f"Run Over: {k.title()}" in first), "points")  # fmt: skip
            with self.subTest(kernel=f"{path.parent.name}/{path.name}"):
                toast.compile_source(code, run_over=run_over,
                                     libs=collect_libraries(code, libs.get))  # fmt: skip

    def test_every_template_compiles(self):
        templates = sorted((ROOT / "toast" / "templates").glob("*.py"))
        self.assertGreaterEqual(len(templates), 9)
        for path in templates:
            text = path.read_text()
            header = [ln for ln in text.splitlines()[:4] if ln.startswith("# Run Over:")]
            self.assertEqual(len(header), 1, path.name)
            run_over = header[0].split(":", 1)[1].strip().upper().replace("FACE ", "")
            with self.subTest(template=path.name):
                toast.compile_source(text, run_over=run_over.lower())

    def test_grid_recipe(self):
        code = next(c for r, c in blocks() if r == "geometry")
        out = run(toast.build(code, run_over="geometry"), [Geometry({"position": np.zeros((0, 3),
                                                                                         np.float32)})])  # fmt: skip
        self.assertEqual(out.npoints, 25)
        self.assertEqual(len(out.prims), 16)
        self.assertEqual(out.prims[0], [0, 1, 6, 5])
        np.testing.assert_allclose(out.points["position"][6], [0.1, 0.1, 0], rtol=1e-6)

    def test_grid_recipe_on_existing_points(self):
        code = next(c for r, c in blocks() if r == "geometry")
        geo = Geometry({"position": np.ones((3, 3), np.float32)})
        out = run(toast.build(code, run_over="geometry"), [geo])
        self.assertEqual(out.npoints, 28)
        self.assertEqual(out.prims[0], [3, 4, 9, 8])


if __name__ == "__main__":
    unittest.main()
