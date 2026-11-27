# SPDX-FileCopyrightText: 2026 varomix
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Runtime for Toast shader functions: the builtins of ``toast_rt.h`` in Blender's portable shader
dialect (``float3`` and friends, GLSL built-in functions), which Blender compiles as GLSL or as
Metal. Every Toast shader function includes it, inside an include guard.

The noise and hash functions are the same algorithms as ``toast_rt.h`` (ported from Blender's
``noise.cc``), so patterns match the geometry node's and Blender's texture nodes. They aren't
bit-exact on the GPU: GPU float math rounds differently.

Rules for this file, so the code compiles as both GLSL and Metal: no comments in the output, no
``out`` parameters (return values or structs), explicit int/uint conversions, every function
defined before it is used, no global constants.
"""

VECS = {2: "float2", 3: "float3", 4: "float4"}
COMPS = "xyzw"
GUARD = "TOAST_SHADER_LIB_1"

UNARY = {
    "sin": "sin(x)", "cos": "cos(x)", "tan": "tan(x)", "asin": "asin(x)", "acos": "acos(x)",
    "atan": "atan(x)", "sinh": "sinh(x)", "cosh": "cosh(x)", "tanh": "tanh(x)",
    "exp": "exp(x)", "log": "log(x)", "log2": "log2(x)", "log10": "log2(x) * 0.30102999566398120f",
    "sqrt": "sqrt(x)", "floor": "floor(x)", "ceil": "ceil(x)", "trunc": "trunc(x)",
    "abs": "abs(x)", "frac": "x - floor(x)",
    "sign": "((x > 0.0f) ? 1.0f : ((x < 0.0f) ? -1.0f : 0.0f))",
    "radians": "x * 0.017453292519943295f", "degrees": "x * 57.29577951308232f",
}  # fmt: skip

BINARY = {
    "atan2": "atan(a, b)",
    "fmod": "toast_fmod_c(a, b)",
    "min": "((a < b) ? a : b)",
    "max": "((a > b) ? a : b)",
    "pow": "toast_pow_c(a, b)",
}


def _vec_overloads(name, n_args, scalar_args=()):
    """Component-wise vector versions of scalar function `name` taking `n_args` arguments.
    Arguments at positions in `scalar_args` stay floats; the others are vectors."""
    out = []
    for n, vt in VECS.items():
        params = ", ".join((f"float {a}" if i in scalar_args else f"{vt} {a}")
                           for i, a in enumerate("abcde"[:n_args]))  # fmt: skip
        comps = []
        for c in COMPS[:n]:
            args = ", ".join((a if i in scalar_args else f"{a}.{c}")
                             for i, a in enumerate("abcde"[:n_args]))  # fmt: skip
            comps.append(f"{name}({args})")
        out.append(f"{vt} {name}({params})\n{{\n  return {vt}({', '.join(comps)});\n}}")
    return out


def _build():
    f = []
    add = f.append

    # --- Python semantics for scalars.
    add("bool toast_truth(bool v)\n{\n  return v;\n}")
    add("bool toast_truth(int v)\n{\n  return v != 0;\n}")
    add("bool toast_truth(float v)\n{\n  return v != 0.0f;\n}")
    add("float toast_fmod_c(float a, float b)\n{\n  return a - b * trunc(a / b);\n}")
    add("""float toast_nan()
{
  return uintBitsToFloat(0x7FC00000u);
}""")
    add("""float toast_pow_c(float a, float b)
{
  if (a >= 0.0f) {
    return pow(a, b);
  }
  if (b != floor(b)) {
    return toast_nan();
  }
  float r = pow(-a, b);
  return (toast_fmod_c(b, 2.0f) != 0.0f) ? -r : r;
}""")
    add("""int toast_pymod(int a, int b)
{
  if (b == 0 || b == -1) {
    return 0;
  }
  int r = a % b;
  if (r != 0 && ((r < 0) != (b < 0))) {
    r += b;
  }
  return r;
}""")
    add("""float toast_pymod(float a, float b)
{
  float r = toast_fmod_c(a, b);
  if (r != 0.0f && ((r < 0.0f) != (b < 0.0f))) {
    r += b;
  }
  return r;
}""")
    add("""int toast_floordiv(int a, int b)
{
  if (b == 0) {
    return 0;
  }
  if (b == -1) {
    return int(0u - uint(a));
  }
  int q = a / b;
  if ((a % b != 0) && ((a < 0) != (b < 0))) {
    q -= 1;
  }
  return q;
}""")
    add("float toast_floordiv(float a, float b)\n{\n  return floor(a / b);\n}")
    add("""int toast_ipow(int base, int e)
{
  uint result = 1u;
  uint b = uint(base);
  while (e > 0) {
    if ((e & 1) != 0) {
      result *= b;
    }
    b *= b;
    e >>= 1;
  }
  return int(result);
}""")
    add("int toast_shl(int a, int b)\n{\n  return int(uint(a) << (uint(b) & 31u));\n}")
    add("int toast_shr(int a, int b)\n{\n  return a >> int(uint(b) & 31u);\n}")
    add("""int toast_to_int(float v)
{
  if (!(v > -2147483648.0f && v < 2147483648.0f)) {
    return 0;
  }
  return int(v);
}""")
    add("int toast_abs(int x)\n{\n  return (x < 0) ? int(0u - uint(x)) : x;\n}")
    add("int toast_min(int a, int b)\n{\n  return (a < b) ? a : b;\n}")
    add("int toast_max(int a, int b)\n{\n  return (a > b) ? a : b;\n}")
    add("int toast_clamp(int x, int lo, int hi)\n{\n  return (x < lo) ? lo : ((x > hi) ? hi : x);\n}")

    # --- Math, scalar and component-wise.
    for name, expr in UNARY.items():
        add(f"float toast_{name}(float x)\n{{\n  return {expr};\n}}")
        f.extend(_vec_overloads(f"toast_{name}", 1))
    for name, expr in BINARY.items():
        add(f"float toast_{name}(float a, float b)\n{{\n  return {expr};\n}}")
        f.extend(_vec_overloads(f"toast_{name}", 2))
        f.extend(_vec_overloads(f"toast_{name}", 2, scalar_args=(1,)))
    f.extend(_vec_overloads("toast_pymod", 2))
    f.extend(_vec_overloads("toast_floordiv", 2))
    add("float toast_clamp(float x, float lo, float hi)\n{\n"
        "  return (x < lo) ? lo : ((x > hi) ? hi : x);\n}")  # fmt: skip
    f.extend(_vec_overloads("toast_clamp", 3, scalar_args=(1, 2)))
    f.extend(_vec_overloads("toast_clamp", 3))
    add("float toast_lerp(float a, float b, float t)\n{\n  return a + (b - a) * t;\n}")
    f.extend(_vec_overloads("toast_lerp", 3, scalar_args=(2,)))
    add("""float toast_fit(float x, float omin, float omax, float nmin, float nmax)
{
  if (omin == omax) {
    return nmin;
  }
  float t = toast_clamp((x - omin) / (omax - omin), 0.0f, 1.0f);
  return nmin + (nmax - nmin) * t;
}""")
    add("""float toast_smoothstep(float e0, float e1, float x)
{
  if (e0 == e1) {
    return (x < e0) ? 0.0f : 1.0f;
  }
  float t = toast_clamp((x - e0) / (e1 - e0), 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}""")
    for n, vt in VECS.items():
        terms = " + ".join(f"a.{c} * b.{c}" for c in COMPS[:n])
        add(f"float toast_dot({vt} a, {vt} b)\n{{\n  return {terms};\n}}")
        add(f"float toast_length({vt} v)\n{{\n  return sqrt(toast_dot(v, v));\n}}")
        add(f"float toast_distance({vt} a, {vt} b)\n{{\n  return toast_length(a - b);\n}}")
        add(f"{vt} toast_normalize({vt} v)\n{{\n  float len = toast_length(v);\n"
            f"  return (len > 0.0f) ? v / len : {vt}(0.0f);\n}}")  # fmt: skip
    add("""float3 toast_cross(float3 a, float3 b)
{
  return float3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
}""")

    # --- Hashes (Jenkins lookup3, Blender noise.cc). State (a, b, c) as a uint3.
    add("uint toast_rot(uint x, uint k)\n{\n  return (x << k) | (x >> (32u - k));\n}")
    add("""uint3 toast_hash_mix(uint3 s)
{
  uint a = s.x;
  uint b = s.y;
  uint c = s.z;
  a -= c;
  a ^= toast_rot(c, 4u);
  c += b;
  b -= a;
  b ^= toast_rot(a, 6u);
  a += c;
  c -= b;
  c ^= toast_rot(b, 8u);
  b += a;
  a -= c;
  a ^= toast_rot(c, 16u);
  c += b;
  b -= a;
  b ^= toast_rot(a, 19u);
  a += c;
  c -= b;
  c ^= toast_rot(b, 4u);
  b += a;
  return uint3(a, b, c);
}""")
    add("""uint toast_hash_final(uint a, uint b, uint c)
{
  c ^= b;
  c -= toast_rot(b, 14u);
  a ^= c;
  a -= toast_rot(c, 11u);
  b ^= a;
  b -= toast_rot(a, 25u);
  c ^= b;
  c -= toast_rot(b, 16u);
  a ^= c;
  a -= toast_rot(c, 4u);
  b ^= a;
  b -= toast_rot(a, 14u);
  c ^= b;
  c -= toast_rot(b, 24u);
  return c;
}""")
    add("""uint toast_hash(uint kx)
{
  uint a = 0xdeadbeefu + (1u << 2u) + 13u;
  return toast_hash_final(a + kx, a, a);
}""")
    add("""uint toast_hash(uint kx, uint ky)
{
  uint a = 0xdeadbeefu + (2u << 2u) + 13u;
  return toast_hash_final(a + kx, a + ky, a);
}""")
    add("""uint toast_hash(uint kx, uint ky, uint kz)
{
  uint a = 0xdeadbeefu + (3u << 2u) + 13u;
  return toast_hash_final(a + kx, a + ky, a + kz);
}""")
    add("""uint toast_hash(uint kx, uint ky, uint kz, uint kw)
{
  uint a = 0xdeadbeefu + (4u << 2u) + 13u;
  uint3 s = toast_hash_mix(uint3(a + kx, a + ky, a + kz));
  return toast_hash_final(s.x + kw, s.y, s.z);
}""")
    add("float toast_u01(uint k)\n{\n  return float(k) / 4294967295.0f;\n}")
    add("float toast_rand(int x)\n{\n  return toast_u01(toast_hash(uint(x)));\n}")
    add("float toast_rand(float x)\n{\n  return toast_u01(toast_hash(floatBitsToUint(x)));\n}")
    for n, vt in VECS.items():
        args = ", ".join(f"floatBitsToUint(x.{c})" for c in COMPS[:n])
        add(f"float toast_rand({vt} x)\n{{\n  return toast_u01(toast_hash({args}));\n}}")
    add("float toast_random(int id, int seed)\n{\n"
        "  return toast_u01(toast_hash(uint(seed), uint(id)));\n}")  # fmt: skip

    # --- Perlin noise (Blender noise.cc).
    add("float toast_fade(float t)\n{\n  return t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f);\n}")
    add("float toast_negate_if(float v, uint c)\n{\n  return (c != 0u) ? -v : v;\n}")
    add("""float toast_grad(uint hash, float x)
{
  uint h = hash & 15u;
  float g = float(1u + (h & 7u));
  return toast_negate_if(g, h & 8u) * x;
}""")
    add("""float toast_grad(uint hash, float x, float y)
{
  uint h = hash & 7u;
  float u = (h < 4u) ? x : y;
  float v = 2.0f * ((h < 4u) ? y : x);
  return toast_negate_if(u, h & 1u) + toast_negate_if(v, h & 2u);
}""")
    add("""float toast_grad(uint hash, float x, float y, float z)
{
  uint h = hash & 15u;
  float u = (h < 8u) ? x : y;
  float vt = (h == 12u || h == 14u) ? x : z;
  float v = (h < 4u) ? y : vt;
  return toast_negate_if(u, h & 1u) + toast_negate_if(v, h & 2u);
}""")
    add("""float toast_grad(uint hash, float x, float y, float z, float w)
{
  uint h = hash & 31u;
  float u = (h < 24u) ? x : y;
  float v = (h < 16u) ? y : z;
  float s = (h < 8u) ? z : w;
  return toast_negate_if(u, h & 1u) + toast_negate_if(v, h & 2u) + toast_negate_if(s, h & 4u);
}""")
    add("""float toast_mix(float v0, float v1, float x)
{
  return (1.0f - x) * v0 + x * v1;
}""")
    add("""float toast_mix(float v0, float v1, float v2, float v3, float x, float y)
{
  float x1 = 1.0f - x;
  return (1.0f - y) * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x);
}""")
    add("""float toast_mix(float v0, float v1, float v2, float v3, float v4, float v5, float v6,
                float v7, float x, float y, float z)
{
  float x1 = 1.0f - x;
  float y1 = 1.0f - y;
  float z1 = 1.0f - z;
  return z1 * (y1 * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x)) +
         z * (y1 * (v4 * x1 + v5 * x) + y * (v6 * x1 + v7 * x));
}""")
    add("""float toast_perlin_noise(float p)
{
  float xf = floor(p);
  int X = int(xf);
  float fx = p - xf;
  float u = toast_fade(fx);
  return toast_mix(toast_grad(toast_hash(uint(X)), fx),
                   toast_grad(toast_hash(uint(X + 1)), fx - 1.0f), u);
}""")
    add("""float toast_perlin_noise(float2 p)
{
  float2 pf = floor(p);
  int X = int(pf.x);
  int Y = int(pf.y);
  float fx = p.x - pf.x;
  float fy = p.y - pf.y;
  float u = toast_fade(fx);
  float v = toast_fade(fy);
  return toast_mix(toast_grad(toast_hash(uint(X), uint(Y)), fx, fy),
                   toast_grad(toast_hash(uint(X + 1), uint(Y)), fx - 1.0f, fy),
                   toast_grad(toast_hash(uint(X), uint(Y + 1)), fx, fy - 1.0f),
                   toast_grad(toast_hash(uint(X + 1), uint(Y + 1)), fx - 1.0f, fy - 1.0f),
                   u, v);
}""")
    add("""float toast_perlin_noise(float3 p)
{
  float3 pf = floor(p);
  uint X = uint(int(pf.x));
  uint Y = uint(int(pf.y));
  uint Z = uint(int(pf.z));
  float fx = p.x - pf.x;
  float fy = p.y - pf.y;
  float fz = p.z - pf.z;
  float u = toast_fade(fx);
  float v = toast_fade(fy);
  float w = toast_fade(fz);
  return toast_mix(toast_grad(toast_hash(X, Y, Z), fx, fy, fz),
                   toast_grad(toast_hash(X + 1u, Y, Z), fx - 1.0f, fy, fz),
                   toast_grad(toast_hash(X, Y + 1u, Z), fx, fy - 1.0f, fz),
                   toast_grad(toast_hash(X + 1u, Y + 1u, Z), fx - 1.0f, fy - 1.0f, fz),
                   toast_grad(toast_hash(X, Y, Z + 1u), fx, fy, fz - 1.0f),
                   toast_grad(toast_hash(X + 1u, Y, Z + 1u), fx - 1.0f, fy, fz - 1.0f),
                   toast_grad(toast_hash(X, Y + 1u, Z + 1u), fx, fy - 1.0f, fz - 1.0f),
                   toast_grad(toast_hash(X + 1u, Y + 1u, Z + 1u), fx - 1.0f, fy - 1.0f, fz - 1.0f),
                   u, v, w);
}""")
    corners = []
    for wbit in (0, 1):
        for zbit in (0, 1):
            for ybit in (0, 1):
                for xbit in (0, 1):
                    h = ", ".join(f"{k}{' + 1u' if b else ''}"
                                  for k, b in zip("XYZW", (xbit, ybit, zbit, wbit)))  # fmt: skip
                    g = ", ".join(f"f{k}{' - 1.0f' if b else ''}"
                                  for k, b in zip("xyzw", (xbit, ybit, zbit, wbit)))  # fmt: skip
                    corners.append(f"toast_grad(toast_hash({h}), {g})")
    lo = ",\n                             ".join(corners[:8])
    hi = ",\n                             ".join(corners[8:])
    add(f"""float toast_perlin_noise(float4 p)
{{
  float4 pf = floor(p);
  uint X = uint(int(pf.x));
  uint Y = uint(int(pf.y));
  uint Z = uint(int(pf.z));
  uint W = uint(int(pf.w));
  float fx = p.x - pf.x;
  float fy = p.y - pf.y;
  float fz = p.z - pf.z;
  float fw = p.w - pf.w;
  float u = toast_fade(fx);
  float v = toast_fade(fy);
  float t = toast_fade(fz);
  float s = toast_fade(fw);
  return toast_mix(toast_mix({lo}, u, v, t),
                   toast_mix({hi}, u, v, t),
                   s);
}}""")
    scale = {1: "0.2500f", 2: "0.6616f", 3: "0.9820f", 4: "0.8344f"}
    for n, vt in {1: "float", **VECS}.items():
        if n == 1:
            corr = "0.5f * ((abs(p) >= 1000000.0f) ? 1.0f : 0.0f)"
        else:
            corr = "0.5f * " + vt + "(" + ", ".join(
                f"(abs(p.{c}) >= 1000000.0f) ? 1.0f : 0.0f" for c in COMPS[:n]) + ")"
        add(f"""float toast_snoise({vt} p)
{{
  {vt} c = {corr};
  p = toast_fmod({'p, 100000.0f' if n == 1 else 'p, 100000.0f'}) + c;
  return toast_perlin_noise(p) * {scale[n]};
}}""")
        add(f"float toast_noise({vt} p)\n{{\n  return toast_snoise(p) / 2.0f + 0.5f;\n}}")
        add(f"""float toast_fbm({vt} p, float detail, float roughness, float lacunarity)
{{
  detail = (detail < 0.0f) ? 0.0f : ((detail > 15.0f) ? 15.0f : detail);
  roughness = (roughness > 0.0f) ? roughness : 0.0f;
  float fscale = 1.0f;
  float amp = 1.0f;
  float maxamp = 0.0f;
  float sum = 0.0f;
  for (int i = 0; i <= int(detail); i++) {{
    float t = toast_snoise(fscale * p);
    sum += t * amp;
    maxamp += amp;
    amp *= roughness;
    fscale *= lacunarity;
  }}
  float rmd = detail - floor(detail);
  if (rmd != 0.0f) {{
    float t = toast_snoise(fscale * p);
    float sum2 = sum + t * amp;
    return toast_mix(0.5f * sum / maxamp + 0.5f, 0.5f * sum2 / (maxamp + amp) + 0.5f, rmd);
  }}
  return 0.5f * sum / maxamp + 0.5f;
}}""")

    # --- Voronoi (3D F1, Blender noise.cc).
    add("""int3 toast_pcg3d(int3 v)
{
  v = v * 1664525 + 1013904223;
  v.x += v.y * v.z;
  v.y += v.z * v.x;
  v.z += v.x * v.y;
  v = v ^ (v >> 16);
  v.x += v.y * v.z;
  v.y += v.z * v.x;
  v.z += v.x * v.y;
  return v;
}""")
    add("""float3 toast_hash_int3_to_float3(int3 k)
{
  int3 h = toast_pcg3d(k) & 0x7fffffff;
  return float3(h) * (1.0f / 2147483647.0f);
}""")
    add("""struct toast_Voronoi {
  float f_distance;
  float3 f_color;
  float3 f_position;
};""")
    add("""toast_Voronoi toast_voronoi_zero()
{
  toast_Voronoi r;
  r.f_distance = 0.0f;
  r.f_color = float3(0.0f);
  r.f_position = float3(0.0f);
  return r;
}""")
    add("""toast_Voronoi toast_voronoi(float3 coord, float randomness)
{
  randomness = (randomness < 0.0f) ? 0.0f : ((randomness > 1.0f) ? 1.0f : randomness);
  float3 cell_f = floor(coord);
  float3 local_p = coord - cell_f;
  int3 cell = int3(cell_f);
  float min_d = 3.402823466e+38f;
  int3 target_offset = int3(0);
  float3 target_p = float3(0.0f);
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        int3 offset = int3(i, j, k);
        float3 point_p = float3(offset) + toast_hash_int3_to_float3(cell + offset) * randomness;
        float3 d = point_p - local_p;
        float dist = d.x * d.x + d.y * d.y + d.z * d.z;
        if (dist < min_d) {
          target_offset = offset;
          min_d = dist;
          target_p = point_p;
        }
      }
    }
  }
  toast_Voronoi r;
  float3 d = target_p - local_p;
  r.f_distance = sqrt(d.x * d.x + d.y * d.y + d.z * d.z);
  r.f_color = toast_hash_int3_to_float3(cell + target_offset);
  r.f_position = target_p + cell_f;
  return r;
}""")

    # --- Curl noise.
    add("""float3 toast_curl_potential(float3 q)
{
  return float3(toast_snoise(q),
                toast_snoise(q + float3(31.416f, -47.853f, 12.679f)),
                toast_snoise(q + float3(-233.145f, -113.408f, -185.31f)));
}""")
    add("""float3 toast_curl_noise(float3 p)
{
  float e = 1e-3f;
  float3 dx = (toast_curl_potential(p + float3(e, 0.0f, 0.0f)) -
               toast_curl_potential(p - float3(e, 0.0f, 0.0f))) / (2.0f * e);
  float3 dy = (toast_curl_potential(p + float3(0.0f, e, 0.0f)) -
               toast_curl_potential(p - float3(0.0f, e, 0.0f))) / (2.0f * e);
  float3 dz = (toast_curl_potential(p + float3(0.0f, 0.0f, e)) -
               toast_curl_potential(p - float3(0.0f, 0.0f, e))) / (2.0f * e);
  return float3(dy.z - dz.y, dz.x - dx.z, dx.y - dy.x);
}""")
    return "\n".join(f)


SOURCE = f"#ifndef {GUARD}\n#define {GUARD}\n{_build()}\n#endif\n"
