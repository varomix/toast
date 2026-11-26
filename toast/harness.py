# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run Toast kernels on numpy arrays, without Blender.

This is the reference host: it does what ``GeometryNodeToast`` will do in the fork (bind
attributes, run fixed-size chunks on several threads, answer host calls, merge the command
buffers), so kernel behavior can be tested before the fork exists. The Blender node must give
the same results.

Geometry is points plus polygons, with attributes on points and on prims (faces)::

    Geometry(points={"position": float32 (n, 3), ...}, prims=[[0, 1, 2], ...],
             prim_attrs={"color": float32 (len(prims), 3), ...})

Curves geometry has ``curves`` (the points of each curve, in order) instead of prims, with
``curve_attrs``. Instances have ``instance_attrs``, with ``transform`` float32 (n, 4, 4)
(column-major, like Blender's instance_transform); ``@position`` reads and writes its translation.

Kernels run over points, faces (prims), curves, instances or the whole geometry once. Edges and
corners exist only in Blender.

Merge rules (the contract the fork must follow too):
- Commands are sorted by (source element index, emission order). Chunks have a fixed size, so the
  order never depends on the number of threads.
- New points are appended in that order. They get position from add_point; other attributes are zero.
- New prims are appended in that order; handles from add_point resolve to the new indices.
- New prims get zero prim attributes.
- Removals apply last: first prims (remove_prim keeps their points), then points. Removing a
  point removes every prim that uses it (Blender's Delete Geometry on points), then points and
  prims are renumbered keeping their order.
"""

import ctypes
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from .version import ABI_VERSION

DEFAULT_GRAIN = 1024

# Toast type name -> (numpy dtype, components)
NP_TYPES = {
    "float": (np.float32, 1),
    "int": (np.int32, 1),
    "bool": (np.bool_, 1),
    "vec2": (np.float32, 2),
    "vec3": (np.float32, 3),
    "vec4": (np.float32, 4),
    "quat": (np.float32, 4),
    "mat4": (np.float32, (4, 4)),
}


def _shape(size, ncomp):
    if isinstance(ncomp, tuple):
        return (size,) + ncomp
    return (size,) if ncomp == 1 else (size, ncomp)


class HarnessError(Exception):
    pass


@dataclass
class Geometry:
    points: dict = field(default_factory=dict)
    prims: list = field(default_factory=list)
    prim_attrs: dict = field(default_factory=dict)
    # Curves geometry: point indices of each curve (None for a mesh or point cloud).
    curves: list = None
    curve_attrs: dict = field(default_factory=dict)
    instance_attrs: dict = field(default_factory=dict)

    @property
    def ncurves(self):
        return 0 if self.curves is None else len(self.curves)

    @property
    def ninstances(self):
        for v in self.instance_attrs.values():
            return len(v)
        return 0

    @property
    def nprims(self):
        return len(self.prims)

    @property
    def npoints(self):
        if "position" in self.points:
            return len(self.points["position"])
        for v in self.points.values():
            return len(v)
        return 0

    def copy(self):
        return Geometry({k: np.array(v, copy=True) for k, v in self.points.items()},
                        [list(p) for p in self.prims],
                        {k: np.array(v, copy=True) for k, v in self.prim_attrs.items()},
                        None if self.curves is None else [list(c) for c in self.curves],
                        {k: np.array(v, copy=True) for k, v in self.curve_attrs.items()},
                        {k: np.array(v, copy=True) for k, v in self.instance_attrs.items()})

    def domain(self, name):
        """(attribute dict, element count) of a domain."""
        if name == "point":
            return self.points, self.npoints
        if name == "face":
            return self.prim_attrs, self.nprims
        if name == "curve":
            return self.curve_attrs, self.ncurves
        if name == "instance":
            return self.instance_attrs, self.ninstances
        raise HarnessError(f"the harness has no {name} domain")


def adapt_point_to_face(values, prims):
    """A point attribute read on faces, as Blender interpolates it: the sum over the face's points
    in corner order, times 1/n (float32, like attribute_math::SimpleMixer)."""
    values = np.asarray(values)
    out = np.zeros((len(prims),) + values.shape[1:], dtype=values.dtype)
    for f, prim in enumerate(prims):
        acc = np.zeros(values.shape[1:], dtype=np.float32)
        for v in prim:
            acc = (acc + values[v] * np.float32(1.0)).astype(np.float32)
        out[f] = acc * (np.float32(1.0) / np.float32(len(prim)))
    return out


# ---------------------------------------------------------------------------- ctypes ABI


class ToastAttr(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("size", ctypes.c_int64),
        ("type", ctypes.c_int32),
        ("domain", ctypes.c_int32),
    ]


NEARPOINTS_FN = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_float),
    ctypes.c_float, ctypes.c_int32, ctypes.POINTER(ctypes.c_int64),
)  # fmt: skip
NPOINTS_FN = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_void_p, ctypes.c_int32)
ADD_POINT_FN = ctypes.CFUNCTYPE(
    ctypes.c_int64, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64,
    ctypes.POINTER(ctypes.c_float),
)  # fmt: skip
ADD_PRIM_FN = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.POINTER(ctypes.c_int64),
    ctypes.c_int32,
)  # fmt: skip
REMOVE_POINT_FN = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int64
)


NPRIMS_FN = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_void_p, ctypes.c_int32)
PRIMPOINTS_FN = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32, ctypes.c_int64, ctypes.c_int32,
    ctypes.POINTER(ctypes.c_int64),
)  # fmt: skip
REMOVE_PRIM_FN = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int64
)


INDEX_QUERY_FN = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32, ctypes.c_int64, ctypes.c_int32,
    ctypes.POINTER(ctypes.c_int64),
)  # fmt: skip
CORNER_FN = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_void_p, ctypes.c_int32, ctypes.c_int64)
SET_ATTR_FN = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int32, ctypes.c_int64,
    ctypes.c_void_p,
)  # fmt: skip


class ToastHit(ctypes.Structure):
    _fields_ = [
        ("position", ctypes.c_float * 3),
        ("normal", ctypes.c_float * 3),
        ("bary", ctypes.c_float * 3),
        ("distance", ctypes.c_float),
        ("face", ctypes.c_int32),
        ("tri_points", ctypes.c_int32 * 3),
        ("hit", ctypes.c_int32),
    ]


NCURVES_FN = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_void_p, ctypes.c_int32)
REMOVE_CURVE_FN = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64, ctypes.c_int64
)

RAY_CAST_FN = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_float),
    ctypes.POINTER(ctypes.c_float), ctypes.c_float, ctypes.POINTER(ToastHit),
)  # fmt: skip
CLOSEST_FN = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_float),
    ctypes.c_float, ctypes.POINTER(ToastHit),
)  # fmt: skip


def _triangles(geo):
    """(tris (t, 3) point indices, face of each tri): fan triangulation of each prim."""
    tris, faces = [], []
    for f, prim in enumerate(geo.prims):
        for k in range(1, len(prim) - 1):
            tris.append((prim[0], prim[k], prim[k + 1]))
            faces.append(f)
    return np.array(tris, dtype=np.int64).reshape(-1, 3), np.array(faces, dtype=np.int64)


def _closest_on_triangles(p, a, b, c):
    """Closest points on triangles (a, b, c) to p, with barycentric weights (Ericson 5.1.5)."""
    n = len(a)
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    w = np.zeros((n, 3))
    done = np.zeros(n, bool)

    def setw(mask, w0, w1, w2):
        m = mask & ~done
        w[m, 0], w[m, 1], w[m, 2] = w0[m], w1[m], w2[m]
        done[m] = True

    one, zero = np.ones(n), np.zeros(n)
    with np.errstate(divide="ignore", invalid="ignore"):
        setw((d1 <= 0) & (d2 <= 0), one, zero, zero)
        setw((d3 >= 0) & (d4 <= d3), zero, one, zero)
        v = d1 / (d1 - d3)
        setw((vc <= 0) & (d1 >= 0) & (d3 <= 0), 1 - v, v, zero)
        setw((d6 >= 0) & (d5 <= d6), zero, zero, one)
        t = d2 / (d2 - d6)
        setw((vb <= 0) & (d2 >= 0) & (d6 <= 0), 1 - t, zero, t)
        u = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        setw((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), zero, 1 - u, u)
        denom = 1 / (va + vb + vc)
        vv, ww = vb * denom, vc * denom
        setw(np.ones(n, bool), 1 - vv - ww, vv, ww)
    q = a * w[:, :1] + b * w[:, 1:2] + c * w[:, 2:3]
    return q, w


class ToastHost(ctypes.Structure):
    _fields_ = [
        ("self", ctypes.c_void_p),
        ("nearpoints", NEARPOINTS_FN),
        ("npoints", NPOINTS_FN),
        ("cmd_add_point", ADD_POINT_FN),
        ("cmd_add_prim", ADD_PRIM_FN),
        ("cmd_remove_point", REMOVE_POINT_FN),
        ("nprims", NPRIMS_FN),
        ("primpoints", PRIMPOINTS_FN),
        ("cmd_remove_prim", REMOVE_PRIM_FN),
        ("point_faces", INDEX_QUERY_FN),
        ("point_neighbors", INDEX_QUERY_FN),
        ("corner_point", CORNER_FN),
        ("corner_face", CORNER_FN),
        ("cmd_set_attr", SET_ATTR_FN),
        ("ray_cast", RAY_CAST_FN),
        ("closest_point", CLOSEST_FN),
        ("ncurves", NCURVES_FN),
        ("curve_points", PRIMPOINTS_FN),
        ("cmd_remove_curve", REMOVE_CURVE_FN),
    ]


class ToastCtx(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("_pad", ctypes.c_uint32),
        ("begin", ctypes.c_int64),
        ("end", ctypes.c_int64),
        ("indices", ctypes.POINTER(ctypes.c_int64)),
        ("domain_size", ctypes.c_int64),
        ("attrs", ctypes.POINTER(ToastAttr)),
        ("params", ctypes.c_void_p),
        ("cmd", ctypes.c_void_p),
        ("host", ctypes.POINTER(ToastHost)),
        ("chunk_id", ctypes.c_int64),
        ("time", ctypes.c_float),
        ("frame", ctypes.c_float),
    ]


# ---------------------------------------------------------------------------- loading


class LoadedKernel:
    """A kernel .so opened with ctypes."""

    def __init__(self, kernel):
        self.kernel = kernel
        self.signature = kernel.signature
        self.lib = ctypes.CDLL(str(kernel.so_path))
        self.lib.toast_abi_version.restype = ctypes.c_int32
        abi = self.lib.toast_abi_version()
        if abi != ABI_VERSION:
            raise HarnessError(f"kernel ABI {abi}, harness ABI {ABI_VERSION}")
        self.lib.toast_signature.restype = ctypes.c_char_p
        embedded = json.loads(self.lib.toast_signature().decode())
        if embedded != self.signature:
            raise HarnessError("signature in the .so differs from the cached JSON")
        self.fn = self.lib.toast_kernel
        self.fn.argtypes = [ctypes.POINTER(ToastCtx)]
        self.fn.restype = None


def pack_params(signature, values=None):
    """Lay out ch() values as the kernel's Params struct. Missing values use the defaults."""
    values = dict(values or {})
    unknown = set(values) - {p["name"] for p in signature["params"]}
    if unknown:
        raise HarnessError(f"unknown parameters: {', '.join(sorted(unknown))}")
    buf = ctypes.create_string_buffer(max(signature["params_size"], 4))
    for p in signature["params"]:
        v = values.get(p["name"], p["default"])
        t, off = p["type"], p["offset"]
        if t == "float":
            arr = np.array([v], dtype=np.float32)
        elif t in ("int", "bool"):
            arr = np.array([int(v)], dtype=np.int32)
        else:
            arr = np.array(v, dtype=np.float32).reshape(-1)
            if arr.size != NP_TYPES[t][1]:
                raise HarnessError(f"parameter {p['name']} needs {NP_TYPES[t][1]} values")
        ctypes.memmove(ctypes.addressof(buf) + off, arr.tobytes(), arr.nbytes)
    return buf


# ---------------------------------------------------------------------------- the host


class _Host:
    """Host services and command buffers for one kernel run."""

    def __init__(self, inputs, attr_sizes=()):
        self.inputs = inputs
        # Bytes per element of each bound attribute, for cmd_set_attr.
        self.attr_sizes = list(attr_sizes)
        self._topology = {}
        self.lock = threading.Lock()
        self.cmds = {}  # chunk_id -> list of commands, in emission order
        self.added = {}  # chunk_id -> points added so far (local handle index)
        self.errors = []
        self._positions = {}

        self.c_nearpoints = NEARPOINTS_FN(self._guard(self._nearpoints, 0))
        self.c_npoints = NPOINTS_FN(self._guard(self._npoints, 0))
        self.c_add_point = ADD_POINT_FN(self._guard(self._add_point, -1))
        self.c_add_prim = ADD_PRIM_FN(self._guard(self._add_prim, None))
        self.c_remove_point = REMOVE_POINT_FN(self._guard(self._remove_point, None))
        self.c_nprims = NPRIMS_FN(self._guard(self._nprims, 0))
        self.c_primpoints = PRIMPOINTS_FN(self._guard(self._primpoints, 0))
        self.c_remove_prim = REMOVE_PRIM_FN(self._guard(self._remove_prim, None))
        self.c_point_faces = INDEX_QUERY_FN(self._guard(self._point_faces, 0))
        self.c_point_neighbors = INDEX_QUERY_FN(self._guard(self._point_neighbors, 0))
        self.c_corner_point = CORNER_FN(self._guard(self._corner_point, -1))
        self.c_corner_face = CORNER_FN(self._guard(self._corner_face, -1))
        self.c_set_attr = SET_ATTR_FN(self._guard(self._set_attr, None))
        self.struct = ToastHost(
            None, self.c_nearpoints, self.c_npoints, self.c_add_point, self.c_add_prim,
            self.c_remove_point, self.c_nprims, self.c_primpoints, self.c_remove_prim,
            self.c_point_faces, self.c_point_neighbors, self.c_corner_point, self.c_corner_face,
            self.c_set_attr, RAY_CAST_FN(self._guard(self._ray_cast, 0)),
            CLOSEST_FN(self._guard(self._closest_point, 0)),
            NCURVES_FN(self._guard(self._ncurves, 0)),
            PRIMPOINTS_FN(self._guard(self._curve_points, 0)),
            REMOVE_CURVE_FN(self._guard(self._remove_curve, None)),
        )  # fmt: skip
        self._keep_fns = (self.struct.ray_cast, self.struct.closest_point, self.struct.ncurves,
                          self.struct.curve_points, self.struct.cmd_remove_curve)  # fmt: skip

    def _guard(self, fn, default):
        def wrapped(*args):
            try:
                return fn(*args)
            except Exception as ex:  # Exceptions can't cross into C; report after the run.
                with self.lock:
                    self.errors.append(ex)
                return default

        return wrapped

    def _input(self, inp):
        if inp >= len(self.inputs) or self.inputs[inp] is None:
            return None
        return self.inputs[inp]

    def _positions_of(self, inp):
        with self.lock:
            pos = self._positions.get(inp)
            if pos is None:
                geo = self._input(inp)
                p = None if geo is None else geo.points.get("position")
                pos = np.zeros((0, 3), np.float32) if p is None else np.asarray(p, dtype=np.float32)
                self._positions[inp] = pos
            return pos

    def _nearpoints(self, _self, inp, pos3, radius, max_count, out):
        """Same contract and float32 arithmetic as the fork's KD-tree query: distance_sq is
        x*x + y*y + z*z in float, inclusive radius, sorted by distance then index."""
        pos = self._positions_of(inp)
        if len(pos) == 0 or max_count <= 0 or not radius >= 0:
            return 0
        q = np.array([pos3[0], pos3[1], pos3[2]], dtype=np.float32)
        d = pos - q
        d2 = d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1] + d[:, 2] * d[:, 2]
        r = np.float32(radius)
        idx = np.nonzero(d2 <= r * r)[0]
        order = idx[np.lexsort((idx, d2[idx]))][:max_count]
        for k, j in enumerate(order):
            out[k] = int(j)
        return len(order)

    def _npoints(self, _self, inp):
        geo = self._input(inp)
        if geo is None:
            return 0
        return geo.npoints if geo.points or not geo.instance_attrs else geo.ninstances

    def _nprims(self, _self, inp):
        geo = self._input(inp)
        return 0 if geo is None else geo.nprims

    def _ncurves(self, _self, inp):
        geo = self._input(inp)
        return 0 if geo is None else geo.ncurves

    def _curve_points(self, _self, inp, curve, max_count, out):
        geo = self._input(inp)
        if geo is None or not 0 <= curve < geo.ncurves:
            return 0
        pts = geo.curves[curve]
        for k, pt in enumerate(pts[:max_count]):
            out[k] = int(pt)
        return len(pts)

    def _remove_curve(self, _self, cmd, src, curve):
        self._chunk_list(cmd).append(("remove_curve", src, curve, None))

    def _primpoints(self, _self, inp, prim, max_count, out):
        geo = self._input(inp)
        if geo is None or not 0 <= prim < geo.nprims:
            return 0
        pts = geo.prims[prim]
        for k, pt in enumerate(pts[:max_count]):
            out[k] = int(pt)
        return len(pts)

    def _topology_of(self, inp):
        """Lazily built point->faces, point->neighbors and corner->(point, face) tables."""
        with self.lock:
            topo = self._topology.get(inp)
            if topo is None:
                geo = self._input(inp)
                n = 0 if geo is None else geo.npoints
                faces = [[] for _ in range(n)]
                neighbors = [set() for _ in range(n)]
                corners = []
                for f, prim in enumerate([] if geo is None else geo.prims):
                    for k, p in enumerate(prim):
                        faces[p].append(f)
                        corners.append((p, f))
                    pairs = [tuple(prim)] if len(prim) == 2 else [
                        (prim[k], prim[(k + 1) % len(prim)]) for k in range(len(prim))]
                    for a, b in pairs:
                        neighbors[a].add(b)
                        neighbors[b].add(a)
                topo = (faces, [sorted(x) for x in neighbors], corners)
                self._topology[inp] = topo
            return topo

    @staticmethod
    def _write_indices(values, max_count, out):
        for k, v in enumerate(values[:max_count]):
            out[k] = int(v)
        return len(values)

    def _point_faces(self, _self, inp, pt, max_count, out):
        faces = self._topology_of(inp)[0]
        return self._write_indices(faces[pt], max_count, out) if 0 <= pt < len(faces) else 0

    def _point_neighbors(self, _self, inp, pt, max_count, out):
        nb = self._topology_of(inp)[1]
        return self._write_indices(nb[pt], max_count, out) if 0 <= pt < len(nb) else 0

    def _corner_point(self, _self, inp, corner):
        corners = self._topology_of(inp)[2]
        return corners[corner][0] if 0 <= corner < len(corners) else -1

    def _corner_face(self, _self, inp, corner):
        corners = self._topology_of(inp)[2]
        return corners[corner][1] if 0 <= corner < len(corners) else -1

    def _tris_of(self, inp):
        with self.lock:
            key = ("tris", inp)
            if key not in self._topology:
                geo = self._input(inp)
                if geo is None or not geo.prims:
                    self._topology[key] = None
                else:
                    tris, faces = _triangles(geo)
                    P = np.asarray(geo.points["position"], np.float64)
                    self._topology[key] = (tris, faces, P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]])
            return self._topology[key]

    @staticmethod
    def _fill_hit(out, tri, face, pos, bary, dist, a, b, c):
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        n = n / ln if ln > 0 else n
        out.contents.position[:] = [float(x) for x in pos]
        out.contents.normal[:] = [float(x) for x in n]
        out.contents.bary[:] = [float(x) for x in bary]
        out.contents.distance = float(dist)
        out.contents.face = int(face)
        out.contents.tri_points[:] = [int(x) for x in tri]
        out.contents.hit = 1
        return 1

    def _ray_cast(self, _self, inp, origin, direction, max_dist, out):
        data = self._tris_of(inp)
        if data is None:
            return 0
        tris, faces, A, B, C = data
        o = np.array(origin[:3], np.float64)
        d = np.array(direction[:3], np.float64)
        ln = np.linalg.norm(d)
        if ln == 0:
            return 0
        d = d / ln
        e1, e2 = B - A, C - A
        h = np.cross(d, e2)
        det = (e1 * h).sum(1)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv = 1.0 / det
            s_ = o - A
            u = (s_ * h).sum(1) * inv
            q = np.cross(s_, e1)
            v = (q * d).sum(1) * inv
            t = (e2 * q).sum(1) * inv
        ok = (np.abs(det) > 1e-12) & (u >= 0) & (v >= 0) & (u + v <= 1) & (t >= 0) & (t <= max_dist)
        if not ok.any():
            return 0
        k = int(np.flatnonzero(ok)[np.argmin(t[ok])])
        return self._fill_hit(out, tris[k], faces[k], o + d * t[k], (1 - u[k] - v[k], u[k], v[k]),
                              t[k], A[k], B[k], C[k])  # fmt: skip

    def _closest_point(self, _self, inp, pos, max_dist, out):
        data = self._tris_of(inp)
        if data is None:
            return 0
        tris, faces, A, B, C = data
        p = np.array(pos[:3], np.float64)
        q, w = _closest_on_triangles(p, A, B, C)
        d2 = ((q - p) ** 2).sum(1)
        k = int(np.argmin(d2))
        dist = float(np.sqrt(d2[k]))
        if dist > max_dist:
            return 0
        return self._fill_hit(out, tris[k], faces[k], q[k], w[k], dist, A[k], B[k], C[k])

    def _set_attr(self, _self, cmd, src, attr, elem, value):
        size = self.attr_sizes[attr]
        data = ctypes.string_at(value, size)
        self._chunk_list(cmd).append(("set_attr", src, (attr, elem, data), None))

    def _remove_prim(self, _self, cmd, src, prim):
        self._chunk_list(cmd).append(("remove_prim", src, prim, None))

    def _chunk_list(self, cmd):
        return self.cmds[cmd]

    def _add_point(self, _self, cmd, src, pos3):
        lst = self._chunk_list(cmd)
        local = self.added.get(cmd, 0)
        self.added[cmd] = local + 1
        handle = -(((cmd - 1) << 32) | local) - 1
        lst.append(("add_point", src, (pos3[0], pos3[1], pos3[2]), handle))
        return handle

    def _add_prim(self, _self, cmd, src, pts, n):
        self._chunk_list(cmd).append(("add_prim", src, [pts[k] for k in range(n)], None))

    def _remove_point(self, _self, cmd, src, pt):
        self._chunk_list(cmd).append(("remove_point", src, pt, None))


def _apply_sets(host, arrays):
    """Apply set_point_attr/set_face_attr in (src, emission order), into the bound arrays."""
    sets = []
    for chunk_id in sorted(host.cmds):
        for seq, c in enumerate(host.cmds[chunk_id]):
            if c[0] == "set_attr":
                sets.append((c[1], chunk_id, seq, c[2]))
    sets.sort(key=lambda t: t[:3])
    for _src, _chunk, _seq, (attr, elem, data) in sets:
        arr = arrays[attr]
        if not 0 <= elem < len(arr):
            raise HarnessError(f"element {elem} does not exist (set_*_attr)")
        raw = arr.view(np.uint8).reshape(len(arr), -1)
        raw[elem] = np.frombuffer(data, dtype=np.uint8)


def _merge(out, host, n_input_points, n_input_prims, run_over="points"):
    """Apply queued commands to ``out`` (the copy of input 0). See the module docstring."""
    if run_over == "instances":
        _merge_instances(out, host)
        return
    if out.curves is not None:
        _merge_curves(out, host)
        return
    all_cmds = []
    for chunk_id in sorted(host.cmds):
        for seq, c in enumerate(host.cmds[chunk_id]):
            all_cmds.append((c[1], chunk_id, seq, c))
    if not all_cmds:
        return
    all_cmds.sort(key=lambda t: (t[0], t[1], t[2]))

    handle_to_index = {}
    new_positions = []
    new_prims = []
    removed = set()
    removed_prims = set()
    n_total = n_input_points

    # Indices from n_input_points on are points added in this run, in merged order.
    n_added = sum(1 for c in all_cmds if c[3][0] == "add_point")

    def resolve(pt):
        if pt < 0:
            if pt not in handle_to_index:
                raise HarnessError(f"unknown point handle {pt}")
            return handle_to_index[pt]
        if pt >= n_input_points + n_added:
            raise HarnessError(f"point {pt} does not exist")
        return pt

    for _src, _chunk, _seq, (kind, _s, payload, handle) in all_cmds:
        if kind == "set_attr":
            continue  # Applied before the merge, see _apply_sets.
        if kind == "add_point":
            handle_to_index[handle] = n_total
            new_positions.append(payload)
            n_total += 1
        elif kind == "add_prim":
            new_prims.append([resolve(p) for p in payload])
        elif kind == "remove_point":
            removed.add(resolve(payload))
        elif kind == "remove_prim":
            if not 0 <= payload < n_input_prims:
                raise HarnessError(f"prim {payload} does not exist")
            removed_prims.add(payload)
        elif kind == "remove_curve":
            raise HarnessError("remove_curve() needs curves")

    n_new = len(new_positions)
    if n_new:
        for name, arr in list(out.points.items()):
            extra = np.zeros((n_new,) + arr.shape[1:], dtype=arr.dtype)
            if name == "position":
                extra[:] = np.array(new_positions, dtype=arr.dtype)
            out.points[name] = np.concatenate([arr, extra])
        if "position" not in out.points:
            out.points["position"] = np.array(new_positions, dtype=np.float32)
    out.prims.extend(new_prims)
    if new_prims:
        for name, arr in list(out.prim_attrs.items()):
            extra = np.zeros((len(new_prims),) + arr.shape[1:], dtype=arr.dtype)
            out.prim_attrs[name] = np.concatenate([arr, extra])

    def keep_prims(keep):
        out.prims = [p for p, k in zip(out.prims, keep) if k]
        out.prim_attrs = {n: v[np.asarray(keep, dtype=bool)] for n, v in out.prim_attrs.items()}

    if removed_prims:
        keep_prims([k not in removed_prims for k in range(len(out.prims))])

    if removed:
        keep = np.ones(n_total, dtype=bool)
        keep[list(removed)] = False
        remap = np.cumsum(keep) - 1
        out.points = {k: v[keep] for k, v in out.points.items()}
        keep_prims([all(keep[p] for p in prim) for prim in out.prims])
        out.prims = [[int(remap[p]) for p in prim] for prim in out.prims]


def _sorted_cmds(host):
    cmds = []
    for chunk_id in sorted(host.cmds):
        for seq, c in enumerate(host.cmds[chunk_id]):
            cmds.append((c[1], chunk_id, seq, c))
    cmds.sort(key=lambda t: t[:3])
    return [c[3] for c in cmds if c[3][0] != "set_attr"]


def _merge_instances(out, host):
    """remove_instance() (queued as remove_point): drop those instances, keeping the order."""
    removed = set()
    for kind, _src, payload, _h in _sorted_cmds(host):
        if kind != "remove_point":
            raise HarnessError(f"{kind} doesn't work on instances")
        if not 0 <= payload < out.ninstances:
            raise HarnessError(f"instance {payload} does not exist")
        removed.add(payload)
    if removed:
        keep = np.array([k not in removed for k in range(out.ninstances)])
        out.instance_attrs = {k: v[keep] for k, v in out.instance_attrs.items()}


def _merge_curves(out, host):
    """Curves: remove_curve() removes a curve with its points; remove_point() removes points, and
    curves left without points (like Blender's Delete Geometry)."""
    removed_curves, removed_points = set(), set()
    for kind, _src, payload, _h in _sorted_cmds(host):
        if kind == "remove_curve":
            if not 0 <= payload < out.ncurves:
                raise HarnessError(f"curve {payload} does not exist")
            removed_curves.add(payload)
        elif kind == "remove_point":
            if not 0 <= payload < out.npoints:
                raise HarnessError(f"point {payload} does not exist")
            removed_points.add(payload)
        else:
            raise HarnessError(f"{kind} doesn't work on curves")
    if not removed_curves and not removed_points:
        return
    keep_curve = np.array([k not in removed_curves for k in range(out.ncurves)], dtype=bool)
    for k in np.flatnonzero(~keep_curve):
        removed_points.update(out.curves[k])
    keep_pt = np.ones(out.npoints, dtype=bool)
    keep_pt[list(removed_points)] = False
    remap = np.cumsum(keep_pt) - 1
    curves = [[int(remap[p]) for p in c if keep_pt[p]] for c in out.curves]
    keep_curve &= np.array([len(c) > 0 for c in curves], dtype=bool)
    out.curves = [c for c, k in zip(curves, keep_curve) if k]
    out.curve_attrs = {k: v[keep_curve] for k, v in out.curve_attrs.items()}
    out.points = {k: v[keep_pt] for k, v in out.points.items()}


def run(kernel, inputs, params=None, threads=1, grain=DEFAULT_GRAIN, selection=None,
        frame=1.0, time=0.0):  # fmt: skip
    """Run ``kernel`` (a toast.Kernel or LoadedKernel) and return the output Geometry.

    ``inputs`` is a list of Geometry (index = input number). ``selection`` is an optional array of
    point indices to run over (the mask); unselected points are left unchanged.
    """
    lk = kernel if isinstance(kernel, LoadedKernel) else LoadedKernel(kernel)
    sig = lk.signature
    inputs = list(inputs)
    if not inputs or inputs[0] is None:
        raise HarnessError("input 0 is required")
    out = inputs[0].copy()
    run_over = sig["run_over"]
    if run_over == "points":
        n = out.npoints
    elif run_over == "faces":
        n = out.nprims
    elif run_over == "curves":
        n = out.ncurves
    elif run_over == "instances":
        n = out.ninstances
    elif run_over == "geometry":
        n = 1
    else:
        raise HarnessError(f"the harness can't run over {run_over}")
    n_input_prims = out.nprims

    # Bind attributes in signature order. Output arrays are the copy of input 0, so snapshot
    # reads (and every read of inputs 1+) see the unmodified input arrays.
    keep_alive = []
    # Instance positions are the transforms' translation: bound as a copy, written back after.
    position_writeback = None
    attrs = (ToastAttr * max(len(sig["attrs"]), 1))()
    for k, a in enumerate(sig["attrs"]):
        dtype, ncomp = NP_TYPES[a["type"]]
        inp = a["input"]
        if inp == 0 and not a["snapshot"]:
            geo = out
        else:
            geo = inputs[inp] if inp < len(inputs) else None
            if geo is None:
                raise HarnessError(f"attribute '{a['name']}' needs input {inp}, which is empty")
        domain = a.get("domain", "point")
        container, size = geo.domain(domain)
        # output() values are kept as "output.<name>" on the Run Over domain.
        key = f"output.{a['name']}" if a.get("output") else a["name"]
        arr = container.get(key)
        if (domain == "instance" and a["name"] == "position" and "transform" in container
                and not a.get("output")):  # fmt: skip
            arr = np.ascontiguousarray(container["transform"][:, 3, :3])
            if geo is out and "w" in a["access"]:
                position_writeback = arr
            keep_alive.append(arr)
            attrs[k] = ToastAttr(arr.ctypes.data, len(arr), 0, 0)
            continue
        if (arr is None and domain in ("face", "curve") and "w" not in a["access"]
                and a["name"] in geo.points and not a.get("output")):  # fmt: skip
            groups = geo.prims if domain == "face" else geo.curves
            arr = adapt_point_to_face(geo.points[a["name"]], groups).astype(
                geo.points[a["name"]].dtype)
        shape = _shape(size, ncomp)
        if arr is None:
            if not a["create"]:
                raise HarnessError(f"attribute '{a['name']}' not found on input {inp}")
            arr = np.zeros(shape, dtype=dtype)
            container[key] = arr
        if arr.dtype != dtype or arr.shape != shape:
            raise HarnessError(
                f"attribute '{a['name']}' is {arr.dtype}{arr.shape}, kernel needs "
                f"{np.dtype(dtype)}{shape} ({a['type']})"
            )
        if not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)
            container[key] = arr
        keep_alive.append(arr)
        attrs[k] = ToastAttr(arr.ctypes.data, len(arr), 0, 0)

    params_buf = pack_params(sig, params)
    host = _Host(inputs, [a.dtype.itemsize * (a.size // max(len(a), 1)) if len(a) else
                          np.dtype(NP_TYPES[s["type"]][0]).itemsize * int(np.prod(NP_TYPES[s["type"]][1]))
                          for a, s in zip(keep_alive, sig["attrs"])])  # fmt: skip

    if selection is not None:
        indices = np.ascontiguousarray(np.asarray(selection, dtype=np.int64))
        count = len(indices)
        idx_ptr = indices.ctypes.data_as(ctypes.POINTER(ctypes.c_int64))
    else:
        count = n
        idx_ptr = None

    chunks = [(cid, b, min(b + grain, count)) for cid, b in enumerate(range(0, count, grain))]
    for cid, _, _ in chunks:
        host.cmds[cid + 1] = []

    def run_chunk(chunk):
        cid, b, e = chunk
        ctx = ToastCtx(
            ABI_VERSION, 0, b, e, idx_ptr, n, attrs, ctypes.cast(params_buf, ctypes.c_void_p),
            ctypes.c_void_p(cid + 1), ctypes.pointer(host.struct), cid, time, frame,
        )  # fmt: skip
        lk.fn(ctypes.byref(ctx))

    if threads <= 1:
        for ch in chunks:
            run_chunk(ch)
    else:
        with ThreadPoolExecutor(max_workers=threads) as pool:
            list(pool.map(run_chunk, chunks))

    if host.errors:
        raise HarnessError(f"host callback failed: {host.errors[0]!r}") from host.errors[0]

    # Chunk ids were offset by one so the cmd pointer is never null.
    host.cmds = {cid - 1: lst for cid, lst in host.cmds.items()}
    _apply_sets(host, keep_alive)
    if position_writeback is not None:
        out.instance_attrs["transform"][:, 3, :3] = position_writeback
    _merge(out, host, out.npoints, n_input_prims, run_over)
    del keep_alive
    return out
