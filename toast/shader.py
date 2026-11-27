# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Toast code for the shader editor: a function run for every shading point (EEVEE).

The same language as the geometry node, without the parts that need geometry: no topology
changes, no queries, no lists, no quat/mat4. `@` attributes are what the shading point has:

- built-in: @position @normal @true_normal @incoming @parametric @backfacing (Geometry node),
  @generated @uv @object @camera @window @reflection (Texture Coordinate node), @color (the
  active color attribute), @time @frame (Scene Time);
- any other `@name` reads the attribute with that name (like the Attribute node), a float
  unless declared (`@name: vec3`, `vec4`).

param() inputs become input sockets, which can be linked: they differ per shading point.
output() values become output sockets. Attributes can't be written.

The compiler reuses the geometry compiler's checks and expressions and emits Blender's portable
shader dialect (``float3``, GLSL builtins) instead of C++: one function, called by the
ShaderNodeToast node through ``GPU_stack_link_source``, plus the runtime in ``shader_lib``.
"""

import ast
import hashlib
import json
import re
from dataclasses import dataclass

from . import shader_lib
from .compiler import BUILTINS, MAIN, UNARY_MATH, Compiler, E
from .errors import ToastError
from .sugar import desugar
from .types import BOOL, BY_NAME, FLOAT, INT, MAT4, NONE, QUAT, VEC3, VEC4, VECS, VORONOI
from .version import VERSION

# Built-in shading inputs: name -> type.
SHADING_INPUTS = {
    "position": VEC3, "normal": VEC3, "true_normal": VEC3, "incoming": VEC3,
    "parametric": VEC3, "backfacing": FLOAT, "generated": VEC3, "uv": VEC3, "object": VEC3,
    "camera": VEC3, "window": VEC3, "reflection": VEC3, "color": VEC3, "time": FLOAT,
    "frame": FLOAT,
}  # fmt: skip
# Types a named attribute can be read as, and how, from the float4 the material gets: the Attribute
# node's Fac (average of the first three), Vector, and the value with its alpha.
ATTRIBUTE_TYPES = (FLOAT, VEC3, VEC4)
ATTRIBUTE_READ = {FLOAT: "(({0}).x + ({0}).y + ({0}).z) / 3.0f", VEC3: "({0}).xyz", VEC4: "{0}"}
OUTPUT_TYPES = (FLOAT, INT, BOOL, VEC3, VEC4)
PARAM_TYPES = (FLOAT, INT, BOOL, VEC3, VEC4)

# Builtins that work per shading point: math, vectors, noise, param() and output().
SHADER_BUILTINS = set(UNARY_MATH) | {
    "pow", "atan2", "fmod", "min", "max", "clamp", "lerp", "map_range", "smoothstep", "dot",
    "cross", "length", "distance", "normalize", "int", "float", "bool", "vec2", "vec3", "vec4",
    "noise", "signed_noise", "fbm", "hash01", "random", "voronoi", "curl_noise", "param",
    "output", "range",
}  # fmt: skip
assert SHADER_BUILTINS <= BUILTINS

# C++ spellings the shader dialect writes differently (the compiler emits `toast::name`).
_DIALECT = [
    (re.compile(r"\btoast::float([234])\b"), r"float\1"),
    (re.compile(r"\btoast::"), "toast_"),
    (re.compile(r"\bint32_t\b"), "int"),
    # `(v_c).x = 1.0f` is fine in C++; GLSL is stricter about assigning to parenthesized names.
    (re.compile(r"\(([A-Za-z_][A-Za-z0-9_]*)\)\."), r"\1."),
]
_COMMENT = re.compile(r"/\*.*?\*/", re.S)

# Name of the generated function, replaced by its hash once the source is known.
_NAME = "TOAST_FN_NAME"


@dataclass
class ShaderSource:
    source: str  # GPU function (EEVEE)
    signature: dict
    desugared: str = ""
    # C++ for Cycles on the CPU: `toast_shader(const float *in, float *out)` (see _emit_cpu).
    cpu: str = ""


def to_dialect(code):
    for pattern, repl in _DIALECT:
        code = pattern.sub(repl, code)
    return code


class ShaderCompiler(Compiler):
    """``target`` "gpu": a function in the shader dialect (EEVEE). "cpu": C++ on toast_rt.h for
    Cycles on the CPU, compiled by the fork's built-in compiler."""

    HELPER_ARGS = ("p",)

    def __init__(self, source, libs=None, target="gpu"):
        super().__init__(source=source, run_over="shader", libs=dict(libs or {}))
        self.target = target
        # Shading inputs in first-use order: name -> (kind, type).
        self.shading = {}

    # ------------------------------------------------------------------ entry

    def compile(self):
        text = desugar(self.source)
        try:
            tree = ast.parse(text)
        except SyntaxError as ex:
            raise ToastError(f"syntax error: {ex.msg}", ex.lineno) from None
        self._prepass(tree)
        for name in sorted(self.written_attrs):
            raise ToastError(f"@{name}: shader code can't write attributes; give values to the "
                             "node's outputs with output(name, value)", self._first_write(tree, name))  # fmt: skip
        self._load_module(MAIN, tree)
        for s in tree.body:
            if isinstance(s, ast.FunctionDef):
                continue
            self.stmt(s)
        if self.target == "cpu":
            return ShaderSource(source="", signature={}, desugared=text, cpu=self._emit_cpu())
        source, sig = self._emit()
        return ShaderSource(source=source, signature=sig, desugared=text)

    def _first_write(self, tree, name):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                ts = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in ts:
                    for n in ast.walk(t):
                        if self._is_attr(n) and n.attr == name:
                            return node.lineno
        return None

    # ------------------------------------------------------------------ attributes

    def _declare_attr(self, node):
        name = node.target.attr
        ann = node.annotation
        self.cur_line = node.lineno
        if not (isinstance(ann, ast.Name) and ann.id in BY_NAME):
            self.err(f"@{name}: unknown type (use one of {', '.join(BY_NAME)})", node)
        t = BY_NAME[ann.id]
        if name in SHADING_INPUTS:
            if SHADING_INPUTS[name] != t:
                self.err(f"@{name} is a {SHADING_INPUTS[name]}, it can't be declared as {t}", node)
        elif t not in ATTRIBUTE_TYPES:
            self.err(f"@{name}: attributes are read as float, vec3 or vec4 in a shader", node)
        old = self.declared.setdefault(name, t)
        if old != t:
            self.err(f"@{name} is declared both as {old} and as {t}", node)

    def attr_ref(self, node, write=False, read=True, expect=None):
        name = node.attr
        if write:
            self.err(f"@{name}: shader code can't write attributes; give values to the node's "
                     "outputs with output(name, value)", node)  # fmt: skip
        if name in ("index", "count"):
            self.err(f"@{name} doesn't exist in a shader: the code runs for shading points, not "
                     "elements", node)  # fmt: skip
        if self.func is not None:
            self.err(f"@{name} can't be used inside def {self.func['name']}(); pass the value as "
                     "an argument", node)  # fmt: skip
        if name in SHADING_INPUTS:
            t = SHADING_INPUTS[name]
            kind = "builtin"
            var = f"s_{name}"
        else:
            t = self.declared.get(name)
            if t is None:
                t = expect if expect in ATTRIBUTE_TYPES else FLOAT
            kind = "attribute"
            var = f"a_{name}"
        old = self.shading.get(name)
        if old is None:
            self.shading[name] = (kind, t)
        elif old[1] != t:
            self.err(f"attribute '{name}' is used both as {old[1]} and as {t}", node)
        if name in ("time", "frame"):
            self.uses_time = True
        return E(var, t)

    # ------------------------------------------------------------------ restrictions

    def expr_Call(self, node, expect):
        f = node.func
        if isinstance(f, ast.Name) and f.id in BUILTINS and f.id not in SHADER_BUILTINS:
            if f.id not in self.locals and f.id not in self.defs:
                what = ("quat and mat4 aren't supported in shader code yet"
                        if f.id in ("quat", "mat4") or f.id.startswith(("quat_", "mat4_"))
                        or f.id in ("rotate", "slerp", "inverse", "to_euler", "transpose",
                                    "transform_point", "transform_direction")
                        else "there is no geometry in a shader, only the shading point")  # fmt: skip
                self.err(f"{f.id}() doesn't work in shader code: {what}", node)
        return super().expr_Call(node, expect)

    def _no_lists(self, node):
        self.err("lists aren't supported in shader code yet", node)

    def expr_List(self, node, expect):
        if expect is not None and expect.is_vec and len(node.elts) == expect.ncomp:
            return self._sequence(node, expect)
        self._no_lists(node)

    def _list_fill(self, node, value_node, count_node, expect):
        self._no_lists(node)

    def _declare(self, name, t, node):
        if t.is_array:
            self._no_lists(node)
        if t in (QUAT, MAT4):
            self.err("quat and mat4 aren't supported in shader code yet", node)
        super()._declare(name, t, node)

    def stmt_For(self, s):
        it = s.iter
        if not (isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range"):
            self.err("shader code loops over range() only", s)
        super().stmt_For(s)

    def call_param(self, node, expect):
        e = super().call_param(node, expect)
        name = node.args[0].value
        if self.params[name].type not in PARAM_TYPES:
            self.err(f"param(): a {self.params[name].type} can't be a shader input socket", node)
        return e

    def call_output(self, node, expect):
        a_name, a_value = self._args(node, "output", 2)
        name = self._const_str(a_name, "output(): the output name")
        if not re.match(r"[A-Za-z_][A-Za-z0-9_]*\Z", name):
            self.err(f"output(): '{name}' is not a valid output name (letters, digits, _)", node)
        if self.func is not None:
            self.err(f"output() can't be used inside def {self.func['name']}(); return the value "
                     "and call output() outside", node)  # fmt: skip
        old = self.outputs.get(name)
        value = self.expr(a_value, old[0] if old else None)
        if old is None:
            t = value.type
            if t == VECS[2]:
                self.err("output(): vec2 outputs are not supported, use a vec3", node)
            if t not in OUTPUT_TYPES:
                self.err(f"output(): a {t} can't be a shader output (use float, int, bool, vec3 "
                         "or vec4)", node)  # fmt: skip
            self.outputs[name] = (t, node.lineno)
        t = self.outputs[name][0]
        code = self.coerce(value, t, a_value, f"output('{name}')")
        return E(f"o_{name} = {code}", NONE)

    # ------------------------------------------------------------------ dialect hooks

    # The CPU target is C++ on toast_rt.h, like geometry kernels: the base class's spellings.

    def _field_code(self, base_code, field):
        if self.target == "cpu":
            return super()._field_code(base_code, field)
        return f"({base_code}).f_{field}"

    def _swizzle_code(self, base_code, comps):
        if self.target == "cpu":
            return super()._swizzle_code(base_code, comps)
        return f"({base_code}).{''.join('xyzw'[k] for k in comps)}"

    def _discard_code(self, code):
        if self.target == "cpu":
            return super()._discard_code(code)
        return f"{code};"

    def _return_main(self):
        # The CPU function writes its outputs at the end: jump there.
        return "goto toast_done;" if self.target == "cpu" else "return;"

    def _zero(self, t):
        if self.target == "cpu":
            return t.zero
        if t == VORONOI:
            return "toast_voronoi_zero()"
        return to_dialect(t.zero)

    def _helper_code(self, fdef, cpp_name, ret, names, types, body, local_vars, uses_ch):
        if self.target == "cpu":
            params = ", ".join(["const Params &p"] + [f"{t.cpp} v_{n}" for n, t in zip(names, types)])
            code = [f"[[maybe_unused]] static inline {ret.cpp} {cpp_name}({params})", "{",
                    "  (void)p;"]  # fmt: skip
        else:
            params = ", ".join([f"{_NAME}_P p"] + [f"{t.cpp} v_{n}" for n, t in zip(names, types)])
            code = [f"{ret.cpp} {cpp_name}({params})", "{"]
        for n, loc in local_vars.items():
            if n not in names:
                code.append(f"  {loc.type.cpp} v_{n} = {self._zero(loc.type)};")
        code += body
        if ret != NONE:
            code.append(f"  return {self._zero(ret)};")
        code.append("}")
        return "\n".join(code)

    # ------------------------------------------------------------------ output

    def _emit(self):
        params = list(self.params.values())
        inputs = list(self.shading.items())
        outputs = list(self.outputs.items())
        # Bool params arrive as bool; the compiler reads them as ints (`p.p_x != 0`).
        ptype = {BOOL: "int"}

        out = [f"struct {_NAME}_P {{"]
        for p in params:
            out.append(f"  {ptype.get(p.type, p.type.cpp)} p_{p.name};")
        if not params:
            out.append("  int unused;")
        out.append("};")
        for code in self.helper_code:
            out.append(code)
        args = [f"{p.type.cpp} in_{p.name}" for p in params]
        # Named attributes always arrive as a float4 (as for the Attribute node).
        args += [f"{t.cpp} s_{name}" if kind == "builtin" else f"float4 r_{name}"
                 for name, (kind, t) in inputs]  # fmt: skip
        args += [f"_ref({t.cpp}, o_{name})" for name, (t, _line) in outputs]
        out.append(f"void {_NAME}({', '.join(args)})")
        out.append("{")
        out.append(f"  {_NAME}_P p;")
        if not params:
            out.append("  p.unused = 0;")
        for p in params:
            value = f"(in_{p.name} ? 1 : 0)" if p.type == BOOL else f"in_{p.name}"
            out.append(f"  p.p_{p.name} = {value};")
        for name, (kind, t) in inputs:
            if kind == "attribute":
                out.append(f"  {t.cpp} a_{name} = {ATTRIBUTE_READ[t].format(f'r_{name}')};")
        for name, (t, _line) in outputs:
            out.append(f"  o_{name} = {self._zero(t)};")
        for name, loc in self.locals.items():
            out.append(f"  {loc.type.cpp} v_{name} = {self._zero(loc.type)};")
        out += self.lines
        out.append("}")

        body = to_dialect(_COMMENT.sub("", "\n".join(out)))
        if "::" in body or "int64_t" in body:
            raise ToastError("internal error: C++ left in shader code (please report)")
        digest = hashlib.sha1((shader_lib.GUARD + body).encode()).hexdigest()[:16]
        name = f"toast_{digest}"
        # Helper names are only unique inside one function: make them unique per function.
        body = body.replace("toast_fn_", f"{name}_fn_").replace(_NAME, name)
        source = shader_lib.SOURCE + body + "\n"

        sig = {
            "toast": VERSION,
            "run_over": "shader",
            "function": name,
            "params": [{"name": p.name, "type": p.type.name, "default": p.default, "min": p.min,
                        "max": p.max} for p in params],  # fmt: skip
            "inputs": [{"name": n, "kind": kind, "type": t.name} for n, (kind, t) in inputs],
            "outputs": [{"name": n, "type": t.name} for n, (t, _line) in outputs],
            "uses": {"time": self.uses_time},
        }
        return source, sig


    def _emit_cpu(self):
        """C++ for Cycles on the CPU: ``toast_shader(in, out)``. ``in`` holds the params, then
        the shading inputs, ``out`` the outputs, each as floats in signature order (float, int
        and bool: 1, vec3: 3, vec4: 4). Cycles packs and unpacks them (svm toast.h)."""
        params = list(self.params.values())
        inputs = list(self.shading.items())
        outputs = list(self.outputs.items())
        out = [f"/* Generated by Toast {VERSION}: a shader function for Cycles on the CPU. */",
               '#include "toast_rt.h"', "", "namespace {", "struct Params {"]  # fmt: skip
        for p in params:
            out.append(f"  {'int32_t' if p.type in (INT, BOOL) else p.type.cpp} p_{p.name};")
        out.append("  int32_t unused;")
        out.append("};")
        out += self.helper_code
        out += ["}  // namespace", "",
                "TOAST_EXPORT int32_t toast_abi_version()", "{", "  return TOAST_ABI_VERSION;", "}",
                "", "TOAST_EXPORT void toast_shader(const float *in, float *out)", "{",
                "  Params p;", "  p.unused = 0;"]  # fmt: skip
        k = 0

        def read(t):
            nonlocal k
            n = t.ncomp
            vals = [f"in[{k + c}]" for c in range(n)]
            k += n
            if t == INT:
                return f"toast::to_int({vals[0]})"
            if t == BOOL:
                return f"({vals[0]} != 0.0f)"
            return vals[0] if n == 1 else f"{t.cpp}({', '.join(vals)})"

        for p in params:
            value = read(p.type)
            if p.type == BOOL:
                value = f"({value} ? 1 : 0)"
            out.append(f"  p.p_{p.name} = {value};")
        for name, (kind, t) in inputs:
            out.append(f"  const {t.cpp} {'s' if kind == 'builtin' else 'a'}_{name} = {read(t)};")
        for name, (t, _line) in outputs:
            out.append(f"  {t.cpp} o_{name} = {self._zero(t)};")
        for name, loc in self.locals.items():
            out.append(f"  {loc.type.cpp} v_{name} = {self._zero(loc.type)};")
        out += self.lines
        out.append("toast_done:;")
        k = 0
        for name, (t, _line) in outputs:
            if t.ncomp == 1:
                out.append(f"  out[{k}] = float(o_{name});")
            else:
                for c in range(t.ncomp):
                    out.append(f"  out[{k + c}] = o_{name}.{'xyzw'[c]};")
            k += t.ncomp
        out += ["}", ""]
        return "\n".join(out)


def compile_shader(source, libs=None):
    """Translate Toast shader code. Returns ShaderSource(source, signature, desugared, cpu)."""
    gpu = ShaderCompiler(source, libs).compile()
    gpu.cpu = ShaderCompiler(source, libs, target="cpu").compile().cpu
    return gpu


def signature_json(sig):
    return json.dumps(sig, sort_keys=True)
