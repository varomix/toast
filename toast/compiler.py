# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Toast frontend: typed Python subset -> C++ kernel source plus a signature.

Pipeline: ``desugar`` (``@`` attributes) -> ``ast.parse`` -> one ordered walk that infers types,
checks the code and emits C++. A variable's type is fixed by its first assignment; declarations
are hoisted to the top of the per-element body. Errors carry the user's line number.
"""

import ast
import json
import math
import re
from dataclasses import dataclass, field

from .errors import ToastError
from .sugar import ATTR_OBJECT, desugar
from .types import (
    ARRAY_ELEMENTS,
    ARRAY_MAX,
    BOOL,
    BY_NAME,
    FLOAT,
    HIT,
    INT,
    KNOWN_ATTRS,
    MAT4,
    NONE,
    POINTREF,
    PROPERTIES,
    QUAT,
    RECORDS,
    VEC3,
    VECS,
    VORONOI,
    array_parts,
    array_type,
)
from .version import ABI_VERSION, VERSION

RUN_OVER = ("points", "faces", "edges", "corners", "curves", "instances", "geometry")
# Domain of `@` attributes for each run-over mode ("geometry" runs once and has none).
RUN_DOMAIN = {
    "points": "point", "faces": "face", "edges": "edge", "corners": "corner", "curves": "curve",
    "instances": "instance", "geometry": None,
}  # fmt: skip
DOMAIN_SUFFIX = {"point": "", "face": "f", "edge": "e", "corner": "c", "curve": "k", "instance": "n"}
# Domains input 0 has in each mode. With Run Over Points the code runs on meshes, point clouds and
# curves alike, so anything may exist.
INPUT0_DOMAINS = {
    "points": {"point", "face", "edge", "corner", "curve"},
    "faces": {"point", "face", "edge", "corner"},
    "edges": {"point", "face", "edge", "corner"},
    "corners": {"point", "face", "edge", "corner"},
    "curves": {"point", "curve"},
    "instances": {"instance"},
    "geometry": {"point", "face", "edge", "corner", "curve"},
}
DOMAIN_WORD = {"point": "points", "face": "faces", "edge": "edges", "corner": "face corners",
               "curve": "curves", "instance": "instances"}  # fmt: skip

MAIN = "__main__"
LIB_PACKAGE = "toast_lib"
MAX_INPUTS = 4
NEARPOINTS_MAX_LIMIT = 4096
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
ATTR_OBJ_RE = re.compile(rf"{ATTR_OBJECT}\Z")

# Read-only attributes from the context. `@index`/`@count` are the element's index and the
# element count of the run-over domain; `@frame`/`@time` are the scene's.
TIME_ATTRS = {"frame": (FLOAT, "c->frame"), "time": (FLOAT, "c->time")}
SPECIAL_NAMES = {"index", "count"} | set(TIME_ATTRS)
# Names from earlier Toast versions, for a helpful error.
OLD_NAMES = {
    "P": "position", "N": "normal", "Cd": "color", "v": "velocity", "pscale": "radius",
    "ptnum": "index", "primnum": "index", "vtxnum": "index", "numpt": "count",
    "numprim": "count", "numvtx": "count", "Frame": "frame", "Time": "time",
}  # fmt: skip
OLD_FUNCTIONS = {
    "ch": "param", "fit": "map_range", "fit01": "map_range", "snoise": "signed_noise",
    "rand": "hash01", "point": "point_attr", "prim": "face_attr", "npoints": "point_count",
    "nprims": "face_count", "nearpoint": "nearest_point", "nearpoints": "nearby_points",
    "primpoints": "face_points", "add_prim": "add_face", "remove_prim": "remove_face",
}  # fmt: skip

UNARY_MATH = (
    "sin cos tan asin acos atan sinh cosh tanh exp log log2 log10 sqrt floor ceil trunc "
    "frac sign radians degrees abs"
).split()
# math.<name> spellings. math.floor/ceil/trunc return int, as in Python.
MATH_MODULE_UNARY = {
    n: n
    for n in "sin cos tan asin acos atan sinh cosh tanh exp log log2 log10 sqrt degrees radians".split()
}
MATH_MODULE_UNARY["fabs"] = "abs"
MATH_MODULE_TO_INT = ("floor", "ceil", "trunc")
MATH_MODULE_BINARY = {"pow": "pow", "atan2": "atan2", "fmod": "fmod"}
MATH_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

BUILTINS = set(UNARY_MATH) | {
    "pow", "atan2", "fmod", "min", "max", "clamp", "lerp", "map_range", "smoothstep",
    "dot", "cross", "length", "distance", "normalize", "int", "float", "bool",
    "vec2", "vec3", "vec4", "noise", "signed_noise", "fbm", "hash01", "random", "param",
    "point_attr", "face_attr", "point_count", "face_count", "nearest_point", "nearby_points",
    "face_points", "add_point", "add_face", "add_edge", "remove_point", "remove_face", "range",
    "point_faces", "point_neighbors", "corner_point", "corner_face", "set_point_attr",
    "set_face_attr", "ray_cast", "closest_point", "sample_nearest_surface", "voronoi",
    "curl_noise", "len", "curve_attr", "instance_attr", "curve_count", "curve_points",
    "remove_curve", "add_curve", "extend_curve", "remove_instance", "quat", "mat4", "quat_axis_angle", "quat_euler",
    "quat_between", "rotate", "slerp", "inverse", "to_euler", "transpose", "transform_point",
    "transform_direction", "mat4_translation", "mat4_rotation", "mat4_scale", "mat4_compose",
    "output",
}  # fmt: skip
# Types an output() socket can have, and the socket each becomes.
OUTPUT_SOCKETS = {"float": "Float", "int": "Integer", "bool": "Boolean", "vec3": "Vector",
                  "vec4": "Color", "quat": "Rotation", "mat4": "Matrix"}  # fmt: skip
LOOP_FUNCTIONS = ("range", "nearby_points", "face_points", "point_faces", "point_neighbors",
                  "curve_points")  # fmt: skip

BINOPS = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//",
    ast.Mod: "%", ast.Pow: "**", ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^",
    ast.LShift: "<<", ast.RShift: ">>",
}  # fmt: skip
CMPOPS = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!="}


def float_lit(v):
    if not math.isfinite(v):
        raise ValueError(v)
    r = repr(float(v))
    return f"{r}f"


@dataclass
class E:
    """A typed C++ expression. ``const`` holds the Python value of literals."""

    code: str
    type: object
    const: object = None


@dataclass
class Binding:
    index: int
    name: str
    type: object
    input: int
    snapshot: bool
    domain: str = "point"
    read: bool = False
    write: bool = False
    # An output() socket: written per element, stored as an anonymous attribute by the node.
    output: bool = False

    @property
    def var(self):
        prefix = "o" if self.output else ("s" if self.snapshot else "a")
        return f"{prefix}{self.input}{DOMAIN_SUFFIX[self.domain]}_{self.name}"

    @property
    def size_var(self):
        return f"n{self.var}"


@dataclass
class Param:
    name: str
    type: object
    default: object
    min: object = None
    max: object = None
    offset: int = 0


@dataclass
class CompiledSource:
    cpp: str
    signature: dict
    desugared: str = ""


@dataclass
class _Local:
    type: object
    line: int


@dataclass
class Compiler:
    source: str
    run_over: str = "points"
    locals: dict = field(default_factory=dict)
    bindings: dict = field(default_factory=dict)
    attr_types: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    # output() sockets in order: name -> (type, line of the first call).
    outputs: dict = field(default_factory=dict)
    host_uses: set = field(default_factory=set)
    inputs_used: set = field(default_factory=set)
    nearpoints_inputs: set = field(default_factory=set)
    surface_inputs: set = field(default_factory=set)
    uses_cmd: bool = False
    builds_curves: bool = False  # add_curve()/extend_curve(): Run Over Geometry runs on curves.
    uses_return: bool = False
    uses_time: bool = False
    loop_depth: int = 0
    tmp: int = 0
    lines: list = field(default_factory=list)
    depth: int = 2
    written_attrs: set = field(default_factory=set)
    # Attribute types from `@name: type` annotations.
    declared: dict = field(default_factory=dict)
    assigned_names: set = field(default_factory=set)
    cur_line: int = None
    # Library sources by module name ("toast_lib.x"), resolved before compiling.
    libs: dict = field(default_factory=dict)
    # Per module: {"names": bare name -> ast.FunctionDef, "aliases": alias -> module}.
    modules: dict = field(default_factory=dict)
    cur_module: str = MAIN
    # (qualified def name, arg types) -> (C++ name, return type).
    helpers: dict = field(default_factory=dict)
    helper_code: list = field(default_factory=list)
    # The helper being compiled: {"name", "ret", "ret_line", "uses_ch"}, None in the kernel body.
    func: dict = None
    compiling: list = field(default_factory=list)

    # ------------------------------------------------------------------ entry

    def compile(self):
        if self.run_over not in RUN_OVER:
            raise ToastError(
                f"run over '{self.run_over}' is not supported yet (supported: {', '.join(RUN_OVER)})"
            )
        text = desugar(self.source)
        try:
            tree = ast.parse(text)
        except SyntaxError as ex:
            raise ToastError(f"syntax error: {ex.msg}", ex.lineno) from None
        self._prepass(tree)
        self._load_module(MAIN, tree)
        for s in tree.body:
            if isinstance(s, ast.FunctionDef):
                continue  # Compiled per call, for the argument types of that call.
            self.stmt(s)
        cpp, sig = self._emit()
        return CompiledSource(cpp=cpp, signature=sig, desugared=text)

    def err(self, msg, node=None):
        line = getattr(node, "lineno", None) or self.cur_line
        raise ToastError(msg, line, None if self.cur_module == MAIN else self.cur_module)

    @property
    def defs(self):
        """def helpers callable by bare name in the module being compiled."""
        return self.modules[self.cur_module]["names"]

    def line(self, text):
        self.lines.append("  " * self.depth + text)

    def new_tmp(self):
        self.tmp += 1
        return f"_t{self.tmp}"

    # ------------------------------------------------------------------ prepass

    @staticmethod
    def _walk_outside_defs(tree):
        # Depth-first in source order, so the first declaration of an attribute wins.
        todo = [n for n in reversed(tree.body) if not isinstance(n, ast.FunctionDef)]
        while todo:
            node = todo.pop()
            yield node
            todo.extend(
                reversed([c for c in ast.iter_child_nodes(node) if not isinstance(c, ast.FunctionDef)])
            )

    def _prepass(self, tree):
        """Find attributes written on input 0 and every assigned local name."""
        for node in self._walk_outside_defs(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            elif isinstance(node, ast.For):
                targets = [node.target]
            for t in targets:
                base = t
                while isinstance(base, (ast.Attribute, ast.Subscript)) and not self._is_attr(base):
                    base = base.value
                if self._is_attr(base):
                    if isinstance(node, ast.AnnAssign) and t is node.target:
                        self._declare_attr(node)
                        if node.value is None:
                            continue  # A declaration, not a write.
                    self.written_attrs.add(base.attr)
                elif isinstance(base, ast.Name):
                    self.assigned_names.add(base.id)

    # ------------------------------------------------------------------ attributes

    @staticmethod
    def _is_attr(node):
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and ATTR_OBJ_RE.match(node.value.id) is not None
        )

    def _declare_attr(self, node):
        """Record the type of an `@name: type` annotation."""
        name = node.target.attr
        self.cur_line = node.lineno
        ann = node.annotation
        if not (isinstance(ann, ast.Name) and ann.id in BY_NAME):
            self.err(f"@{name}: unknown type (use one of {', '.join(BY_NAME)})", node)
        t = BY_NAME[ann.id]
        known = KNOWN_ATTRS.get(name)
        if known is not None and known != t:
            self.err(f"@{name} is a {known}, it can't be declared as {t}", node)
        if name in SPECIAL_NAMES:
            self.err(f"@{name} is read-only and can't be declared", node)
        old = self.declared.setdefault(name, t)
        if old != t:
            self.err(f"@{name} is declared both as {old} and as {t}", node)

    def _attr_type(self, name, node, expect=None):
        """Declared type, else the built-in attribute's type, else the expected type, else float."""
        if name in OLD_NAMES and name not in self.declared:
            self.err(f"@{name} is now @{OLD_NAMES[name]} (Toast uses Blender's attribute names)",
                     node)  # fmt: skip
        if name in self.declared:
            return self.declared[name]
        if name in KNOWN_ATTRS:
            return KNOWN_ATTRS[name]
        if expect is not None and expect in BY_NAME.values():
            return expect
        return FLOAT

    def _check_attr_consistent(self, inp, name, t, node, domain="point"):
        old = self.attr_types.setdefault((inp, name, domain), t)
        if old != t:
            self.err(f"attribute '{name}' is used both as {old} and as {t}", node)

    def bind(self, inp, name, t, snapshot, read=False, write=False, domain="point"):
        key = (inp, name, snapshot, domain)
        b = self.bindings.get(key)
        if b is None:
            b = Binding(len(self.bindings), name, t, inp, snapshot, domain)
            self.bindings[key] = b
        b.read |= read
        b.write |= write
        self.inputs_used.add(inp)
        return b

    def attr_ref(self, node, write=False, read=True, expect=None):
        """Resolve ``_A.name`` / ``_A_f.name``. Returns E for its value at element i."""
        raw = node.attr
        if raw in SPECIAL_NAMES:
            t, code = self._special_attr(raw, node)
            if write:
                self.err(f"@{raw} is read-only", node)
            return E(code, t)
        if raw.startswith("opinput"):
            self.err(f"@{raw}: read other inputs with point_attr(1, name, @index)", node)
        domain = RUN_DOMAIN[self.run_over]
        if domain is None:
            self.err(
                f"@{raw}: Run Over Geometry runs once for the whole geometry, so it has no @ "
                "attributes; read with point_attr() or face_attr() and create with add_point()",
                node,
            )
        if self.func is not None:
            self.err(
                f"@{raw} can't be used inside def {self.func['name']}(); "
                "pass the value as an argument",
                node,
            )
        name = raw
        t = self._attr_type(name, node, expect)
        self._check_attr_consistent(0, name, t, node, domain)
        b = self.bind(0, name, t, snapshot=False, read=read, write=write, domain=domain)
        return E(f"{b.var}[i]", t)

    def _special_attr(self, raw, node):
        """Type and code of a read-only context attribute such as @ptnum or @Frame."""
        if raw in TIME_ATTRS:
            self.uses_time = True
            return TIME_ATTRS[raw]
        if self.run_over == "geometry":
            self.err(f"@{raw} is not available with Run Over Geometry", node)
        if raw == "index":
            return INT, "int32_t(i)"
        return INT, "int32_t(c->domain_size)"

    # ------------------------------------------------------------------ conversions

    def coerce(self, e, target, node, what="value"):
        if e.type == target:
            return e.code
        if target == FLOAT and e.type in (INT, BOOL):
            if e.const is not None and not isinstance(e.const, bool):
                return float_lit(float(e.const))
            return f"float({e.code})"
        if target == INT and e.type == BOOL:
            return f"int32_t({e.code})"
        if target == POINTREF and e.type == INT:
            return f"int64_t({e.code})"
        self.err(f"{what}: expected {target}, got {e.type}", node)

    def truth(self, node):
        e = self.expr(node)
        if e.type == BOOL:
            return e.code
        if e.type in (INT, FLOAT):
            return f"toast::truth({e.code})"
        if e.type == HIT:
            self.err("a hit can't be used as a condition, use its .hit field", node)
        self.err(f"a {e.type} can't be used as a condition", node)

    def _num(self, e, node, what):
        if e.type not in (FLOAT, INT, BOOL):
            self.err(f"{what}: expected a number, got {e.type}", node)

    def _const_int(self, node, what, lo=None, hi=None):
        e = self.expr(node)
        if e.type != INT or e.const is None:
            self.err(f"{what} must be a constant integer", node)
        if (lo is not None and e.const < lo) or (hi is not None and e.const > hi):
            self.err(f"{what} must be between {lo} and {hi}", node)
        return e.const

    def _const_str(self, node, what):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            self.err(f"{what} must be a constant string", node)
        return node.value

    def _input_arg(self, node, fname):
        return self._const_int(node, f"{fname}(): the input number", 0, MAX_INPUTS - 1)

    # ------------------------------------------------------------------ expressions

    def expr(self, node, expect=None):
        method = getattr(self, f"expr_{type(node).__name__}", None)
        if method is None:
            self.err(f"{type(node).__name__} expressions are not supported", node)
        return method(node, expect)

    def expr_Constant(self, node, expect):
        v = node.value
        if isinstance(v, bool):
            return E("true" if v else "false", BOOL, v)
        if isinstance(v, int):
            if not INT32_MIN <= v <= INT32_MAX:
                self.err(f"integer {v} does not fit in 32 bits", node)
            return E(str(v), INT, v)
        if isinstance(v, float):
            if not math.isfinite(v):
                self.err("infinite or NaN constants are not supported", node)
            return E(float_lit(v), FLOAT, v)
        if isinstance(v, str):
            self.err("strings are only supported as names in param() and point_attr()", node)
        self.err(f"constant {v!r} is not supported", node)

    def expr_Name(self, node, expect):
        name = node.id
        if name in self.locals:
            return E(f"v_{name}", self.locals[name].type)
        if ATTR_OBJ_RE.match(name):
            self.err("'@' must be followed directly by an attribute name", node)
        if name in BUILTINS or name in self.defs:
            self.err(f"'{name}' is a function, call it with ()", node)
        if name in self.assigned_names and self.func is None:
            self.err(f"'{name}' is used before it is assigned", node)
        self.err(f"name '{name}' is not defined", node)

    def expr_Attribute(self, node, expect):
        if self._is_attr(node):
            return self.attr_ref(node, expect=expect)
        if isinstance(node.value, ast.Name) and node.value.id == "math":
            if node.attr in MATH_CONSTANTS:
                v = MATH_CONSTANTS[node.attr]
                return E(float_lit(v), FLOAT, v)
            self.err(f"math.{node.attr} is not supported here", node)
        base = self.expr(node.value)
        if base.type in RECORDS:
            fields = RECORDS[base.type]
            if node.attr not in fields:
                self.err(f"a {base.type} has no field '.{node.attr}' (it has "
                         f"{', '.join(fields)})", node)  # fmt: skip
            return E(f"({base.code}).{node.attr}", fields[node.attr])
        if base.type in PROPERTIES:
            props = PROPERTIES[base.type]
            if node.attr not in props:
                self.err(f"a {base.type} has no property '.{node.attr}' (it has "
                         f"{', '.join(props)})", node)  # fmt: skip
            t, code = props[node.attr]
            return E(code.format(base.code), t)
        if base.type.is_array:
            self.err(f"a list has no '.{node.attr}': lists have a fixed size in Toast, create "
                     "them with [value] * count", node)  # fmt: skip
        return self._swizzle(base, node.attr, node)

    def _swizzle(self, base, letters, node):
        if not base.type.is_vec:
            self.err(f"a {base.type} has no attribute '.{letters}'", node)
        sets = ("xyzw", "rgba")
        comps = None
        for s in sets:
            if all(ch in s for ch in letters):
                comps = [s.index(ch) for ch in letters]
                break
        if comps is None or not 1 <= len(comps) <= 4:
            self.err(f"'.{letters}' is not a valid swizzle", node)
        if max(comps) >= base.type.ncomp:
            self.err(f"'.{letters}' is out of range for a {base.type}", node)
        if len(comps) == 1:
            return E(f"({base.code}).{'xyzw'[comps[0]]}", FLOAT)
        n = len(comps)
        args = ", ".join(str(k) for k in comps)
        return E(f"toast::swz{n}<{args}>({base.code})", VECS[n])

    def expr_Subscript(self, node, expect):
        base = self.expr(node.value)
        if base.type.is_array:
            return E(f"({base.code}).get({self._array_index(node.slice)})", array_parts(base.type)[0])
        if not base.type.is_vec:
            self.err(f"a {base.type} can't be indexed", node)
        k = self._const_int(node.slice, "a vector index", 0, base.type.ncomp - 1)
        return E(f"({base.code}).{'xyzw'[k]}", FLOAT)

    def _sequence(self, node, expect):
        elts = node.elts
        if expect is not None and expect.is_vec and len(elts) == expect.ncomp:
            t = expect
        elif 2 <= len(elts) <= 4:
            t = VECS[len(elts)]
        else:
            self.err(
                f"a tuple of {len(elts)} values can't be used here "
                "(tuples of 2 to 4 numbers become vectors)",
                node,
            )
        parts = []
        const = []
        for el in elts:
            e = self.expr(el)
            self._num(e, el, "vector component")
            parts.append(self.coerce(e, FLOAT, el))
            const.append(e.const)
        c = tuple(const) if all(x is not None for x in const) else None
        return E(f"{t.cpp}({', '.join(parts)})", t, c)

    expr_Tuple = _sequence

    def expr_List(self, node, expect):
        """A list literal is a fixed-size array, except where a vector is expected (so
        `@position = [0, 0, 1]` keeps working)."""
        if expect is not None and expect.is_vec and len(node.elts) == expect.ncomp:
            return self._sequence(node, expect)
        if not node.elts:
            self.err("an empty list has no size: create a list with [value] * count", node)
        if len(node.elts) > ARRAY_MAX:
            self.err(f"lists can hold at most {ARRAY_MAX} values", node)
        want = array_parts(expect)[0] if expect is not None and expect.is_array else None
        es = [self.expr(el, want) for el in node.elts]
        t = want or self._list_element_type(es, node)
        parts = [self.coerce(e, t, el, "list value") for e, el in zip(es, node.elts)]
        at = array_type(t, len(es))
        return E(f"{at.cpp}{{{{{', '.join(parts)}}}}}", at)

    def _list_element_type(self, es, node):
        nums = (FLOAT, INT, BOOL)
        if all(e.type in nums for e in es):
            if any(e.type == FLOAT for e in es):
                return FLOAT
            return INT if any(e.type == INT for e in es) else BOOL
        t = es[0].type
        if t not in ARRAY_ELEMENTS:
            self.err(f"a list can't hold a {t}", node)
        for e in es:
            if e.type != t:
                self.err(f"all values of a list must have the same type, got {t} and {e.type}", node)
        return t

    def _list_fill(self, node, value_node, count_node, expect):
        """[value] * count: a list of `count` copies of `value`."""
        want = array_parts(expect)[0] if expect is not None and expect.is_array else None
        e = self.expr(value_node, want)
        t = want or e.type
        if t not in ARRAY_ELEMENTS:
            self.err(f"a list can't hold a {e.type}", node)
        n = self._const_int(count_node, "the size of a list ([value] * count)", 1, ARRAY_MAX)
        at = array_type(t, n)
        return E(f"{at.cpp}::filled({self.coerce(e, t, value_node, 'list value')})", at)

    def _array_index(self, node):
        e = self.expr(node)
        if e.type not in (INT, BOOL):
            self.err(f"a list index must be an int, got {e.type}", node)
        return self.coerce(e, INT, node)

    def expr_UnaryOp(self, node, expect):
        if isinstance(node.op, ast.Not):
            return E(f"(!{self.truth(node.operand)})", BOOL)
        e = self.expr(node.operand, expect)
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            if e.type == BOOL:
                e = E(f"int32_t({e.code})", INT, None if e.const is None else int(e.const))
            if e.type not in (INT, FLOAT) and not e.type.is_vec:
                self.err(f"unary minus is not defined for a {e.type}", node)
            if isinstance(node.op, ast.UAdd):
                return e
            const = None
            if isinstance(e.const, (int, float)):
                const = -e.const
            elif isinstance(e.const, tuple):
                const = tuple(-x for x in e.const)
            if e.type == FLOAT and const is not None:
                return E(float_lit(const), FLOAT, const)
            if e.type == INT and const is not None:
                if const < INT32_MIN:
                    self.err("integer out of range", node)
                return E(f"({const})", INT, const)
            return E(f"(-{e.code})", e.type, const)
        if isinstance(node.op, ast.Invert):
            if e.type != INT:
                self.err(f"'~' needs an int, got {e.type}", node)
            return E(f"(~{e.code})", INT)
        self.err("unsupported unary operator", node)

    def expr_BinOp(self, node, expect):
        if isinstance(node.op, ast.MatMult):
            self.err("'@' matrix multiplication is not supported", node)
        op = BINOPS.get(type(node.op))
        if isinstance(node.op, ast.Mult):
            for lst, count in ((node.left, node.right), (node.right, node.left)):
                if isinstance(lst, ast.List) and len(lst.elts) == 1:
                    return self._list_fill(node, lst.elts[0], count, expect)
        l = self.expr(node.left, expect)
        r = self.expr(node.right, expect)
        return self.binop(op, l, r, node)

    def binop(self, op, l, r, node):
        for e in (l, r):
            if e.type in (POINTREF, NONE) or e.type.is_array or e.type in RECORDS:
                self.err(f"'{op}' can't be used with a {e.type}", node)
        if l.type in (QUAT, MAT4) or r.type in (QUAT, MAT4):
            if op == "*" and l.type == r.type:
                return E(f"({l.code} * {r.code})", l.type)
            if l.type == MAT4 and r.type == VEC3:
                self.err("use transform_point(m, p) or transform_direction(m, d) to transform "
                         "a vector by a mat4", node)  # fmt: skip
            if l.type == QUAT and r.type == VEC3:
                self.err("use rotate(q, v) to rotate a vector by a quat", node)
            self.err(f"'{op}' between {l.type} and {r.type} is not supported (a quat or mat4 "
                     "can only be multiplied by another of its kind)", node)  # fmt: skip
        if l.type.is_vec or r.type.is_vec:
            if op in ("&", "|", "^", "<<", ">>"):
                self.err(f"'{op}' is not defined for vectors", node)
            if l.type.is_vec and r.type.is_vec and l.type != r.type:
                self.err(f"'{op}' between {l.type} and {r.type}: sizes differ", node)
            vt = l.type if l.type.is_vec else r.type
            if op in ("+", "-", "*", "/"):
                lc = l.code if l.type.is_vec else self.coerce(l, FLOAT, node)
                rc = r.code if r.type.is_vec else self.coerce(r, FLOAT, node)
                return E(f"({lc} {op} {rc})", vt)
            lc = l.code if l.type.is_vec else f"{vt.cpp}({self.coerce(l, FLOAT, node)})"
            rc = r.code if r.type.is_vec else f"{vt.cpp}({self.coerce(r, FLOAT, node)})"
            fn = {"%": "toast::pymod", "//": "toast::floordiv", "**": "toast::pow"}[op]
            return E(f"{fn}({lc}, {rc})", vt)

        lt = INT if l.type == BOOL else l.type
        rt = INT if r.type == BOOL else r.type
        lc_i = self.coerce(l, INT, node) if l.type == BOOL else l.code
        rc_i = self.coerce(r, INT, node) if r.type == BOOL else r.code
        if op in ("&", "|", "^", "<<", ">>"):
            if lt != INT or rt != INT:
                self.err(f"'{op}' needs ints, got {l.type} and {r.type}", node)
            if op == "<<":
                return E(f"toast::shl({lc_i}, {rc_i})", INT)
            if op == ">>":
                return E(f"toast::shr({lc_i}, {rc_i})", INT)
            return E(f"({lc_i} {op} {rc_i})", INT)
        if lt == INT and rt == INT:
            if op in ("+", "-", "*"):
                return E(f"({lc_i} {op} {rc_i})", INT)
            if op == "/":
                return E(f"({self.coerce(l, FLOAT, node)} / {self.coerce(r, FLOAT, node)})", FLOAT)
            if op == "//":
                return E(f"toast::floordiv({lc_i}, {rc_i})", INT)
            if op == "%":
                return E(f"toast::pymod({lc_i}, {rc_i})", INT)
            if op == "**":
                if isinstance(r.const, int) and r.const >= 0:
                    return E(f"toast::ipow({lc_i}, {rc_i})", INT)
                lc, rc = self.coerce(l, FLOAT, node), self.coerce(r, FLOAT, node)
                return E(f"toast::pow({lc}, {rc})", FLOAT)
        lc, rc = self.coerce(l, FLOAT, node), self.coerce(r, FLOAT, node)
        if op in ("+", "-", "*", "/"):
            return E(f"({lc} {op} {rc})", FLOAT)
        fn = {"%": "toast::pymod", "//": "toast::floordiv", "**": "toast::pow"}[op]
        return E(f"{fn}({lc}, {rc})", FLOAT)

    def expr_BoolOp(self, node, expect):
        op = " && " if isinstance(node.op, ast.And) else " || "
        return E("(" + op.join(self.truth(v) for v in node.values) + ")", BOOL)

    def expr_Compare(self, node, expect):
        parts = []
        left = self.expr(node.left)
        for op, comp in zip(node.ops, node.comparators):
            cop = CMPOPS.get(type(op))
            if cop is None:
                self.err("only <, <=, >, >=, == and != comparisons are supported", node)
            right = self.expr(comp)
            for e in (left, right):
                if e.type not in (FLOAT, INT, BOOL):
                    self.err(f"a {e.type} can't be compared (no vector comparisons)", node)
            if FLOAT in (left.type, right.type):
                lc, rc = self.coerce(left, FLOAT, node), self.coerce(right, FLOAT, node)
            elif left.type == right.type:
                lc, rc = left.code, right.code
            else:
                lc, rc = self.coerce(left, INT, node), self.coerce(right, INT, node)
            parts.append(f"({lc} {cop} {rc})")
            left = right
        if len(parts) == 1:
            return E(parts[0], BOOL)
        return E("(" + " && ".join(parts) + ")", BOOL)

    def expr_IfExp(self, node, expect):
        cond = self.truth(node.test)
        a = self.expr(node.body, expect)
        b = self.expr(node.orelse, expect)
        t = self._unify(a, b, node)
        return E(f"({cond} ? {self.coerce(a, t, node)} : {self.coerce(b, t, node)})", t)

    def _unify(self, a, b, node):
        if a.type == b.type:
            return a.type
        nums = (FLOAT, INT, BOOL)
        if a.type in nums and b.type in nums:
            return FLOAT if FLOAT in (a.type, b.type) else INT
        self.err(f"both branches must have the same type, got {a.type} and {b.type}", node)

    # ------------------------------------------------------------------ calls

    def expr_Call(self, node, expect):
        f = node.func
        if isinstance(f, ast.Name):
            name = f.id
            if name in self.locals:
                self.err(f"'{name}' is a variable, not a function", node)
        elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "math":
            return self._math_module_call(f.attr, node)
        elif (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
              and f.value.id in self.locals):  # fmt: skip
            t = self.locals[f.value.id].type
            if t.is_array:
                self.err(f"{f.value.id}.{f.attr}(): lists have a fixed size in Toast and no "
                         "methods; create them with [value] * count", node)  # fmt: skip
            self.err(f"a {t} has no method .{f.attr}()", node)
        elif isinstance(f, ast.Attribute) and self._dotted(f.value) is not None:
            prefix = self._dotted(f.value)
            module = self.modules[self.cur_module]["aliases"].get(prefix)
            if module is None:
                self.err(f"'{prefix}' is not an imported library", node)
            fdef = self.modules[module]["own"].get(f.attr)
            if fdef is None:
                self.err(f"{module} has no def {f.attr}()", node)
            return self._call_helper(fdef, node)
        else:
            self.err("only builtin functions can be called", node)
        if name in self.defs:
            return self._call_helper(self.defs[name], node)
        if name in OLD_FUNCTIONS:
            self.err(f"{name}() is now {OLD_FUNCTIONS[name]}()", node)
        if name in LOOP_FUNCTIONS:
            self.err(f"{name}() can only be used as the iterable of a for loop", node)
        handler = getattr(self, f"call_{name}", None)
        if handler is None:
            if name in UNARY_MATH:
                return self._unary_math(name, node)
            self.err(f"'{name}' is not a Toast builtin", node)
        return handler(node, expect)

    def _args(self, node, fname, n_min, n_max=None, kw=()):
        n_max = n_min if n_max is None else n_max
        for k in node.keywords:
            if k.arg not in kw:
                self.err(f"{fname}() has no argument '{k.arg}'", node)
        if any(isinstance(a, ast.Starred) for a in node.args):
            self.err("*args is not supported", node)
        if not n_min <= len(node.args) <= n_max:
            want = str(n_min) if n_min == n_max else f"{n_min} to {n_max}"
            self.err(f"{fname}() takes {want} arguments, got {len(node.args)}", node)
        return node.args

    def _float_or_vec(self, e, node, fname):
        if e.type.is_vec or e.type == FLOAT:
            return e.code, e.type
        if e.type in (INT, BOOL):
            return self.coerce(e, FLOAT, node), FLOAT
        self.err(f"{fname}() needs a number or vector, got {e.type}", node)

    def _unary_math(self, name, node, to_int=False):
        (a,) = self._args(node, name, 1)
        e = self.expr(a)
        if name == "abs" and e.type in (INT, BOOL):
            return E(f"toast::abs({self.coerce(e, INT, node)})", INT)
        code, t = self._float_or_vec(e, node, name)
        out = E(f"toast::{name}({code})", t)
        if to_int:
            if t != FLOAT:
                self.err(f"math.{name}() needs a number", node)
            return E(f"toast::to_int({out.code})", INT)
        return out

    def _math_module_call(self, attr, node):
        if attr in MATH_MODULE_UNARY:
            return self._unary_math(MATH_MODULE_UNARY[attr], node)
        if attr in MATH_MODULE_TO_INT:
            return self._unary_math(attr, node, to_int=True)
        if attr in MATH_MODULE_BINARY:
            return self._binary_float(MATH_MODULE_BINARY[attr], node)
        self.err(f"math.{attr}() is not supported", node)

    def _binary_float(self, name, node):
        a, b = self._args(node, name, 2)
        ea, eb = self.expr(a), self.expr(b)
        ca, ta = self._float_or_vec(ea, node, name)
        cb, tb = self._float_or_vec(eb, node, name)
        if ta.is_vec and tb.is_vec and ta != tb:
            self.err(f"{name}(): sizes differ ({ta} and {tb})", node)
        if not ta.is_vec and tb.is_vec:
            ca = f"{tb.cpp}({ca})"
        t = ta if ta.is_vec else tb
        return E(f"toast::{name}({ca}, {cb})", t)

    def call_pow(self, node, expect):
        return self._binary_float("pow", node)

    def call_atan2(self, node, expect):
        return self._binary_float("atan2", node)

    def call_fmod(self, node, expect):
        return self._binary_float("fmod", node)

    def _minmax(self, name, node):
        a, b = self._args(node, name, 2)
        ea, eb = self.expr(a), self.expr(b)
        if ea.type in (INT, BOOL) and eb.type in (INT, BOOL):
            return E(
                f"toast::{name}({self.coerce(ea, INT, node)}, {self.coerce(eb, INT, node)})", INT
            )
        return self._binary_float(name, node)

    def call_min(self, node, expect):
        return self._minmax("min", node)

    def call_max(self, node, expect):
        return self._minmax("max", node)

    def call_clamp(self, node, expect):
        x, lo, hi = self._args(node, "clamp", 3)
        ex, elo, ehi = self.expr(x), self.expr(lo), self.expr(hi)
        if all(e.type in (INT, BOOL) for e in (ex, elo, ehi)):
            args = ", ".join(self.coerce(e, INT, node) for e in (ex, elo, ehi))
            return E(f"toast::clamp({args})", INT)
        cx, tx = self._float_or_vec(ex, node, "clamp")
        bounds = []
        for e, n in ((elo, lo), (ehi, hi)):
            if e.type.is_vec:
                if e.type != tx:
                    self.err(f"clamp(): bounds must be numbers or a {tx}", n)
                bounds.append(e.code)
            else:
                bounds.append(self.coerce(e, FLOAT, n))
        if elo.type.is_vec != ehi.type.is_vec:
            self.err("clamp(): both bounds must be numbers or both vectors", node)
        return E(f"toast::clamp({cx}, {bounds[0]}, {bounds[1]})", tx)

    def call_lerp(self, node, expect):
        a, b, t = self._args(node, "lerp", 3)
        ea = self.expr(a, expect)
        eb = self.expr(b, ea.type if ea.type.is_vec else expect)
        ty = ea.type if ea.type.is_vec else (eb.type if eb.type.is_vec else FLOAT)
        if ty.is_vec:
            if not (ea.type == ty and eb.type == ty):
                self.err(f"lerp(): a and b must both be {ty}", node)
            ca, cb = ea.code, eb.code
        else:
            ca, cb = self.coerce(ea, FLOAT, a), self.coerce(eb, FLOAT, b)
        ct = self.coerce(self.expr(t), FLOAT, t, "lerp() amount")
        return E(f"toast::lerp({ca}, {cb}, {ct})", ty)

    def _floats(self, node, fname, n):
        args = self._args(node, fname, n)
        return [self.coerce(self.expr(a), FLOAT, a, f"{fname}() argument") for a in args]

    def call_map_range(self, node, expect):
        """Blender's Map Range node (linear, clamped)."""
        return E(f"toast::fit({', '.join(self._floats(node, 'map_range', 5))})", FLOAT)

    def call_smoothstep(self, node, expect):
        return E(f"toast::smoothstep({', '.join(self._floats(node, 'smoothstep', 3))})", FLOAT)

    def _vec_args(self, node, fname, n, only=None):
        args = self._args(node, fname, n)
        es = [self.expr(args[0])]
        for a in args[1:]:
            es.append(self.expr(a, es[0].type))
        for e, a in zip(es, args):
            if not e.type.is_vec or (only is not None and e.type != only):
                self.err(f"{fname}() needs {only or 'vector'} arguments, got {e.type}", a)
            if e.type != es[0].type:
                self.err(f"{fname}(): sizes differ ({es[0].type} and {e.type})", a)
        return es

    def call_dot(self, node, expect):
        a, b = self._vec_args(node, "dot", 2)
        return E(f"toast::dot({a.code}, {b.code})", FLOAT)

    def call_cross(self, node, expect):
        a, b = self._vec_args(node, "cross", 2, only=VEC3)
        return E(f"toast::cross({a.code}, {b.code})", VEC3)

    def call_length(self, node, expect):
        (a,) = self._vec_args(node, "length", 1)
        return E(f"toast::length({a.code})", FLOAT)

    def call_distance(self, node, expect):
        a, b = self._vec_args(node, "distance", 2)
        return E(f"toast::distance({a.code}, {b.code})", FLOAT)

    def call_normalize(self, node, expect):
        if len(node.args) == 1 and not node.keywords:
            e = self.expr(node.args[0])
            if e.type == QUAT:
                return E(f"toast::normalize({e.code})", QUAT)
        (a,) = self._vec_args(node, "normalize", 1)
        return E(f"toast::normalize({a.code})", a.type)

    def call_int(self, node, expect):
        (a,) = self._args(node, "int", 1)
        e = self.expr(a)
        if e.type == INT:
            return e
        if e.type == BOOL:
            return E(self.coerce(e, INT, node), INT)
        if e.type == FLOAT:
            return E(f"toast::to_int({e.code})", INT)
        self.err(f"int() of a {e.type} is not supported", node)

    def call_float(self, node, expect):
        (a,) = self._args(node, "float", 1)
        e = self.expr(a)
        self._num(e, a, "float()")
        return E(self.coerce(e, FLOAT, node), FLOAT)

    def call_bool(self, node, expect):
        (a,) = self._args(node, "bool", 1)
        return E(self.truth(a), BOOL)

    def _vec_ctor(self, n, node):
        t = VECS[n]
        args = self._args(node, f"vec{n}", 1, n)
        if len(args) == 1:
            e = self.expr(args[0], t)
            if e.type == t:
                return e
            if e.type in (FLOAT, INT, BOOL):
                return E(f"{t.cpp}({self.coerce(e, FLOAT, node)})", t)
            self.err(f"vec{n}() of a {e.type} is not supported", node)
        if len(args) != n:
            self.err(f"vec{n}() takes 1 or {n} numbers, got {len(args)}", node)
        parts = []
        for a in args:
            e = self.expr(a)
            self._num(e, a, f"vec{n}() component")
            parts.append(self.coerce(e, FLOAT, a))
        return E(f"{t.cpp}({', '.join(parts)})", t)

    def call_vec2(self, node, expect):
        return self._vec_ctor(2, node)

    def call_vec3(self, node, expect):
        return self._vec_ctor(3, node)

    def call_vec4(self, node, expect):
        return self._vec_ctor(4, node)

    def _noise_pos(self, node, fname, a):
        e = self.expr(a)
        code, t = self._float_or_vec(e, node, fname)
        return code

    def call_noise(self, node, expect):
        (a,) = self._args(node, "noise", 1)
        return E(f"toast::noise({self._noise_pos(node, 'noise', a)})", FLOAT)

    def call_signed_noise(self, node, expect):
        (a,) = self._args(node, "signed_noise", 1)
        return E(f"toast::snoise({self._noise_pos(node, 'signed_noise', a)})", FLOAT)

    def call_fbm(self, node, expect):
        names = ("detail", "roughness", "lacunarity")
        defaults = {"detail": 2.0, "roughness": 0.5, "lacunarity": 2.0}
        args = self._args(node, "fbm", 1, 4, kw=names)
        given = dict(zip(names, args[1:]))
        for k in node.keywords:
            if k.arg in given:
                self.err(f"fbm() got '{k.arg}' twice", node)
            given[k.arg] = k.value
        parts = [self._noise_pos(node, "fbm", args[0])]
        for n in names:
            if n in given:
                parts.append(self.coerce(self.expr(given[n]), FLOAT, given[n], f"fbm() {n}"))
            else:
                parts.append(float_lit(defaults[n]))
        return E(f"toast::fbm({', '.join(parts)})", FLOAT)

    def call_hash01(self, node, expect):
        (a,) = self._args(node, "hash01", 1)
        e = self.expr(a)
        if e.type == BOOL:
            return E(f"toast::rand({self.coerce(e, INT, node)})", FLOAT)
        if e.type in (INT, FLOAT) or e.type.is_vec:
            return E(f"toast::rand({e.code})", FLOAT)
        self.err(f"hash01() of a {e.type} is not supported", node)

    def call_voronoi(self, node, expect):
        """Blender's Voronoi Texture (3D, F1, Euclidean, detail 0): a record with .distance,
        .color and .position of the nearest cell."""
        args = self._args(node, "voronoi", 1, 2, kw=("randomness",))
        pos = self.coerce(self.expr(args[0], VEC3), VEC3, args[0], "voronoi() position")
        rnode = args[1] if len(args) == 2 else next(
            (k.value for k in node.keywords if k.arg == "randomness"), None)
        if len(args) == 2 and node.keywords:
            self.err("voronoi() got 'randomness' twice", node)
        rnd = "1.0f" if rnode is None else self.coerce(self.expr(rnode), FLOAT, rnode,
                                                         "voronoi() randomness")  # fmt: skip
        return E(f"toast::voronoi({pos}, {rnd})", VORONOI)

    def call_random(self, node, expect):
        a, b = self._args(node, "random", 2)
        ea, eb = self.expr(a), self.expr(b)
        ca = self.coerce(ea, INT, a, "random() id")
        cb = self.coerce(eb, INT, b, "random() seed")
        return E(f"toast::random({ca}, {cb})", FLOAT)

    def call_curl_noise(self, node, expect):
        (a,) = self._args(node, "curl_noise", 1)
        p = self.coerce(self.expr(a, VEC3), VEC3, a, "curl_noise() position")
        return E(f"toast::curl_noise({p})", VEC3)

    def call_len(self, node, expect):
        (a,) = self._args(node, "len", 1)
        e = self.expr(a)
        if e.type.is_array:
            n = array_parts(e.type)[1]
            return E(str(n), INT, n)
        if e.type.is_vec:
            return E(str(e.type.ncomp), INT, e.type.ncomp)
        self.err(f"len() of a {e.type} is not supported", node)

    # ---- rotations and matrices

    def _typed(self, node, t, what):
        e = self.expr(node, t)
        if t == FLOAT:
            return self.coerce(e, FLOAT, node, what)
        if e.type != t:
            self.err(f"{what}: expected a {t}, got {e.type}", node)
        return e.code

    def call_quat(self, node, expect):
        args = self._args(node, "quat", 0, 4)
        if not args:
            return E("toast::quat()", QUAT)
        if len(args) != 4:
            self.err("quat() takes no arguments (no rotation) or 4 numbers w, x, y, z; see "
                     "quat_axis_angle() and quat_euler()", node)  # fmt: skip
        parts = [self._typed(a, FLOAT, "quat() component") for a in args]
        return E(f"toast::quat({', '.join(parts)})", QUAT)

    def call_mat4(self, node, expect):
        self._args(node, "mat4", 0)
        return E("toast::float4x4()", MAT4)

    def call_quat_axis_angle(self, node, expect):
        a, b = self._args(node, "quat_axis_angle", 2)
        axis = self._typed(a, VEC3, "quat_axis_angle() axis")
        angle = self._typed(b, FLOAT, "quat_axis_angle() angle")
        return E(f"toast::quat_axis_angle({axis}, {angle})", QUAT)

    def call_quat_euler(self, node, expect):
        (a,) = self._args(node, "quat_euler", 1)
        return E(f"toast::quat_euler({self._typed(a, VEC3, 'quat_euler() angles')})", QUAT)

    def call_quat_between(self, node, expect):
        a, b = self._args(node, "quat_between", 2)
        va = self._typed(a, VEC3, "quat_between() from")
        vb = self._typed(b, VEC3, "quat_between() to")
        return E(f"toast::quat_between({va}, {vb})", QUAT)

    def call_rotate(self, node, expect):
        a, b = self._args(node, "rotate", 2)
        q = self._typed(a, QUAT, "rotate() rotation")
        v = self._typed(b, VEC3, "rotate() vector")
        return E(f"toast::rotate({q}, {v})", VEC3)

    def call_slerp(self, node, expect):
        a, b, t = self._args(node, "slerp", 3)
        qa = self._typed(a, QUAT, "slerp() a")
        qb = self._typed(b, QUAT, "slerp() b")
        return E(f"toast::slerp({qa}, {qb}, {self._typed(t, FLOAT, 'slerp() amount')})", QUAT)

    def call_inverse(self, node, expect):
        (a,) = self._args(node, "inverse", 1)
        e = self.expr(a)
        if e.type not in (QUAT, MAT4):
            self.err(f"inverse() needs a quat or mat4, got {e.type}", node)
        return E(f"toast::inverse({e.code})", e.type)

    def call_to_euler(self, node, expect):
        (a,) = self._args(node, "to_euler", 1)
        return E(f"toast::to_euler({self._typed(a, QUAT, 'to_euler() rotation')})", VEC3)

    def call_transpose(self, node, expect):
        (a,) = self._args(node, "transpose", 1)
        return E(f"toast::transpose({self._typed(a, MAT4, 'transpose() matrix')})", MAT4)

    def call_transform_point(self, node, expect):
        a, b = self._args(node, "transform_point", 2)
        m = self._typed(a, MAT4, "transform_point() matrix")
        return E(f"toast::transform_point({m}, {self._typed(b, VEC3, 'transform_point() point')})",
                 VEC3)  # fmt: skip

    def call_transform_direction(self, node, expect):
        a, b = self._args(node, "transform_direction", 2)
        m = self._typed(a, MAT4, "transform_direction() matrix")
        d = self._typed(b, VEC3, "transform_direction() direction")
        return E(f"toast::transform_direction({m}, {d})", VEC3)

    def call_mat4_translation(self, node, expect):
        (a,) = self._args(node, "mat4_translation", 1)
        return E(f"toast::mat4_translation({self._typed(a, VEC3, 'mat4_translation()')})", MAT4)

    def call_mat4_rotation(self, node, expect):
        (a,) = self._args(node, "mat4_rotation", 1)
        return E(f"toast::mat4_rotation({self._typed(a, QUAT, 'mat4_rotation()')})", MAT4)

    def _scale_arg(self, node, what):
        e = self.expr(node, VEC3)
        if e.type in (FLOAT, INT, BOOL):
            return f"toast::float3({self.coerce(e, FLOAT, node)})"
        if e.type != VEC3:
            self.err(f"{what}: expected a number or vec3, got {e.type}", node)
        return e.code

    def call_mat4_scale(self, node, expect):
        (a,) = self._args(node, "mat4_scale", 1)
        return E(f"toast::mat4_scale({self._scale_arg(a, 'mat4_scale()')})", MAT4)

    def call_mat4_compose(self, node, expect):
        a, b, c = self._args(node, "mat4_compose", 3)
        loc = self._typed(a, VEC3, "mat4_compose() location")
        rot = self._typed(b, QUAT, "mat4_compose() rotation")
        scale = self._scale_arg(c, "mat4_compose() scale")
        return E(f"toast::mat4_compose({loc}, {rot}, {scale})", MAT4)

    # ---- parameters, attributes, host

    def _check_domain(self, fname, inp, domain, node):
        """Input 0 is the geometry being run on: some domains don't exist in some modes."""
        if inp != 0 or domain in INPUT0_DOMAINS[self.run_over]:
            return
        if self.run_over == "instances":
            self.err(f"{fname}(): with Run Over Instances, input 0 has only instances (use "
                     "@attributes or instance_attr())", node)  # fmt: skip
        self.err(f"{fname}(): with Run Over {self.run_over.capitalize()}, input 0 has no "
                 f"{DOMAIN_WORD[domain]}", node)  # fmt: skip

    def _check_mode(self, fname, modes, node, hint=""):
        if self.run_over not in modes:
            self.err(f"{fname}() doesn't work with Run Over {self.run_over.capitalize()}{hint}", node)

    def call_param(self, node, expect):
        args = self._args(node, "param", 2, kw=("min", "max"))
        name = self._const_str(args[0], "param(): the parameter name")
        if not IDENT_RE.match(name):
            self.err(f"param(): '{name}' is not a valid parameter name (letters, digits, _)", node)
        d = self.expr(args[1])
        if d.const is None:
            self.err("param(): the default must be a constant (number, bool or tuple)", node)
        if d.type == VECS[2]:
            self.err("param(): vec2 parameters are not supported, use 3 or 4 numbers", node)
        kws = {}
        for k in node.keywords:
            ke = self.expr(k.value)
            if ke.const is None or ke.type not in (INT, FLOAT):
                self.err(f"param(): {k.arg}= must be a constant number", node)
            kws[k.arg] = ke.const
        old = self.params.get(name)
        if old is None:
            default = [float(x) for x in d.const] if isinstance(d.const, tuple) else d.const
            self.params[name] = Param(name, d.type, default, kws.get("min"), kws.get("max"))
        elif old.type != d.type:
            self.err(f"param('{name}') was first used with a {old.type} default, here a {d.type}", node)
        if self.func is not None:
            self.func["uses_ch"] = True
        if d.type == BOOL:
            return E(f"(p.p_{name} != 0)", BOOL)
        return E(f"p.p_{name}", d.type)

    def call_output(self, node, expect):
        """output(name, value): a socket on the node with `value` for each element of the Run Over
        domain (an anonymous attribute, like the Top output of Extrude Mesh)."""
        a_name, a_value = self._args(node, "output", 2)
        name = self._const_str(a_name, "output(): the output name")
        if not IDENT_RE.match(name):
            self.err(f"output(): '{name}' is not a valid output name (letters, digits, _)", node)
        if self.func is not None:
            self.err(f"output() can't be used inside def {self.func['name']}(); return the value "
                     "and call output() outside", node)  # fmt: skip
        domain = RUN_DOMAIN[self.run_over]
        if domain is None:
            self.err("output(): Run Over Geometry runs once and has no elements to give values "
                     "to; store an attribute with set_point_attr() instead", node)  # fmt: skip
        old = self.outputs.get(name)
        value = self.expr(a_value, old[0] if old else None)
        if old is None:
            t = value.type
            if t == VECS[2]:
                self.err("output(): vec2 outputs are not supported, use a vec3", node)
            if t.name not in OUTPUT_SOCKETS:
                self.err(f"output(): a {t} can't be an output (use {', '.join(OUTPUT_SOCKETS)})",
                         node)  # fmt: skip
            self.outputs[name] = (t, node.lineno)
        t = self.outputs[name][0]
        key = (0, ("output", name), False, domain)
        b = self.bindings.get(key)
        if b is None:
            b = Binding(len(self.bindings), name, t, 0, False, domain, output=True)
            self.bindings[key] = b
        b.write = True
        code = self.coerce(value, t, a_value, f"output('{name}')")
        return E(f"{b.var}[i] = {code}", NONE)

    def _element_read(self, fname, domain, node, expect):
        """point_attr()/face_attr(): an attribute of element j of an input, by constant name."""
        if self.func is not None:
            self.err(
                f"{fname}() can't be used inside def {self.func['name']}(); "
                "read the value outside and pass it as an argument",
                node,
            )
        a_inp, a_name, a_j = self._args(node, fname, 3)
        inp = self._input_arg(a_inp, fname)
        self._check_domain(fname, inp, domain, node)
        name = self._const_str(a_name, f"{fname}(): the attribute name")
        if not IDENT_RE.match(name):
            self.err(f"{fname}(): '{name}' is not a valid attribute name", node)
        if name in SPECIAL_NAMES:
            self.err(f"{fname}(): '{name}' can't be read with {fname}()", node)
        t = self._attr_type(name, node, expect)
        self._check_attr_consistent(inp, name, t, node, domain)
        j = self.expr(a_j)
        if j.type == POINTREF:
            self.err(f"{fname}(): elements added in this run can't be read", node)
        jc = self.coerce(j, INT, a_j, f"{fname}() index")
        # The kernel writes run-domain attributes of input 0 in place: read a copy of those.
        snapshot = (
            inp == 0 and name in self.written_attrs and domain == RUN_DOMAIN[self.run_over]
        )
        b = self.bind(inp, name, t, snapshot=snapshot, read=True, domain=domain)
        return E(f"toast::rd({b.var}, {b.size_var}, {jc})", t)

    def call_point_attr(self, node, expect):
        return self._element_read("point_attr", "point", node, expect)

    def call_face_attr(self, node, expect):
        return self._element_read("face_attr", "face", node, expect)

    def call_curve_attr(self, node, expect):
        return self._element_read("curve_attr", "curve", node, expect)

    def call_instance_attr(self, node, expect):
        return self._element_read("instance_attr", "instance", node, expect)

    def call_curve_count(self, node, expect):
        (a,) = self._args(node, "curve_count", 1)
        inp = self._input_arg(a, "curve_count")
        self._check_domain("curve_count", inp, "curve", node)
        self.host_uses.add("ncurves")
        self.inputs_used.add(inp)
        return E(f"toast::ncurves(c, {inp})", INT)

    def call_remove_curve(self, node, expect):
        (a,) = self._args(node, "remove_curve", 1)
        self._check_mode("remove_curve", ("points", "curves", "geometry"), node)
        e = self.expr(a)
        if e.type != INT:
            self.err(f"remove_curve() needs a curve number, got {e.type}", a)
        self.uses_cmd = True
        return E(f"toast::remove_curve(c, i, {e.code})", NONE)

    def call_remove_instance(self, node, expect):
        (a,) = self._args(node, "remove_instance", 1)
        self._check_mode("remove_instance", ("instances",), node)
        e = self.expr(a)
        if e.type != INT:
            self.err(f"remove_instance() needs an instance number, got {e.type}", a)
        self.uses_cmd = True
        return E(f"toast::remove_point(c, i, {e.code})", NONE)

    def call_face_count(self, node, expect):
        (a,) = self._args(node, "face_count", 1)
        inp = self._input_arg(a, "face_count")
        self.host_uses.add("nprims")
        self.inputs_used.add(inp)
        return E(f"toast::nprims(c, {inp})", INT)

    def call_remove_face(self, node, expect):
        (a,) = self._args(node, "remove_face", 1)
        self._check_domain("remove_face", 0, "face", node)
        e = self.expr(a)
        if e.type != INT:
            self.err(f"remove_face() needs a face number, got {e.type}", a)
        self.uses_cmd = True
        return E(f"toast::remove_prim(c, i, {e.code})", NONE)

    def call_point_count(self, node, expect):
        (a,) = self._args(node, "point_count", 1)
        inp = self._input_arg(a, "point_count")
        self.host_uses.add("npoints")
        self.inputs_used.add(inp)
        return E(f"toast::npoints(c, {inp})", INT)

    def call_nearest_point(self, node, expect):
        a_inp, a_pos, a_r = self._args(node, "nearest_point", 3)
        inp = self._input_arg(a_inp, "nearest_point")
        pos = self.coerce(self.expr(a_pos, VEC3), VEC3, a_pos, "nearest_point() position")
        r = self.coerce(self.expr(a_r), FLOAT, a_r, "nearest_point() radius")
        self.host_uses.add("nearpoints")
        self.inputs_used.add(inp)
        self.nearpoints_inputs.add(inp)
        return E(f"toast::nearpoint(c, {inp}, {pos}, {r})", INT)

    def _corner_query(self, fname, node):
        a_inp, a_corner = self._args(node, fname, 2)
        inp = self._input_arg(a_inp, fname)
        corner = self.coerce(self.expr(a_corner), INT, a_corner, f"{fname}() corner")
        self.host_uses.add(fname)
        self.inputs_used.add(inp)
        return E(f"toast::{fname}(c, {inp}, {corner})", INT)

    def call_corner_point(self, node, expect):
        return self._corner_query("corner_point", node)

    def call_corner_face(self, node, expect):
        return self._corner_query("corner_face", node)

    def _set_attr(self, fname, domain, node):
        a_j, a_name, a_value = self._args(node, fname, 3)
        self._check_domain(fname, 0, domain, node)
        name = self._const_str(a_name, f"{fname}(): the attribute name")
        if not IDENT_RE.match(name):
            self.err(f"{fname}(): '{name}' is not a valid attribute name", node)
        if name in SPECIAL_NAMES:
            self.err(f"{fname}(): '{name}' is read-only", node)
        j = self.expr(a_j)
        # A point added in this run (add_point's handle): the host writes it once it exists.
        if j.type == POINTREF and domain != "point":
            self.err(f"{fname}(): needs a face index, not a point added with add_point()", node)
        jc = j.code if j.type == POINTREF else self.coerce(j, INT, a_j, f"{fname}() index")
        typed = name in self.declared or name in KNOWN_ATTRS
        value = self.expr(a_value, self._attr_type(name, node) if typed else None)
        if value.type not in BY_NAME.values():
            self.err(f"{fname}(): '{name}' can't hold a {value.type}", node)
        t = self._attr_type(name, node, value.type)
        self._check_attr_consistent(0, name, t, node, domain)
        b = self.bind(0, name, t, snapshot=False, write=True, domain=domain)
        self.uses_cmd = True
        vc = self.coerce(value, t, a_value, f"{fname}() value")
        return E(f"toast::set_attr<{t.cpp}>(c, i, {b.index}, {jc}, {vc})", NONE)

    def call_set_point_attr(self, node, expect):
        return self._set_attr("set_point_attr", "point", node)

    def call_set_face_attr(self, node, expect):
        return self._set_attr("set_face_attr", "face", node)

    def _surface_input(self, fname, a_inp):
        inp = self._input_arg(a_inp, fname)
        self.host_uses.add(fname if fname != "sample_nearest_surface" else "closest_point")
        self.inputs_used.add(inp)
        self.surface_inputs.add(inp)
        return inp

    def call_ray_cast(self, node, expect):
        args = self._args(node, "ray_cast", 3, 4)
        inp = self._surface_input("ray_cast", args[0])
        origin = self.coerce(self.expr(args[1], VEC3), VEC3, args[1], "ray_cast() origin")
        direction = self.coerce(self.expr(args[2], VEC3), VEC3, args[2], "ray_cast() direction")
        dist = (
            self.coerce(self.expr(args[3]), FLOAT, args[3], "ray_cast() max distance")
            if len(args) == 4 else "3.4e38f"
        )  # fmt: skip
        return E(f"toast::ray_cast(c, {inp}, {origin}, {direction}, {dist})", HIT)

    def call_closest_point(self, node, expect):
        args = self._args(node, "closest_point", 2, 3)
        inp = self._surface_input("closest_point", args[0])
        pos = self.coerce(self.expr(args[1], VEC3), VEC3, args[1], "closest_point() position")
        dist = (
            self.coerce(self.expr(args[2]), FLOAT, args[2], "closest_point() max distance")
            if len(args) == 3 else "3.4e38f"
        )  # fmt: skip
        return E(f"toast::closest_point(c, {inp}, {pos}, {dist})", HIT)

    def call_sample_nearest_surface(self, node, expect):
        """Like Blender's Sample Nearest Surface: a point attribute of `input`, interpolated at
        the surface point closest to `position`."""
        if self.func is not None:
            self.err(f"sample_nearest_surface() can't be used inside def {self.func['name']}()",
                     node)  # fmt: skip
        a_inp, a_name, a_pos = self._args(node, "sample_nearest_surface", 3)
        inp = self._surface_input("sample_nearest_surface", a_inp)
        name = self._const_str(a_name, "sample_nearest_surface(): the attribute name")
        if not IDENT_RE.match(name) or name in SPECIAL_NAMES:
            self.err(f"sample_nearest_surface(): '{name}' can't be sampled", node)
        t = self._attr_type(name, node, expect)
        if t not in (FLOAT, VECS[2], VEC3, VECS[4]):
            self.err(f"sample_nearest_surface(): '{name}' is a {t}, only float and vector "
                     "attributes can be interpolated", node)  # fmt: skip
        self._check_attr_consistent(inp, name, t, node, "point")
        snapshot = inp == 0 and name in self.written_attrs and RUN_DOMAIN[self.run_over] == "point"
        b = self.bind(inp, name, t, snapshot=snapshot, read=True, domain="point")
        pos = self.coerce(self.expr(a_pos, VEC3), VEC3, a_pos, "sample_nearest_surface() position")
        hit = f"toast::closest_point(c, {inp}, {pos}, 3.4e38f)"
        return E(f"toast::interp_hit({b.var}, {b.size_var}, {hit})", t)

    def call_add_point(self, node, expect):
        (a,) = self._args(node, "add_point", 1)
        self._check_mode("add_point", ("points", "faces", "edges", "corners", "curves", "geometry"),
                         node)  # fmt: skip
        pos = self.coerce(self.expr(a, VEC3), VEC3, a, "add_point() position")
        self.uses_cmd = True
        return E(f"toast::add_point(c, i, {pos})", POINTREF)

    def _point_refs(self, fname, nodes):
        pts = []
        for el in nodes:
            e = self.expr(el)
            if e.type not in (INT, POINTREF):
                self.err(f"{fname}(): points must be ints or add_point() results, got {e.type}", el)
            pts.append(e.code)
        return pts

    def call_add_face(self, node, expect):
        (a,) = self._args(node, "add_face", 1)
        self._check_domain("add_face", 0, "face", node)
        if not isinstance(a, (ast.Tuple, ast.List)) or len(a.elts) < 3:
            if isinstance(a, (ast.Tuple, ast.List)) and len(a.elts) == 2:
                self.err("add_face() needs 3 or more points; use add_edge(a, b) for 2", node)
            self.err("add_face() takes a tuple of 3 or more points, like add_face((a, b, c))", node)
        pts = self._point_refs("add_face", a.elts)
        self.uses_cmd = True
        return E(f"toast::add_prim(c, i, {', '.join(pts)})", NONE)

    def call_add_curve(self, node, expect):
        """add_curve((a, b, ...)), or add_curve(points, count) with a list of point numbers."""
        args = self._args(node, "add_curve", 1, 2)
        self._check_mode("add_curve", ("points", "curves", "geometry"), node)
        self.uses_cmd = True
        self.builds_curves = True
        if len(args) == 2:
            lst = self.expr(args[0])
            elem = array_parts(lst.type)[0] if lst.type.is_array else None
            if elem != INT:
                self.err("add_curve(points, count): points must be a list of point numbers "
                         f"(list[int]), got {lst.type}", args[0])  # fmt: skip
            n = self.coerce(self.expr(args[1]), INT, args[1], "add_curve() count")
            return E(f"toast::add_curve_list(c, i, {lst.code}, {n})", NONE)
        (a,) = args
        if not isinstance(a, (ast.Tuple, ast.List)) or len(a.elts) < 1:
            self.err("add_curve() takes a tuple of points, like add_curve((a, b, c)), or a list of "
                     "point numbers and a count: add_curve(points, n)", node)  # fmt: skip
        pts = self._point_refs("add_curve", a.elts)
        return E(f"toast::add_curve(c, i, {', '.join(pts)})", NONE)

    def call_extend_curve(self, node, expect):
        a_curve, a_pos = self._args(node, "extend_curve", 2)
        self._check_mode("extend_curve", ("points", "curves", "geometry"), node)
        curve = self.expr(a_curve)
        if curve.type != INT:
            self.err(f"extend_curve() needs a curve number, got {curve.type}", a_curve)
        pos = self.coerce(self.expr(a_pos, VEC3), VEC3, a_pos, "extend_curve() position")
        self.uses_cmd = True
        self.builds_curves = True
        return E(f"toast::extend_curve(c, i, {curve.code}, {pos})", POINTREF)

    def call_add_edge(self, node, expect):
        args = self._args(node, "add_edge", 2)
        self._check_domain("add_edge", 0, "edge", node)
        pts = self._point_refs("add_edge", args)
        self.uses_cmd = True
        return E(f"toast::add_prim(c, i, {', '.join(pts)})", NONE)

    def call_remove_point(self, node, expect):
        (a,) = self._args(node, "remove_point", 1)
        if self.run_over == "instances":
            self.err("remove_point(): with Run Over Instances, use remove_instance()", node)
        e = self.expr(a)
        if e.type not in (INT, POINTREF):
            self.err(f"remove_point() needs a point number, got {e.type}", a)
        self.uses_cmd = True
        return E(f"toast::remove_point(c, i, {e.code})", NONE)

    # ------------------------------------------------------------------ statements

    def stmt(self, s):
        self.cur_line = s.lineno
        method = getattr(self, f"stmt_{type(s).__name__}", None)
        if method is None:
            self.err(f"'{type(s).__name__}' statements are not supported", s)
        method(s)

    def block(self, body):
        self.depth += 1
        for s in body:
            self.stmt(s)
        self.depth -= 1

    def stmt_Expr(self, s):
        v = s.value
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            return  # docstring-like comment
        e = self.expr(v)
        if e.type == NONE:
            self.line(f"{e.code};")
        else:
            self.line(f"(void)({e.code});")

    def stmt_Pass(self, s):
        pass

    def stmt_Import(self, s):
        for alias in s.names:
            if alias.name == "math" and alias.asname is None:
                continue
            if alias.name.startswith(LIB_PACKAGE + "."):
                continue  # Resolved before compiling, see _load_module.
            self.err(
                f"import {alias.name}: only 'import math' and 'import {LIB_PACKAGE}.<name>' "
                "are supported",
                s,
            )

    def stmt_ImportFrom(self, s):
        if (s.module or "").startswith(LIB_PACKAGE + ".") and s.level == 0:
            return  # Resolved before compiling, see _load_module.
        self.err(f"'from ... import' only works with {LIB_PACKAGE} libraries", s)

    def stmt_FunctionDef(self, s):
        self.err("def helpers must be defined at the top level, not inside other code", s)

    # ---- def helpers

    @staticmethod
    def _dotted(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        parts.append(node.id)
        return ".".join(reversed(parts))

    def _parse_library(self, module):
        if module not in self.libs:
            self.err(f"can't find library {module}")
        try:
            return ast.parse(desugar(self.libs[module]))
        except ToastError as ex:
            raise ToastError(ex.message, ex.line, module) from None
        except SyntaxError as ex:
            raise ToastError(f"syntax error: {ex.msg}", ex.lineno, module) from None

    def _load_module(self, module, tree=None):
        """Register a module's defs and imports. Libraries may contain only defs and imports."""
        if module in self.modules:
            return
        self.modules[module] = {"names": {}, "own": {}, "aliases": {}}
        saved = (self.cur_module, self.cur_line)
        self.cur_module = module
        try:
            if tree is None:
                tree = self._parse_library(module)
                for st in tree.body:
                    is_doc = isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)
                    if not (is_doc or isinstance(st, (ast.FunctionDef, ast.Import, ast.ImportFrom, ast.Pass))):
                        self.err("a toast_lib library may only contain def helpers and imports", st)
            self._collect_defs(tree, module)
            self._collect_imports(tree, module)
        finally:
            self.cur_module, self.cur_line = saved

    def _collect_imports(self, tree, module):
        mod = self.modules[module]
        for st in tree.body:
            self.cur_line = st.lineno
            if isinstance(st, ast.Import):
                for alias in st.names:
                    if not alias.name.startswith(LIB_PACKAGE + "."):
                        continue
                    self._load_module(alias.name)
                    mod["aliases"][alias.asname or alias.name] = alias.name
            elif isinstance(st, ast.ImportFrom) and (st.module or "").startswith(LIB_PACKAGE + "."):
                self._load_module(st.module)
                lib = self.modules[st.module]["own"]
                for alias in st.names:
                    if alias.name == "*":
                        for n, fdef in lib.items():
                            mod["names"].setdefault(n, fdef)
                        continue
                    if alias.name not in lib:
                        self.err(f"{st.module} has no def {alias.name}()", st)
                    local = alias.asname or alias.name
                    if local in mod["names"] and mod["names"][local] is not lib[alias.name]:
                        self.err(f"'{local}' is already defined", st)
                    mod["names"][local] = lib[alias.name]

    def _collect_defs(self, tree, module):
        for s in tree.body:
            if not isinstance(s, ast.FunctionDef):
                continue
            self.cur_line = s.lineno
            a = s.args
            if s.decorator_list:
                self.err("decorators are not supported", s)
            if a.vararg or a.kwarg or a.kwonlyargs or a.posonlyargs or a.defaults:
                self.err(f"def {s.name}(): only plain positional arguments are supported", s)
            if s.name in BUILTINS:
                self.err(f"def {s.name}(): '{s.name}' is a Toast builtin", s)
            if s.name in self.defs:
                self.err(f"def {s.name}() is defined twice", s)
            if s.name.startswith("_") or not IDENT_RE.match(s.name) or not s.name.isascii():
                self.err(f"def {s.name}(): invalid name", s)
            for arg in a.args:
                ann = arg.annotation
                if ann is not None and not (isinstance(ann, ast.Name) and ann.id in BY_NAME):
                    self.err(f"def {s.name}(): unknown type annotation on '{arg.arg}'", s)
            s.toast_module = module
            s.toast_qualname = s.name if module == MAIN else f"{module}.{s.name}"
            self.modules[module]["names"][s.name] = s
            self.modules[module]["own"][s.name] = s

    def _call_helper(self, fdef, node):
        name = fdef.toast_qualname
        if node.keywords:
            self.err(f"{name}(): keyword arguments are not supported", node)
        params = fdef.args.args
        if len(node.args) != len(params):
            self.err(f"{name}() takes {len(params)} arguments, got {len(node.args)}", node)
        args, types = [], []
        for p, a in zip(params, node.args):
            want = BY_NAME[p.annotation.id] if p.annotation is not None else None
            e = self.expr(a, want)
            if e.type == NONE:
                self.err(f"{name}(): argument '{p.arg}' has no value", a)
            t = want or e.type
            args.append(self.coerce(e, t, a, f"{name}() argument '{p.arg}'"))
            types.append(t)
        key = (fdef.toast_qualname, tuple(types))
        if key not in self.helpers:
            if name in self.compiling:
                self.err(f"{name}() calls itself: recursion is not supported", node)
            self._compile_helper(fdef, types, key)
        cpp_name, ret = self.helpers[key]
        return E(f"{cpp_name}({', '.join(['c', 'i'] + args)})", ret)

    def _compile_helper(self, fdef, types, key):
        saved = (self.locals, self.lines, self.depth, self.loop_depth, self.func, self.cur_line,
                 self.cur_module)  # fmt: skip
        self.locals, self.lines, self.depth, self.loop_depth = {}, [], 1, 0
        self.cur_module = fdef.toast_module
        self.func = {"name": fdef.toast_qualname, "ret": None, "ret_line": None, "uses_ch": False}
        self.compiling.append(fdef.toast_qualname)
        try:
            names = [p.arg for p in fdef.args.args]
            for p, t in zip(fdef.args.args, types):
                self._declare(p.arg, t, fdef)
            for st in fdef.body:
                self.stmt(st)
            ret = self.func["ret"] or NONE
            body, local_vars, uses_ch = self.lines, self.locals, self.func["uses_ch"]
        finally:
            (self.locals, self.lines, self.depth, self.loop_depth, self.func, self.cur_line,
             self.cur_module) = saved  # fmt: skip
            self.compiling.pop()

        cpp_name = f"toast_fn_{fdef.name}_{len(self.helper_code)}"
        params = ", ".join(
            ["const ToastCtx *c", "const int64_t i"] + [f"{t.cpp} v_{n}" for n, t in zip(names, types)]
        )
        code = [f"/* def {fdef.toast_qualname}({', '.join(f'{n}: {t}' for n, t in zip(names, types))}) */"]
        code.append(f"[[maybe_unused]] static inline {ret.cpp} {cpp_name}({params})")
        code.append("{")
        code.append("  (void)c;")
        code.append("  (void)i;")
        if uses_ch:
            code.append("  const Params &p = *(const Params *)c->params;")
        for n, loc in local_vars.items():
            if n not in names:
                code.append(f"  {loc.type.cpp} v_{n} = {loc.type.zero};")
        code += body
        if ret != NONE:
            code.append(f"  return {ret.zero};")
        code.append("}")
        self.helper_code.append("\n".join(code))
        self.helpers[key] = (cpp_name, ret)

    def _declare(self, name, t, node):
        if t == NONE:
            self.err("this call returns nothing, it can't be assigned", node)
        if not name.isascii() or not IDENT_RE.match(name):
            self.err(f"'{name}': variable names must be ASCII letters, digits and _", node)
        if name in BUILTINS:
            self.err(f"'{name}' is a builtin function and can't be used as a variable", node)
        if name.startswith("_"):
            self.err(f"'{name}': names starting with '_' are reserved", node)
        self.locals[name] = _Local(t, node.lineno)

    def _assign_local(self, name, value, node):
        loc = self.locals.get(name)
        if loc is None:
            self._declare(name, value.type, node)
            loc = self.locals[name]
        elif loc.type != value.type and not (
            loc.type == FLOAT and value.type in (INT, BOOL) or loc.type == INT and value.type == BOOL
        ):
            self.err(
                f"can't assign a {value.type} to '{name}', which is a {loc.type} "
                f"(its type was fixed on line {loc.line})",
                node,
            )
        self.line(f"v_{name} = {self.coerce(value, loc.type, node)};")

    def _assign(self, target, value_node, node, aug=None):
        def value_for(cur, expect):
            if aug is None:
                return self.expr(value_node, expect)
            rhs = self.expr(value_node, expect if expect is not None and expect.is_vec else None)
            return self.binop(aug, cur, rhs, node)

        if isinstance(target, ast.Name):
            name = target.id
            loc = self.locals.get(name)
            if aug is not None and loc is None:
                self.err(f"'{name}' is used before it is assigned", node)
            cur = E(f"v_{name}", loc.type) if loc else None
            self._assign_local(name, value_for(cur, loc.type if loc else None), node)
            return
        if self._is_attr(target):
            name = target.attr
            typed = (
                name in self.declared or name in KNOWN_ATTRS or name in SPECIAL_NAMES
                or (0, name, RUN_DOMAIN[self.run_over]) in self.attr_types
            )  # fmt: skip
            if aug is None and not typed:
                # A new attribute without annotation takes the type of its first value.
                val = self.expr(value_node)
                if val.type not in BY_NAME.values():
                    self.err(f"@{name} can't hold a {val.type}", node)
                cur = self.attr_ref(target, write=True, read=False, expect=val.type)
            else:
                cur = self.attr_ref(target, write=True, read=aug is not None)
                val = value_for(cur, cur.type)
            self.line(f"{cur.code} = {self.coerce(val, cur.type, node, f'@{name}')};")
            return
        if isinstance(target, (ast.Attribute, ast.Subscript)):
            base_node = target.value
            if self._is_attr(base_node):
                base = self.attr_ref(base_node, write=True, read=True)
            elif isinstance(base_node, ast.Name) and base_node.id in self.locals:
                base = E(f"v_{base_node.id}", self.locals[base_node.id].type)
            elif isinstance(base_node, ast.Subscript):
                self.err("assign a whole list value, like a[i] = v, not one component of it "
                         "(copy it to a variable, change that, and assign it back)", node)  # fmt: skip
            else:
                self.err("only components of variables and attributes can be assigned", node)
            if isinstance(target, ast.Subscript) and base.type.is_array:
                if not isinstance(base_node, ast.Name):
                    self.err("only lists in variables can be changed", node)
                elem = array_parts(base.type)[0]
                idx = self._array_index(target.slice)
                cur = E(f"{base.code}.get({idx})", elem)
                val = value_for(cur, elem)
                self.line(f"{base.code}.at({idx}) = {self.coerce(val, elem, node)};")
                return
            if isinstance(target, ast.Attribute):
                if base.type in PROPERTIES:
                    self.err(f"the properties of a {base.type} are read-only", node)
                comp = self._swizzle(base, target.attr, node)
                if comp.type != FLOAT:
                    self.err("only one component can be assigned at a time, like v.x = 1", node)
            else:
                comp = self.expr_Subscript(ast.Subscript(value=base_node, slice=target.slice), None)
            val = value_for(comp, FLOAT)
            # comp.code is "(base).x"; assign through the same lvalue.
            self.line(f"{comp.code} = {self.coerce(val, FLOAT, node)};")
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            self.err("tuple unpacking is not supported", node)
        self.err("this can't be assigned to", node)

    def stmt_Assign(self, s):
        if len(s.targets) != 1:
            self.err("chained assignment (a = b = ...) is not supported", s)
        self._assign(s.targets[0], s.value, s)

    def stmt_AugAssign(self, s):
        op = BINOPS.get(type(s.op))
        if op is None:
            self.err("unsupported augmented assignment", s)
        self._assign(s.target, s.value, s, aug=op)

    def stmt_AnnAssign(self, s):
        if self._is_attr(s.target):
            # Declared in the prepass (`@name: type`); with a value it is also a write.
            if s.value is not None:
                self._assign(s.target, s.value, s)
            return
        if not isinstance(s.target, ast.Name):
            self.err("annotations are only supported on variables and @attributes", s)
        ann = s.annotation
        name = s.target.id
        if (isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name)
                and ann.value.id == "list"):  # fmt: skip
            elem = ann.slice
            if not (isinstance(elem, ast.Name) and elem.id in BY_NAME):
                self.err(f"list[...]: unknown element type (use one of {', '.join(BY_NAME)})", s)
            if s.value is None:
                self.err(f"'{name}: list[{elem.id}]' needs a value to give it a size, like "
                         f"[0] * 8", s)  # fmt: skip
            hint = array_type(BY_NAME[elem.id], 1)
            value = self.expr(s.value, hint)
            if not value.type.is_array or array_parts(value.type)[0] != BY_NAME[elem.id]:
                self.err(f"'{name}' is annotated list[{elem.id}], got a {value.type}", s)
            self._assign_local(name, value, s)
            return
        if not (isinstance(ann, ast.Name) and ann.id in BY_NAME):
            self.err(f"unknown type annotation (use one of {', '.join(BY_NAME)}, list[...])", s)
        t = BY_NAME[ann.id]
        loc = self.locals.get(name)
        if loc is not None and loc.type != t:
            self.err(f"'{name}' is already a {loc.type} (line {loc.line})", s)
        if loc is None:
            self._declare(name, t, s)
        if s.value is not None:
            self._assign_local(name, self.expr(s.value, t), s)

    def stmt_If(self, s):
        self.line(f"if ({self.truth(s.test)}) {{")
        self.block(s.body)
        orelse = s.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                nxt = orelse[0]
                self.cur_line = nxt.lineno
                self.line(f"}} else if ({self.truth(nxt.test)}) {{")
                self.block(nxt.body)
                orelse = nxt.orelse
            else:
                self.line("} else {")
                self.block(orelse)
                orelse = None
        self.line("}")

    def stmt_While(self, s):
        if s.orelse:
            self.err("while ... else is not supported", s)
        self.line(f"while ({self.truth(s.test)}) {{")
        self.loop_depth += 1
        self.block(s.body)
        self.loop_depth -= 1
        self.line("}")

    def _loop_var(self, target, node):
        if not isinstance(target, ast.Name):
            self.err("the loop variable must be a plain name", node)
        name = target.id
        loc = self.locals.get(name)
        if loc is None:
            self._declare(name, INT, node)
        elif loc.type != INT:
            self.err(f"loop variable '{name}' is a {loc.type}, it must be an int", node)
        return f"v_{name}"

    def stmt_For(self, s):
        if s.orelse:
            self.err("for ... else is not supported", s)
        it = s.iter
        if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name)):
            self._for_list(s, it)
            return
        if it.func.id == "range":
            self._for_range(s, it)
        elif it.func.id == "nearby_points":
            self._for_nearpoints(s, it)
        elif it.func.id == "face_points":
            self._for_primpoints(s, it)
        elif it.func.id in ("point_faces", "point_neighbors"):
            self._for_point_query(s, it)
        elif it.func.id == "curve_points":
            self._for_curve_points(s, it)
        elif it.func.id in OLD_FUNCTIONS:
            self.err(f"{it.func.id}() is now {OLD_FUNCTIONS[it.func.id]}()", s)
        elif it.func.id in self.defs or it.func.id in BUILTINS:
            self._for_list(s, it)
        else:
            self.err(f"'{it.func.id}' is not a Toast builtin", s)

    def _for_range(self, s, it):
        args = self._args(it, "range", 1, 3)
        es = [self.expr(a) for a in args]
        for e, a in zip(es, args):
            if e.type not in (INT, BOOL):
                self.err(f"range() needs ints, got {e.type}", a)
        codes = [self.coerce(e, INT, s) for e in es]
        step = 1
        if len(args) == 3:
            step = self._const_int(args[2], "range() step")
            if step == 0:
                self.err("range() step must not be zero", s)
        start, stop = ("0", codes[0]) if len(args) == 1 else (codes[0], codes[1])
        var = self._loop_var(s.target, s)
        t = self.new_tmp()
        cmp = "<" if step > 0 else ">"
        self.line("{")
        self.depth += 1
        self.line(f"const int32_t {t}_start = {start};")
        self.line(f"const int32_t {t}_stop = {stop};")
        self.line(f"for (int32_t {t} = {t}_start; {t} {cmp} {t}_stop; {t} += {step}) {{")
        self.depth += 1
        self.line(f"{var} = {t};")
        self.loop_depth += 1
        self.depth -= 1
        self.block(s.body)
        self.loop_depth -= 1
        self.line("}")
        self.depth -= 1
        self.line("}")

    def _for_nearpoints(self, s, it):
        a_inp, a_pos, a_r, a_max = self._args(it, "nearby_points", 4)
        inp = self._input_arg(a_inp, "nearby_points")
        pos = self.coerce(self.expr(a_pos, VEC3), VEC3, a_pos, "nearby_points() position")
        r = self.coerce(self.expr(a_r), FLOAT, a_r, "nearby_points() radius")
        mx = self._const_int(a_max, "nearby_points(): the maximum count", 1, NEARPOINTS_MAX_LIMIT)
        self.host_uses.add("nearpoints")
        self.inputs_used.add(inp)
        self.nearpoints_inputs.add(inp)
        var = self._loop_var(s.target, s)
        t = self.new_tmp()
        self.line("{")
        self.depth += 1
        self.line(f"int64_t {t}_buf[{mx}];")
        self.line(f"const int32_t {t}_n = toast::nearpoints(c, {inp}, {pos}, {r}, {mx}, {t}_buf);")
        self.line(f"for (int32_t {t} = 0; {t} < {t}_n; {t}++) {{")
        self.depth += 1
        self.line(f"{var} = int32_t({t}_buf[{t}]);")
        self.loop_depth += 1
        self.depth -= 1
        self.block(s.body)
        self.loop_depth -= 1
        self.line("}")
        self.depth -= 1
        self.line("}")

    def _for_list(self, s, it):
        """for x in <list>: x takes each value in order."""
        e = self.expr(it)
        if not e.type.is_array:
            self.err("for loops go over a list, range(), nearby_points(), face_points(), "
                     "curve_points(), point_faces() or point_neighbors()", s)  # fmt: skip
        elem, n = array_parts(e.type)
        if not isinstance(s.target, ast.Name):
            self.err("the loop variable must be a plain name", s)
        name = s.target.id
        loc = self.locals.get(name)
        if loc is None:
            self._declare(name, elem, s)
        elif loc.type != elem:
            self.err(f"loop variable '{name}' is a {loc.type}, the list holds {elem}", s)
        t = self.new_tmp()
        self.line("{")
        self.depth += 1
        self.line(f"const {e.type.cpp} {t}_list = {e.code};")
        self.line(f"for (int32_t {t} = 0; {t} < {n}; {t}++) {{")
        self.depth += 1
        self.line(f"v_{name} = {t}_list.v[{t}];")
        self.loop_depth += 1
        self.depth -= 1
        self.block(s.body)
        self.loop_depth -= 1
        self.line("}")
        self.depth -= 1
        self.line("}")

    def _for_curve_points(self, s, it):
        a_inp, a_curve, a_max = self._args(it, "curve_points", 3)
        inp = self._input_arg(a_inp, "curve_points")
        self._check_domain("curve_points", inp, "curve", it)
        curve = self.coerce(self.expr(a_curve), INT, a_curve, "curve_points() curve")
        mx = self._const_int(a_max, "curve_points(): the maximum count", 1, NEARPOINTS_MAX_LIMIT)
        self.host_uses.add("curve_points")
        self.inputs_used.add(inp)
        self._emit_index_loop(s, f"toast::curve_points(c, {inp}, {curve}, {mx}, {{buf}})", mx)

    def _for_primpoints(self, s, it):
        a_inp, a_prim, a_max = self._args(it, "face_points", 3)
        inp = self._input_arg(a_inp, "face_points")
        self._check_domain("face_points", inp, "face", it)
        prim = self.coerce(self.expr(a_prim), INT, a_prim, "face_points() face")
        mx = self._const_int(a_max, "face_points(): the maximum count", 1, NEARPOINTS_MAX_LIMIT)
        self.host_uses.add("primpoints")
        self.inputs_used.add(inp)
        var = self._loop_var(s.target, s)
        t = self.new_tmp()
        self.line("{")
        self.depth += 1
        self.line(f"int64_t {t}_buf[{mx}];")
        self.line(f"const int32_t {t}_n = toast::primpoints(c, {inp}, {prim}, {mx}, {t}_buf);")
        self.line(f"for (int32_t {t} = 0; {t} < {t}_n; {t}++) {{")
        self.depth += 1
        self.line(f"{var} = int32_t({t}_buf[{t}]);")
        self.loop_depth += 1
        self.depth -= 1
        self.block(s.body)
        self.loop_depth -= 1
        self.line("}")
        self.depth -= 1
        self.line("}")

    def _for_point_query(self, s, it):
        fname = it.func.id
        a_inp, a_pt, a_max = self._args(it, fname, 3)
        inp = self._input_arg(a_inp, fname)
        pt = self.coerce(self.expr(a_pt), INT, a_pt, f"{fname}() point")
        mx = self._const_int(a_max, f"{fname}(): the maximum count", 1, NEARPOINTS_MAX_LIMIT)
        self.host_uses.add(fname)
        self.inputs_used.add(inp)
        self._emit_index_loop(s, f"toast::{fname}(c, {inp}, {pt}, {mx}, {{buf}})", mx)

    def _emit_index_loop(self, s, call, mx):
        """for v in <host query filling a buffer of at most mx indices>: body"""
        var = self._loop_var(s.target, s)
        t = self.new_tmp()
        self.line("{")
        self.depth += 1
        self.line(f"int64_t {t}_buf[{mx}];")
        self.line(f"const int32_t {t}_n = {call.format(buf=f'{t}_buf')};")
        self.line(f"for (int32_t {t} = 0; {t} < {t}_n; {t}++) {{")
        self.depth += 1
        self.line(f"{var} = int32_t({t}_buf[{t}]);")
        self.loop_depth += 1
        self.depth -= 1
        self.block(s.body)
        self.loop_depth -= 1
        self.line("}")
        self.depth -= 1
        self.line("}")

    def stmt_Break(self, s):
        if self.loop_depth == 0:
            self.err("'break' outside a loop", s)
        self.line("break;")

    def stmt_Continue(self, s):
        if self.loop_depth == 0:
            self.err("'continue' outside a loop", s)
        self.line("continue;")

    def stmt_Return(self, s):
        f = self.func
        if f is None:
            if s.value is not None:
                self.err("return with a value is only allowed inside def helpers", s)
            self.uses_return = True  # Ends this element.
            self.line("goto toast_next;")
            return
        if s.value is None:
            if f["ret"] not in (None, NONE):
                self.err(f"{f['name']}() returns a {f['ret']} on line {f['ret_line']}", s)
            f["ret"], f["ret_line"] = NONE, s.lineno
            self.line("return;")
            return
        e = self.expr(s.value, f["ret"] if f["ret"] not in (None, NONE) else None)
        if e.type == NONE:
            self.err("this call returns nothing", s)
        if f["ret"] is None:
            f["ret"], f["ret_line"] = e.type, s.lineno
        elif f["ret"] == NONE:
            self.err(f"{f['name']}() returns nothing on line {f['ret_line']}", s)
        elif e.type != f["ret"] and not (f["ret"] == FLOAT and e.type in (INT, BOOL)):
            self.err(
                f"{f['name']}() returns a {f['ret']} on line {f['ret_line']} and a {e.type} here "
                "(convert one, e.g. with float())",
                s,
            )
        self.line(f"return {self.coerce(e, f['ret'], s)};")

    # ------------------------------------------------------------------ output

    def _params_layout(self):
        size = {INT: 4, FLOAT: 4, BOOL: 4, VECS[3]: 12, VECS[4]: 16}
        cpp = {INT: "int32_t", FLOAT: "float", BOOL: "int32_t"}
        off = 0
        fields = []
        for p in self.params.values():
            p.offset = off
            fields.append((cpp.get(p.type, p.type.cpp), p))
            off += size[p.type]
        return fields, off

    def _signature(self, params_size):
        attrs = []
        for b in sorted(self.bindings.values(), key=lambda b: b.index):
            access = ("r" if b.read else "") + ("w" if b.write else "")
            attrs.append(
                {
                    "name": b.name,
                    "type": b.type.name,
                    "type_code": b.type.abi,
                    "input": b.input,
                    "domain": b.domain,
                    "access": access or "r",
                    "create": b.write,
                    "snapshot": b.snapshot,
                    "output": b.output,
                }
            )
        params = [
            {
                "name": p.name,
                "type": p.type.name,
                "default": p.default,
                "min": p.min,
                "max": p.max,
                "offset": p.offset,
            }
            for p in self.params.values()
        ]
        return {
            "toast": VERSION,
            "abi": ABI_VERSION,
            "run_over": self.run_over,
            "attrs": attrs,
            "params": params,
            "params_size": params_size,
            "outputs": [{"name": n, "type": t.name, "socket": OUTPUT_SOCKETS[t.name]}
                        for n, (t, _line) in self.outputs.items()],  # fmt: skip
            "uses": {
                "cmd": self.uses_cmd,
                "curves": self.builds_curves,
                "time": self.uses_time,
                "host": sorted(self.host_uses | ({"cmd"} if self.uses_cmd else set())),
                "inputs": sorted(self.inputs_used | {0}),
                "nearpoints_inputs": sorted(self.nearpoints_inputs),
                "surface_inputs": sorted(self.surface_inputs),
            },
        }

    def _emit(self):
        fields, params_size = self._params_layout()
        sig = self._signature(params_size)
        sig_json = json.dumps(sig, sort_keys=True)
        out = [
            f"/* Generated by Toast {VERSION}. Do not edit: regenerated from the node's code. */",
            '#include "toast_rt.h"',
            "",
            "namespace {",
        ]
        if fields:
            out.append("struct Params {")
            for cpp, p in fields:
                out.append(f"  {cpp} p_{p.name};")
            out.append("};")
            for _, p in fields:
                out.append(f"static_assert(offsetof(Params, p_{p.name}) == {p.offset}, \"layout\");")
            out.append(f'static_assert(sizeof(Params) == {params_size}, "layout");')
        out.append(f'const char k_signature[] = R"TOASTSIG({sig_json})TOASTSIG";')
        for code in self.helper_code:
            out += ["", code]
        out += [
            "}  // namespace",
            "",
            "TOAST_EXPORT int32_t toast_abi_version()",
            "{",
            "  return TOAST_ABI_VERSION;",
            "}",
            "",
            "TOAST_EXPORT const char *toast_signature()",
            "{",
            "  return k_signature;",
            "}",
            "",
            "TOAST_EXPORT void toast_kernel(const ToastCtx *c)",
            "{",
        ]
        for b in sorted(self.bindings.values(), key=lambda b: b.index):
            const = "" if b.write else "const "
            out.append(f"  {const}{b.type.cpp} *{b.var} = ({const}{b.type.cpp} *)c->attrs[{b.index}].data;")
            out.append(f"  const int64_t {b.size_var} = c->attrs[{b.index}].size;")
            out.append(f"  (void){b.size_var};")
        if fields:
            out.append("  const Params &p = *(const Params *)c->params;")
        out.append("  for (int64_t k = c->begin; k < c->end; k++) {")
        out.append("    const int64_t i = c->indices ? c->indices[k] : k;")
        for name, loc in self.locals.items():
            out.append(f"    {loc.type.cpp} v_{name} = {loc.type.zero};")
        out += self.lines
        if self.uses_return:
            out.append("  toast_next:;")
        out += ["  }", "}", ""]
        return "\n".join(out), sig


def find_library_imports(source, module=MAIN):
    """Names of the toast_lib libraries ``source`` imports, with the line of each import."""
    try:
        tree = ast.parse(desugar(source))
    except ToastError as ex:
        raise ToastError(ex.message, ex.line, None if module == MAIN else module) from None
    except SyntaxError as ex:
        raise ToastError(f"syntax error: {ex.msg}", ex.lineno, None if module == MAIN else module) from None
    found = []
    for st in tree.body:
        if isinstance(st, ast.Import):
            found += [(a.name, st.lineno) for a in st.names if a.name.startswith(LIB_PACKAGE + ".")]
        elif isinstance(st, ast.ImportFrom) and (st.module or "").startswith(LIB_PACKAGE + "."):
            found.append((st.module, st.lineno))
    return found


def collect_libraries(source, resolver):
    """Resolve every library ``source`` needs, recursively: {module name: source}.

    ``resolver(module_name)`` returns the library's source, or None if it doesn't exist.
    """
    libs = {}
    todo = [(MAIN, source)]
    while todo:
        module, text = todo.pop()
        for lib, line in find_library_imports(text, module):
            if lib in libs:
                continue
            lib_source = resolver(lib) if resolver else None
            if lib_source is None:
                raise ToastError(
                    f"can't find library {lib} (a text named '{lib}' or a file in the library "
                    "folders)",
                    line,
                    None if module == MAIN else module,
                )
            libs[lib] = lib_source
            todo.append((lib, lib_source))
    return libs


def compile_source(source, run_over="points", libs=None):
    """Translate Toast source to C++. Returns CompiledSource(cpp, signature, desugared)."""
    return Compiler(source=source, run_over=run_over, libs=dict(libs or {})).compile()
