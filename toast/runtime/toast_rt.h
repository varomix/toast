/* SPDX-FileCopyrightText: 2026 varomix
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/* toast_rt.h: runtime for Toast kernels.
 *
 * Self-contained on purpose: no Blender headers. Kernels see only the C ABI below (ToastCtx,
 * ToastAttr, ToastHost), so a kernel built once keeps working when the fork moves to a newer
 * Blender, as long as TOAST_ABI_VERSION matches.
 *
 * Noise and hash functions are ported from Blender's `blenlib/intern/noise.cc` (5.3) and must
 * stay bit-identical to it. Keep their arithmetic exactly as upstream writes it, including the
 * double literals in `fade`, the bilinear `mix` and the 2D `noise_grad`. Kernels are compiled
 * with -ffp-contract=off so no FMA contraction changes the rounding. */

#pragma once

/* No system headers: kernels also compile in Blender's built-in compiler, on machines without a
 * C++ toolchain. Types come from the compiler's predefined macros, math from its builtins (which
 * become the same instructions or libm calls as <cmath>, so results don't change). */
typedef __INT8_TYPE__ int8_t;
typedef __INT16_TYPE__ int16_t;
typedef __INT32_TYPE__ int32_t;
typedef __INT64_TYPE__ int64_t;
typedef __UINT8_TYPE__ uint8_t;
typedef __UINT16_TYPE__ uint16_t;
typedef __UINT32_TYPE__ uint32_t;
typedef __UINT64_TYPE__ uint64_t;
typedef __SIZE_TYPE__ size_t;
#ifndef offsetof
#  define offsetof(type, member) __builtin_offsetof(type, member)
#endif

#define TOAST_ABI_VERSION 6

#if defined(_WIN32)
#  define TOAST_EXPORT extern "C" __declspec(dllexport)
#else
#  define TOAST_EXPORT extern "C" __attribute__((visibility("default")))
#endif

/* -------------------------------------------------------------------- */
/* C ABI, shared with the host (Blender node or test harness). */

extern "C" {

struct ToastCmdBuffer; /* Opaque, owned by the host. One per chunk. */

/* ToastAttr.type */
enum {
  TOAST_TYPE_FLOAT = 0,
  TOAST_TYPE_INT = 1,  /* int32 */
  TOAST_TYPE_BOOL = 2, /* 1 byte */
  TOAST_TYPE_FLOAT2 = 3,
  TOAST_TYPE_FLOAT3 = 4,
  TOAST_TYPE_FLOAT4 = 5,
  TOAST_TYPE_QUAT = 6,   /* w, x, y, z: Blender's Quaternion. */
  TOAST_TYPE_MAT4 = 7,   /* 16 floats, column-major: Blender's float4x4. */
};

/* ToastAttr.domain */
enum {
  TOAST_DOMAIN_POINT = 0,
  TOAST_DOMAIN_FACE = 1,
  TOAST_DOMAIN_EDGE = 2,
  TOAST_DOMAIN_CORNER = 3,
  TOAST_DOMAIN_CURVE = 4,
  TOAST_DOMAIN_INSTANCE = 5,
};

/* Result of a surface query (ray cast or closest point) on a mesh's triangles. */
typedef struct ToastHit {
  float position[3];
  float normal[3];      /* Normalized triangle normal, Blender's face winding. */
  float bary[3];        /* Barycentric weights of tri_points at `position`. */
  float distance;
  int32_t face;         /* Face of the hit triangle, -1 without a hit. */
  int32_t tri_points[3];
  int32_t hit;
} ToastHit;

typedef struct ToastAttr {
  void *data;   /* Packed array, `size` elements of `type`. */
  int64_t size; /* Element count of the attribute's domain on its input. */
  int32_t type;
  int32_t domain;
} ToastAttr;

/* Services implemented by the host. Function pointers take `self` first so they can be plain C
 * callbacks (ctypes in the test harness). Contracts:
 * - nearpoints: points of `input` with distance <= radius, sorted by distance then index,
 *   at most `max` written to `out`; returns the count.
 * - cmd_add_point: queues a new point and returns an opaque negative handle, valid only as an
 *   argument to later topology commands of the same kernel run.
 * - cmd_add_prim: queues a prim through `n` points (indices or handles). 2 points = edge.
 * - cmd_remove_point: queues removal; removals apply after all adds, and remove every prim that
 *   uses the point.
 * - nprims / primpoints: face count of `input`, and the points of a face in order (at most `max`
 *   written to `out`; returns the face's point count, 0 for a face that doesn't exist).
 * - cmd_remove_prim: queues removing a face, keeping its points (removed before points).
 * - point_faces / point_neighbors: faces using a point, points sharing an edge with it, both in
 *   ascending index order (at most `max` written; returns the full count).
 * - corner_point / corner_face: the point and face of a corner, -1 if it doesn't exist.
 * - cmd_set_attr: queues writing `value` to element `elem` of the attribute bound at `attr`
 *   (a writable binding). Applied after the run in (src, emission order), before topology.
 *   `elem` may be a handle from cmd_add_point (point attributes): applied once the point is
 *   added, before removals.
 * - ray_cast / closest_point: query the triangles of `input`'s mesh (as it was before the run).
 *   ray_cast normalizes `dir`; both ignore results farther than `max_dist`. Return out->hit.
 * - ncurves / curve_points: curve count of `input`'s curves, and the points of a curve in order
 *   (like primpoints).
 * - cmd_remove_curve: queues removing a curve with its points (curves only).
 * - cmd_add_curve: queues a new curve through `n` points (indices or handles), in order (curves
 *   only). Points from cmd_add_point on curves must each be in exactly one new curve.
 * - cmd_extend_curve: queues a new point at the tip of an existing curve (curves only) and returns
 *   its handle, like cmd_add_point. It copies the tip point's other attributes.
 * Commands are merged sorted by (src, emission order), so results don't depend on threads. */
typedef struct ToastHost {
  void *self;
  int32_t (*nearpoints)(
      void *self, int32_t input, const float *pos3, float radius, int32_t max, int64_t *out);
  int64_t (*npoints)(void *self, int32_t input);
  int64_t (*cmd_add_point)(void *self, ToastCmdBuffer *cmd, int64_t src, const float *pos3);
  void (*cmd_add_prim)(
      void *self, ToastCmdBuffer *cmd, int64_t src, const int64_t *pts, int32_t n);
  void (*cmd_remove_point)(void *self, ToastCmdBuffer *cmd, int64_t src, int64_t pt);
  /* ABI 2. */
  int64_t (*nprims)(void *self, int32_t input);
  int32_t (*primpoints)(void *self, int32_t input, int64_t prim, int32_t max, int64_t *out);
  void (*cmd_remove_prim)(void *self, ToastCmdBuffer *cmd, int64_t src, int64_t prim);
  /* ABI 3. */
  int32_t (*point_faces)(void *self, int32_t input, int64_t point, int32_t max, int64_t *out);
  int32_t (*point_neighbors)(void *self, int32_t input, int64_t point, int32_t max, int64_t *out);
  int64_t (*corner_point)(void *self, int32_t input, int64_t corner);
  int64_t (*corner_face)(void *self, int32_t input, int64_t corner);
  void (*cmd_set_attr)(
      void *self, ToastCmdBuffer *cmd, int64_t src, int32_t attr, int64_t elem, const void *value);
  /* ABI 4. */
  int32_t (*ray_cast)(void *self,
                      int32_t input,
                      const float *origin,
                      const float *dir,
                      float max_dist,
                      ToastHit *out);
  int32_t (*closest_point)(
      void *self, int32_t input, const float *pos, float max_dist, ToastHit *out);
  /* ABI 5. */
  int64_t (*ncurves)(void *self, int32_t input);
  int32_t (*curve_points)(void *self, int32_t input, int64_t curve, int32_t max, int64_t *out);
  void (*cmd_remove_curve)(void *self, ToastCmdBuffer *cmd, int64_t src, int64_t curve);
  /* ABI 6. */
  void (*cmd_add_curve)(
      void *self, ToastCmdBuffer *cmd, int64_t src, const int64_t *pts, int32_t n);
  int64_t (*cmd_extend_curve)(
      void *self, ToastCmdBuffer *cmd, int64_t src, int64_t curve, const float *pos3);
} ToastHost;

typedef struct ToastCtx {
  uint32_t abi_version, _pad;
  int64_t begin, end;      /* This chunk's range of mask positions. */
  const int64_t *indices;  /* Mask indices; null when the mask is 0..domain_size-1. */
  int64_t domain_size;     /* Elements in the run-over domain of input 0 (1 for Run Over Geometry). */
  ToastAttr *attrs;        /* Bound in signature order. */
  const void *params;      /* ch() values, laid out as the signature's params. */
  ToastCmdBuffer *cmd;     /* This chunk's command buffer. */
  const ToastHost *host;
  int64_t chunk_id;        /* begin / grain size, independent of thread count. */
  float time, frame;
} ToastCtx;

} /* extern "C" */

/* -------------------------------------------------------------------- */
/* Vector types. Packed floats, same layout as Blender's float2/3/4 attribute arrays. */

namespace toast {

struct float2 {
  float x, y;
  float2() = default;
  constexpr float2(float x_, float y_) : x(x_), y(y_) {}
  constexpr explicit float2(float s) : x(s), y(s) {}
  float &operator[](int k) { return (&x)[k]; }
  float operator[](int k) const { return (&x)[k]; }
};

struct float3 {
  float x, y, z;
  float3() = default;
  constexpr float3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}
  constexpr explicit float3(float s) : x(s), y(s), z(s) {}
  float &operator[](int k) { return (&x)[k]; }
  float operator[](int k) const { return (&x)[k]; }
};

struct float4 {
  float x, y, z, w;
  float4() = default;
  constexpr float4(float x_, float y_, float z_, float w_) : x(x_), y(y_), z(z_), w(w_) {}
  constexpr explicit float4(float s) : x(s), y(s), z(s), w(s) {}
  float &operator[](int k) { return (&x)[k]; }
  float operator[](int k) const { return (&x)[k]; }
};

static_assert(sizeof(float2) == 8, "float2 must be packed");
static_assert(sizeof(float3) == 12, "float3 must be packed");
static_assert(sizeof(float4) == 16, "float4 must be packed");

template<typename V> struct vec_size;
template<> struct vec_size<float2> {
  static constexpr int value = 2;
};
template<> struct vec_size<float3> {
  static constexpr int value = 3;
};
template<> struct vec_size<float4> {
  static constexpr int value = 4;
};

#define TOAST_VEC_OPS(V) \
  inline V operator-(V a) \
  { \
    for (int k = 0; k < vec_size<V>::value; k++) { \
      a[k] = -a[k]; \
    } \
    return a; \
  } \
  inline V operator+(V a) { return a; } \
  TOAST_VEC_BINOP(V, +) \
  TOAST_VEC_BINOP(V, -) \
  TOAST_VEC_BINOP(V, *) \
  TOAST_VEC_BINOP(V, /)

#define TOAST_VEC_BINOP(V, OP) \
  inline V operator OP(V a, const V &b) \
  { \
    for (int k = 0; k < vec_size<V>::value; k++) { \
      a[k] = a[k] OP b[k]; \
    } \
    return a; \
  } \
  inline V operator OP(V a, float b) \
  { \
    for (int k = 0; k < vec_size<V>::value; k++) { \
      a[k] = a[k] OP b; \
    } \
    return a; \
  } \
  inline V operator OP(float a, V b) \
  { \
    for (int k = 0; k < vec_size<V>::value; k++) { \
      b[k] = a OP b[k]; \
    } \
    return b; \
  } \
  inline V &operator OP##=(V & a, const V & b) { return a = a OP b; } \
  inline V &operator OP##=(V & a, float b) { return a = a OP b; }

TOAST_VEC_OPS(float2)
TOAST_VEC_OPS(float3)
TOAST_VEC_OPS(float4)

#undef TOAST_VEC_OPS
#undef TOAST_VEC_BINOP

template<int A, int B, typename V> inline float2 swz2(const V &v)
{
  return float2(v[A], v[B]);
}
template<int A, int B, int C, typename V> inline float3 swz3(const V &v)
{
  return float3(v[A], v[B], v[C]);
}
template<int A, int B, int C, int D, typename V> inline float4 swz4(const V &v)
{
  return float4(v[A], v[B], v[C], v[D]);
}

/* -------------------------------------------------------------------- */
/* Scalar helpers with Python semantics. Integer ops never trap: Blender must not crash. */

inline bool truth(bool v)
{
  return v;
}
inline bool truth(int32_t v)
{
  return v != 0;
}
inline bool truth(int64_t v)
{
  return v != 0;
}
inline bool truth(float v)
{
  return v != 0.0f;
}

inline int32_t pymod(int32_t a, int32_t b)
{
  if (b == 0) {
    return 0;
  }
  if (b == -1) {
    return 0;
  }
  int32_t r = a % b;
  if (r != 0 && ((r < 0) != (b < 0))) {
    r += b;
  }
  return r;
}

inline float pymod(float a, float b)
{
  float r = __builtin_fmodf(a, b);
  if (r != 0.0f && ((r < 0.0f) != (b < 0.0f))) {
    r += b;
  }
  return r;
}

inline int32_t floordiv(int32_t a, int32_t b)
{
  if (b == 0) {
    return 0;
  }
  if (b == -1) {
    return int32_t(0u - uint32_t(a));
  }
  int32_t q = a / b;
  if ((a % b != 0) && ((a < 0) != (b < 0))) {
    q -= 1;
  }
  return q;
}

inline float floordiv(float a, float b)
{
  return __builtin_floorf(a / b);
}

inline int32_t ipow(int32_t base, int32_t exp)
{
  uint32_t result = 1u;
  uint32_t b = uint32_t(base);
  while (exp > 0) {
    if (exp & 1) {
      result *= b;
    }
    b *= b;
    exp >>= 1;
  }
  return int32_t(result);
}

inline int32_t shl(int32_t a, int32_t b)
{
  return int32_t(uint32_t(a) << (uint32_t(b) & 31u));
}
inline int32_t shr(int32_t a, int32_t b)
{
  return a >> (uint32_t(b) & 31u);
}

/* Python int(): truncates toward zero; out of range and NaN give 0 instead of UB. */
inline int32_t to_int(float v)
{
  if (!(v > -2147483648.0f && v < 2147483648.0f)) {
    return 0;
  }
  return int32_t(v);
}

/* -------------------------------------------------------------------- */
/* Math. Scalar versions plus component-wise vector versions. */

#define TOAST_UNARY(NAME, EXPR) \
  inline float NAME(float x) \
  { \
    return EXPR; \
  } \
  template<typename V, int N = vec_size<V>::value> inline V NAME(V v) \
  { \
    for (int k = 0; k < N; k++) { \
      v[k] = NAME(v[k]); \
    } \
    return v; \
  }

TOAST_UNARY(sin, __builtin_sinf(x))
TOAST_UNARY(cos, __builtin_cosf(x))
TOAST_UNARY(tan, __builtin_tanf(x))
TOAST_UNARY(asin, __builtin_asinf(x))
TOAST_UNARY(acos, __builtin_acosf(x))
TOAST_UNARY(atan, __builtin_atanf(x))
TOAST_UNARY(sinh, __builtin_sinhf(x))
TOAST_UNARY(cosh, __builtin_coshf(x))
TOAST_UNARY(tanh, __builtin_tanhf(x))
TOAST_UNARY(exp, __builtin_expf(x))
TOAST_UNARY(log, __builtin_logf(x))
TOAST_UNARY(log2, __builtin_log2f(x))
TOAST_UNARY(log10, __builtin_log10f(x))
TOAST_UNARY(sqrt, __builtin_sqrtf(x))
TOAST_UNARY(floor, __builtin_floorf(x))
TOAST_UNARY(ceil, __builtin_ceilf(x))
TOAST_UNARY(trunc, __builtin_truncf(x))
TOAST_UNARY(abs, __builtin_fabsf(x))
TOAST_UNARY(frac, x - __builtin_floorf(x))
TOAST_UNARY(sign, float((x > 0.0f) - (x < 0.0f)))
TOAST_UNARY(radians, x * 0.017453292519943295f)
TOAST_UNARY(degrees, x * 57.29577951308232f)

#undef TOAST_UNARY

inline int32_t abs(int32_t x)
{
  return x < 0 ? int32_t(0u - uint32_t(x)) : x;
}

#define TOAST_BINARY(NAME, EXPR) \
  inline float NAME(float a, float b) \
  { \
    return EXPR; \
  } \
  template<typename V, int N = vec_size<V>::value> inline V NAME(V a, const V &b) \
  { \
    for (int k = 0; k < N; k++) { \
      a[k] = NAME(a[k], b[k]); \
    } \
    return a; \
  } \
  template<typename V, int N = vec_size<V>::value> inline V NAME(V a, float b) \
  { \
    for (int k = 0; k < N; k++) { \
      a[k] = NAME(a[k], b); \
    } \
    return a; \
  }

TOAST_BINARY(pow, __builtin_powf(a, b))
TOAST_BINARY(atan2, __builtin_atan2f(a, b))
TOAST_BINARY(fmod, __builtin_fmodf(a, b))
TOAST_BINARY(min, a < b ? a : b)
TOAST_BINARY(max, a > b ? a : b)

#undef TOAST_BINARY

/* Python semantics for vectors, component-wise. */
template<typename V, int N = vec_size<V>::value> inline V pymod(V a, const V &b)
{
  for (int k = 0; k < N; k++) {
    a[k] = pymod(a[k], b[k]);
  }
  return a;
}
template<typename V, int N = vec_size<V>::value> inline V floordiv(V a, const V &b)
{
  for (int k = 0; k < N; k++) {
    a[k] = floordiv(a[k], b[k]);
  }
  return a;
}

inline int32_t min(int32_t a, int32_t b)
{
  return a < b ? a : b;
}
inline int32_t max(int32_t a, int32_t b)
{
  return a > b ? a : b;
}

inline float clamp(float x, float lo, float hi)
{
  return x < lo ? lo : (x > hi ? hi : x);
}
inline int32_t clamp(int32_t x, int32_t lo, int32_t hi)
{
  return x < lo ? lo : (x > hi ? hi : x);
}
template<typename V, int N = vec_size<V>::value> inline V clamp(V v, float lo, float hi)
{
  for (int k = 0; k < N; k++) {
    v[k] = clamp(v[k], lo, hi);
  }
  return v;
}
template<typename V, int N = vec_size<V>::value> inline V clamp(V v, const V &lo, const V &hi)
{
  for (int k = 0; k < N; k++) {
    v[k] = clamp(v[k], lo[k], hi[k]);
  }
  return v;
}

/* lerp(a, b, t) = a + (b - a) * t */
inline float lerp(float a, float b, float t)
{
  return a + (b - a) * t;
}
template<typename V, int N = vec_size<V>::value> inline V lerp(V a, const V &b, float t)
{
  for (int k = 0; k < N; k++) {
    a[k] = lerp(a[k], b[k], t);
  }
  return a;
}

/* fit() clamps to the source range first. */
inline float fit(float x, float omin, float omax, float nmin, float nmax)
{
  if (omin == omax) {
    return nmin;
  }
  float t = (x - omin) / (omax - omin);
  t = clamp(t, 0.0f, 1.0f);
  return nmin + (nmax - nmin) * t;
}
inline float fit01(float x, float nmin, float nmax)
{
  return fit(x, 0.0f, 1.0f, nmin, nmax);
}
inline float smoothstep(float e0, float e1, float x)
{
  if (e0 == e1) {
    return x < e0 ? 0.0f : 1.0f;
  }
  float t = clamp((x - e0) / (e1 - e0), 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}

template<typename V, int N = vec_size<V>::value> inline float dot(const V &a, const V &b)
{
  float r = 0.0f;
  for (int k = 0; k < N; k++) {
    r += a[k] * b[k];
  }
  return r;
}
inline float3 cross(const float3 &a, const float3 &b)
{
  return float3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
}
template<typename V, int N = vec_size<V>::value> inline float length(const V &v)
{
  return __builtin_sqrtf(dot(v, v));
}
template<typename V, int N = vec_size<V>::value> inline float distance(const V &a, const V &b)
{
  return length(a - b);
}
/* Zero vectors stay zero, as in Blender's math::normalize. */
template<typename V, int N = vec_size<V>::value> inline V normalize(const V &v)
{
  const float len = length(v);
  return len > 0.0f ? v / len : V(0.0f);
}

/* Bounds-checked attribute read: out of range gives zero, never a crash. */
template<typename T> inline T rd(const T *data, int64_t size, int64_t j)
{
  return (j >= 0 && j < size) ? data[j] : T{};
}

/* -------------------------------------------------------------------- */
/* Host services. */

inline int32_t nearpoints(
    const ToastCtx *c, int32_t input, float3 pos, float radius, int32_t max, int64_t *out)
{
  return c->host->nearpoints(c->host->self, input, &pos.x, radius, max, out);
}
inline int32_t nearpoint(const ToastCtx *c, int32_t input, float3 pos, float radius)
{
  int64_t found = -1;
  const int32_t n = c->host->nearpoints(c->host->self, input, &pos.x, radius, 1, &found);
  return n > 0 ? int32_t(found) : -1;
}
inline int32_t npoints(const ToastCtx *c, int32_t input)
{
  return int32_t(c->host->npoints(c->host->self, input));
}
inline int64_t add_point(const ToastCtx *c, int64_t src, float3 pos)
{
  return c->host->cmd_add_point(c->host->self, c->cmd, src, &pos.x);
}
template<typename... Points> inline void add_prim(const ToastCtx *c, int64_t src, Points... pts)
{
  const int64_t list[] = {int64_t(pts)...};
  c->host->cmd_add_prim(c->host->self, c->cmd, src, list, int32_t(sizeof...(pts)));
}
inline void remove_point(const ToastCtx *c, int64_t src, int64_t pt)
{
  c->host->cmd_remove_point(c->host->self, c->cmd, src, pt);
}
inline int32_t nprims(const ToastCtx *c, int32_t input)
{
  return int32_t(c->host->nprims(c->host->self, input));
}
inline int32_t primpoints(const ToastCtx *c, int32_t input, int64_t prim, int32_t max, int64_t *out)
{
  const int32_t n = c->host->primpoints(c->host->self, input, prim, max, out);
  return n < max ? n : max;
}
inline void remove_prim(const ToastCtx *c, int64_t src, int64_t prim)
{
  c->host->cmd_remove_prim(c->host->self, c->cmd, src, prim);
}
inline int32_t ncurves(const ToastCtx *c, int32_t input)
{
  return int32_t(c->host->ncurves(c->host->self, input));
}
inline int32_t curve_points(
    const ToastCtx *c, int32_t input, int64_t curve, int32_t max, int64_t *out)
{
  const int32_t n = c->host->curve_points(c->host->self, input, curve, max, out);
  return n < max ? n : max;
}
inline void remove_curve(const ToastCtx *c, int64_t src, int64_t curve)
{
  c->host->cmd_remove_curve(c->host->self, c->cmd, src, curve);
}
template<typename... Points> inline void add_curve(const ToastCtx *c, int64_t src, Points... pts)
{
  const int64_t list[] = {int64_t(pts)...};
  c->host->cmd_add_curve(c->host->self, c->cmd, src, list, int32_t(sizeof...(pts)));
}
inline int64_t extend_curve(const ToastCtx *c, int64_t src, int64_t curve, float3 pos)
{
  return c->host->cmd_extend_curve(c->host->self, c->cmd, src, curve, &pos.x);
}
inline int32_t point_faces(const ToastCtx *c, int32_t input, int64_t pt, int32_t max, int64_t *out)
{
  const int32_t n = c->host->point_faces(c->host->self, input, pt, max, out);
  return n < max ? n : max;
}
inline int32_t point_neighbors(
    const ToastCtx *c, int32_t input, int64_t pt, int32_t max, int64_t *out)
{
  const int32_t n = c->host->point_neighbors(c->host->self, input, pt, max, out);
  return n < max ? n : max;
}
inline int32_t corner_point(const ToastCtx *c, int32_t input, int64_t corner)
{
  return int32_t(c->host->corner_point(c->host->self, input, corner));
}
inline int32_t corner_face(const ToastCtx *c, int32_t input, int64_t corner)
{
  return int32_t(c->host->corner_face(c->host->self, input, corner));
}
template<typename T>
inline void set_attr(const ToastCtx *c, int64_t src, int32_t attr, int64_t elem, T value)
{
  c->host->cmd_set_attr(c->host->self, c->cmd, src, attr, elem, &value);
}

/* The `hit` record of Toast code. */
struct Hit {
  bool hit = false;
  float3 position = float3(0.0f);
  float3 normal = float3(0.0f);
  float distance = 0.0f;
  int32_t face = -1;
  int32_t tri_points[3] = {-1, -1, -1};
  float3 bary = float3(0.0f);
};

inline Hit to_hit(const ToastHit &h)
{
  Hit r;
  if (h.hit == 0) {
    return r; /* No hit: face and points -1, the rest zero. */
  }
  r.hit = true;
  r.position = float3(h.position[0], h.position[1], h.position[2]);
  r.normal = float3(h.normal[0], h.normal[1], h.normal[2]);
  r.distance = h.distance;
  r.face = h.face;
  r.tri_points[0] = h.tri_points[0];
  r.tri_points[1] = h.tri_points[1];
  r.tri_points[2] = h.tri_points[2];
  r.bary = float3(h.bary[0], h.bary[1], h.bary[2]);
  return r;
}

inline Hit ray_cast(const ToastCtx *c, int32_t input, float3 origin, float3 dir, float max_dist)
{
  ToastHit h{};
  c->host->ray_cast(c->host->self, input, &origin.x, &dir.x, max_dist, &h);
  return to_hit(h);
}

inline Hit closest_point(const ToastCtx *c, int32_t input, float3 pos, float max_dist)
{
  ToastHit h{};
  c->host->closest_point(c->host->self, input, &pos.x, max_dist, &h);
  return to_hit(h);
}

/* An attribute on the points of the hit triangle, interpolated with the barycentric weights.
 * Zero without a hit. */
template<typename T> inline T interp_hit(const T *data, int64_t size, const Hit &h)
{
  if (!h.hit) {
    return T{};
  }
  return rd(data, size, h.tri_points[0]) * h.bary.x + rd(data, size, h.tri_points[1]) * h.bary.y +
         rd(data, size, h.tri_points[2]) * h.bary.z;
}

/* -------------------------------------------------------------------- */
/* Hashes, ported from Blender `noise.cc` (Jenkins lookup3). */

namespace detail {

inline uint32_t hash_bit_rotate(uint32_t x, uint32_t k)
{
  return (x << k) | (x >> (32 - k));
}

inline void hash_bit_mix(uint32_t &a, uint32_t &b, uint32_t &c)
{
  a -= c;
  a ^= hash_bit_rotate(c, 4);
  c += b;
  b -= a;
  b ^= hash_bit_rotate(a, 6);
  a += c;
  c -= b;
  c ^= hash_bit_rotate(b, 8);
  b += a;
  a -= c;
  a ^= hash_bit_rotate(c, 16);
  c += b;
  b -= a;
  b ^= hash_bit_rotate(a, 19);
  a += c;
  c -= b;
  c ^= hash_bit_rotate(b, 4);
  b += a;
}

inline void hash_bit_final(uint32_t &a, uint32_t &b, uint32_t &c)
{
  c ^= b;
  c -= hash_bit_rotate(b, 14);
  a ^= c;
  a -= hash_bit_rotate(c, 11);
  b ^= a;
  b -= hash_bit_rotate(a, 25);
  c ^= b;
  c -= hash_bit_rotate(b, 16);
  a ^= c;
  a -= hash_bit_rotate(c, 4);
  b ^= a;
  b -= hash_bit_rotate(a, 14);
  c ^= b;
  c -= hash_bit_rotate(b, 24);
}

}  // namespace detail

inline uint32_t hash(uint32_t kx)
{
  uint32_t a, b, c;
  a = b = c = 0xdeadbeef + (1 << 2) + 13;
  a += kx;
  detail::hash_bit_final(a, b, c);
  return c;
}

inline uint32_t hash(uint32_t kx, uint32_t ky)
{
  uint32_t a, b, c;
  a = b = c = 0xdeadbeef + (2 << 2) + 13;
  b += ky;
  a += kx;
  detail::hash_bit_final(a, b, c);
  return c;
}

inline uint32_t hash(uint32_t kx, uint32_t ky, uint32_t kz)
{
  uint32_t a, b, c;
  a = b = c = 0xdeadbeef + (3 << 2) + 13;
  c += kz;
  b += ky;
  a += kx;
  detail::hash_bit_final(a, b, c);
  return c;
}

inline uint32_t hash(uint32_t kx, uint32_t ky, uint32_t kz, uint32_t kw)
{
  uint32_t a, b, c;
  a = b = c = 0xdeadbeef + (4 << 2) + 13;
  a += kx;
  b += ky;
  c += kz;
  detail::hash_bit_mix(a, b, c);
  a += kw;
  detail::hash_bit_final(a, b, c);
  return c;
}

inline uint32_t float_as_uint(float f)
{
  uint32_t u;
  __builtin_memcpy(&u, &f, sizeof(u));
  return u;
}

inline uint32_t hash_float(float kx)
{
  return hash(float_as_uint(kx));
}
inline uint32_t hash_float(float2 k)
{
  return hash(float_as_uint(k.x), float_as_uint(k.y));
}
inline uint32_t hash_float(float3 k)
{
  return hash(float_as_uint(k.x), float_as_uint(k.y), float_as_uint(k.z));
}
inline uint32_t hash_float(float4 k)
{
  return hash(float_as_uint(k.x), float_as_uint(k.y), float_as_uint(k.z), float_as_uint(k.w));
}

inline float uint_to_float_01(uint32_t k)
{
  return float(k) / float(0xFFFFFFFFu);
}

inline float hash_to_float(uint32_t kx)
{
  return uint_to_float_01(hash(kx));
}
inline float hash_to_float(uint32_t kx, uint32_t ky)
{
  return uint_to_float_01(hash(kx, ky));
}
inline float hash_to_float(uint32_t kx, uint32_t ky, uint32_t kz)
{
  return uint_to_float_01(hash(kx, ky, kz));
}

inline float hash_float_to_float(float k)
{
  return uint_to_float_01(hash_float(k));
}
inline float hash_float_to_float(float2 k)
{
  return uint_to_float_01(hash_float(k));
}
inline float hash_float_to_float(float3 k)
{
  return uint_to_float_01(hash_float(k));
}
inline float hash_float_to_float(float4 k)
{
  return uint_to_float_01(hash_float(k));
}

/* -------------------------------------------------------------------- */
/* Perlin noise, ported from Blender `noise.cc`. Keep the arithmetic verbatim. */

namespace detail {

template<typename T> inline T mix(T v0, T v1, float x)
{
  return (1 - x) * v0 + x * v1;
}

inline float mix(float v0, float v1, float v2, float v3, float x, float y)
{
  float x1 = 1.0 - x;
  return (1.0 - y) * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x);
}

inline float mix(float v0,
                 float v1,
                 float v2,
                 float v3,
                 float v4,
                 float v5,
                 float v6,
                 float v7,
                 float x,
                 float y,
                 float z)
{
  float x1 = 1.0 - x;
  float y1 = 1.0 - y;
  float z1 = 1.0 - z;
  return z1 * (y1 * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x)) +
         z * (y1 * (v4 * x1 + v5 * x) + y * (v6 * x1 + v7 * x));
}

inline float mix(float v0,
                 float v1,
                 float v2,
                 float v3,
                 float v4,
                 float v5,
                 float v6,
                 float v7,
                 float v8,
                 float v9,
                 float v10,
                 float v11,
                 float v12,
                 float v13,
                 float v14,
                 float v15,
                 float x,
                 float y,
                 float z,
                 float w)
{
  return mix(mix(v0, v1, v2, v3, v4, v5, v6, v7, x, y, z),
             mix(v8, v9, v10, v11, v12, v13, v14, v15, x, y, z),
             w);
}

inline float fade(float t)
{
  return t * t * t * (t * (t * 6.0 - 15.0) + 10.0);
}

inline float negate_if(float value, uint32_t condition)
{
  return (condition != 0u) ? -value : value;
}

inline float noise_grad(uint32_t hash, float x)
{
  uint32_t h = hash & 15u;
  float g = 1u + (h & 7u);
  return negate_if(g, h & 8u) * x;
}

inline float noise_grad(uint32_t hash, float x, float y)
{
  uint32_t h = hash & 7u;
  float u = h < 4u ? x : y;
  float v = 2.0 * (h < 4u ? y : x);
  return negate_if(u, h & 1u) + negate_if(v, h & 2u);
}

inline float noise_grad(uint32_t hash, float x, float y, float z)
{
  uint32_t h = hash & 15u;
  float u = h < 8u ? x : y;
  float vt = (h == 12u || h == 14u) ? x : z;
  float v = h < 4u ? y : vt;
  return negate_if(u, h & 1u) + negate_if(v, h & 2u);
}

inline float noise_grad(uint32_t hash, float x, float y, float z, float w)
{
  uint32_t h = hash & 31u;
  float u = h < 24u ? x : y;
  float v = h < 16u ? y : z;
  float s = h < 8u ? z : w;
  return negate_if(u, h & 1u) + negate_if(v, h & 2u) + negate_if(s, h & 4u);
}

inline float floor_fraction(float x, int &i)
{
  float x_floor = __builtin_floorf(x);
  i = int(x_floor);
  return x - x_floor;
}

inline float perlin_noise(float position)
{
  int X;
  float fx = floor_fraction(position, X);
  float u = fade(fx);
  float r = mix(noise_grad(hash(X), fx), noise_grad(hash(X + 1), fx - 1.0), u);
  return r;
}

inline float perlin_noise(float2 position)
{
  int X, Y;
  float fx = floor_fraction(position.x, X);
  float fy = floor_fraction(position.y, Y);
  float u = fade(fx);
  float v = fade(fy);
  float r = mix(noise_grad(hash(X, Y), fx, fy),
                noise_grad(hash(X + 1, Y), fx - 1.0, fy),
                noise_grad(hash(X, Y + 1), fx, fy - 1.0),
                noise_grad(hash(X + 1, Y + 1), fx - 1.0, fy - 1.0),
                u,
                v);
  return r;
}

inline float perlin_noise(float3 position)
{
  int X, Y, Z;
  float fx = floor_fraction(position.x, X);
  float fy = floor_fraction(position.y, Y);
  float fz = floor_fraction(position.z, Z);
  float u = fade(fx);
  float v = fade(fy);
  float w = fade(fz);
  float r = mix(noise_grad(hash(X, Y, Z), fx, fy, fz),
                noise_grad(hash(X + 1, Y, Z), fx - 1, fy, fz),
                noise_grad(hash(X, Y + 1, Z), fx, fy - 1, fz),
                noise_grad(hash(X + 1, Y + 1, Z), fx - 1, fy - 1, fz),
                noise_grad(hash(X, Y, Z + 1), fx, fy, fz - 1),
                noise_grad(hash(X + 1, Y, Z + 1), fx - 1, fy, fz - 1),
                noise_grad(hash(X, Y + 1, Z + 1), fx, fy - 1, fz - 1),
                noise_grad(hash(X + 1, Y + 1, Z + 1), fx - 1, fy - 1, fz - 1),
                u,
                v,
                w);
  return r;
}

inline float perlin_noise(float4 position)
{
  int X, Y, Z, W;
  float fx = floor_fraction(position.x, X);
  float fy = floor_fraction(position.y, Y);
  float fz = floor_fraction(position.z, Z);
  float fw = floor_fraction(position.w, W);
  float u = fade(fx);
  float v = fade(fy);
  float t = fade(fz);
  float s = fade(fw);
  float r = mix(
      noise_grad(hash(X, Y, Z, W), fx, fy, fz, fw),
      noise_grad(hash(X + 1, Y, Z, W), fx - 1.0, fy, fz, fw),
      noise_grad(hash(X, Y + 1, Z, W), fx, fy - 1.0, fz, fw),
      noise_grad(hash(X + 1, Y + 1, Z, W), fx - 1.0, fy - 1.0, fz, fw),
      noise_grad(hash(X, Y, Z + 1, W), fx, fy, fz - 1.0, fw),
      noise_grad(hash(X + 1, Y, Z + 1, W), fx - 1.0, fy, fz - 1.0, fw),
      noise_grad(hash(X, Y + 1, Z + 1, W), fx, fy - 1.0, fz - 1.0, fw),
      noise_grad(hash(X + 1, Y + 1, Z + 1, W), fx - 1.0, fy - 1.0, fz - 1.0, fw),
      noise_grad(hash(X, Y, Z, W + 1), fx, fy, fz, fw - 1.0),
      noise_grad(hash(X + 1, Y, Z, W + 1), fx - 1.0, fy, fz, fw - 1.0),
      noise_grad(hash(X, Y + 1, Z, W + 1), fx, fy - 1.0, fz, fw - 1.0),
      noise_grad(hash(X + 1, Y + 1, Z, W + 1), fx - 1.0, fy - 1.0, fz, fw - 1.0),
      noise_grad(hash(X, Y, Z + 1, W + 1), fx, fy, fz - 1.0, fw - 1.0),
      noise_grad(hash(X + 1, Y, Z + 1, W + 1), fx - 1.0, fy, fz - 1.0, fw - 1.0),
      noise_grad(hash(X, Y + 1, Z + 1, W + 1), fx, fy - 1.0, fz - 1.0, fw - 1.0),
      noise_grad(hash(X + 1, Y + 1, Z + 1, W + 1), fx - 1.0, fy - 1.0, fz - 1.0, fw - 1.0),
      u,
      v,
      t,
      s);
  return r;
}

inline float mod_f(float a, float b)
{
  return __builtin_fmodf(a, b);
}
inline float2 mod_f(float2 a, float b)
{
  return float2(__builtin_fmodf(a.x, b), __builtin_fmodf(a.y, b));
}
inline float3 mod_f(float3 a, float b)
{
  return float3(__builtin_fmodf(a.x, b), __builtin_fmodf(a.y, b), __builtin_fmodf(a.z, b));
}
inline float4 mod_f(float4 a, float b)
{
  return float4(__builtin_fmodf(a.x, b), __builtin_fmodf(a.y, b), __builtin_fmodf(a.z, b), __builtin_fmodf(a.w, b));
}

}  // namespace detail

inline float perlin_signed(float position)
{
  float precision_correction = 0.5f * float(__builtin_fabsf(position) >= 1000000.0f);
  position = detail::mod_f(position, 100000.0f) + precision_correction;
  return detail::perlin_noise(position) * 0.2500f;
}

inline float perlin_signed(float2 position)
{
  float2 precision_correction = 0.5f * float2(float(__builtin_fabsf(position.x) >= 1000000.0f),
                                              float(__builtin_fabsf(position.y) >= 1000000.0f));
  position = detail::mod_f(position, 100000.0f) + precision_correction;
  return detail::perlin_noise(position) * 0.6616f;
}

inline float perlin_signed(float3 position)
{
  float3 precision_correction = 0.5f * float3(float(__builtin_fabsf(position.x) >= 1000000.0f),
                                              float(__builtin_fabsf(position.y) >= 1000000.0f),
                                              float(__builtin_fabsf(position.z) >= 1000000.0f));
  position = detail::mod_f(position, 100000.0f) + precision_correction;
  return detail::perlin_noise(position) * 0.9820f;
}

inline float perlin_signed(float4 position)
{
  float4 precision_correction = 0.5f * float4(float(__builtin_fabsf(position.x) >= 1000000.0f),
                                              float(__builtin_fabsf(position.y) >= 1000000.0f),
                                              float(__builtin_fabsf(position.z) >= 1000000.0f),
                                              float(__builtin_fabsf(position.w) >= 1000000.0f));
  position = detail::mod_f(position, 100000.0f) + precision_correction;
  return detail::perlin_noise(position) * 0.8344f;
}

template<typename T> inline float perlin(T position)
{
  return perlin_signed(position) / 2.0f + 0.5f;
}

template<typename T>
inline float perlin_fbm(
    T p, const float detail, const float roughness, const float lacunarity, const bool normalize)
{
  float fscale = 1.0f;
  float amp = 1.0f;
  float maxamp = 0.0f;
  float sum = 0.0f;

  for (int i = 0; i <= int(detail); i++) {
    float t = perlin_signed(fscale * p);
    sum += t * amp;
    maxamp += amp;
    amp *= roughness;
    fscale *= lacunarity;
  }
  float rmd = detail - __builtin_floorf(detail);
  if (rmd != 0.0f) {
    float t = perlin_signed(fscale * p);
    float sum2 = sum + t * amp;
    return normalize ? detail::mix(0.5f * sum / maxamp + 0.5f,
                                   0.5f * sum2 / (maxamp + amp) + 0.5f,
                                   rmd) :
                       detail::mix(sum, sum2, rmd);
  }
  return normalize ? 0.5f * sum / maxamp + 0.5f : sum;
}

/* -------------------------------------------------------------------- */
/* Voronoi, ported from Blender `noise.cc` (3D F1). Keep the arithmetic verbatim. */

namespace detail {

struct int3v {
  int32_t x, y, z;
};

/* PCG 3D hash ("Hash Functions for GPU Rendering", JCGT 2020), signed as in Blender. Relies on
 * wrapping signed overflow (kernels build with -fwrapv). */
inline int3v hash_pcg3d_i(int3v v)
{
  v.x = v.x * 1664525 + 1013904223;
  v.y = v.y * 1664525 + 1013904223;
  v.z = v.z * 1664525 + 1013904223;
  v.x += v.y * v.z;
  v.y += v.z * v.x;
  v.z += v.x * v.y;
  v.x = v.x ^ (v.x >> 16);
  v.y = v.y ^ (v.y >> 16);
  v.z = v.z ^ (v.z >> 16);
  v.x += v.y * v.z;
  v.y += v.z * v.x;
  v.z += v.x * v.y;
  return v;
}

inline float int_to_float_01(int32_t k)
{
  return float(k & 0x7fffffff) * (1.0f / float(0x7fffffff));
}

inline float3 hash_int3_to_float3(int3v k)
{
  int3v h = hash_pcg3d_i(k);
  return float3(int_to_float_01(h.x), int_to_float_01(h.y), int_to_float_01(h.z));
}

inline float length_squared(const float3 &a)
{
  return a.x * a.x + a.y * a.y + a.z * a.z;
}

}  // namespace detail

/* The `voronoi` record of Toast code. */
struct Voronoi {
  float distance = 0.0f;
  float3 color = float3(0.0f);
  float3 position = float3(0.0f);
};

/* voronoi(p, randomness): Voronoi Texture node, 3D, F1, Euclidean, detail 0, not normalized,
 * scale 1 (put the scale in p). */
inline Voronoi voronoi(float3 coord, float randomness)
{
  randomness = randomness < 0.0f ? 0.0f : (randomness > 1.0f ? 1.0f : randomness);
  float3 cellPosition_f = float3(__builtin_floorf(coord.x), __builtin_floorf(coord.y), __builtin_floorf(coord.z));
  float3 localPosition = coord - cellPosition_f;
  detail::int3v cellPosition = {
      int32_t(cellPosition_f.x), int32_t(cellPosition_f.y), int32_t(cellPosition_f.z)};

  float minDistance = 3.402823466e+38f;
  detail::int3v targetOffset = {0, 0, 0};
  float3 targetPosition = float3(0.0f, 0.0f, 0.0f);
  for (int k = -1; k <= 1; k++) {
    for (int j = -1; j <= 1; j++) {
      for (int i = -1; i <= 1; i++) {
        detail::int3v cellOffset = {i, j, k};
        detail::int3v cell = {
            cellPosition.x + cellOffset.x, cellPosition.y + cellOffset.y, cellPosition.z + k};
        float3 pointPosition = float3(float(i), float(j), float(k)) +
                               detail::hash_int3_to_float3(cell) * randomness;
        float distanceToPoint = detail::length_squared(pointPosition - localPosition);
        if (distanceToPoint < minDistance) {
          targetOffset = cellOffset;
          minDistance = distanceToPoint;
          targetPosition = pointPosition;
        }
      }
    }
  }

  Voronoi octave;
  octave.distance = __builtin_sqrtf(detail::length_squared(targetPosition - localPosition));
  octave.color = detail::hash_int3_to_float3({cellPosition.x + targetOffset.x,
                                              cellPosition.y + targetOffset.y,
                                              cellPosition.z + targetOffset.z});
  octave.position = (targetPosition + cellPosition_f) / 1.0f;
  return octave;
}

/* -------------------------------------------------------------------- */
/* Toast builtins. Each matches a Blender node exactly; see the Toast design notes. */

/* noise(p): Noise Texture node, scale 1, detail 0, distortion 0, normalized. In [0, 1]. */
template<typename T> inline float noise(T p)
{
  return perlin(p);
}

/* snoise(p): signed Perlin noise in [-1, 1]. */
template<typename T> inline float snoise(T p)
{
  return perlin_signed(p);
}

/* fbm(p, ...): Noise Texture node (fBM, normalized, distortion 0) with scale 1. */
template<typename T>
inline float fbm(T p, float detail, float roughness, float lacunarity)
{
  const float d = detail < 0.0f ? 0.0f : (detail > 15.0f ? 15.0f : detail);
  const float r = roughness > 0.0f ? roughness : 0.0f;
  return perlin_fbm(p, d, r, lacunarity, true);
}

/* random(id, seed): Random Value node, Float, min 0, max 1. */
inline float random(int32_t id, int32_t seed)
{
  return hash_to_float(uint32_t(seed), uint32_t(id));
}

/* rand(x): hash to [0, 1]. Floats and vectors hash their bits, ints hash their value. */
inline float rand(int32_t x)
{
  return hash_to_float(uint32_t(x));
}
inline float rand(float x)
{
  return hash_float_to_float(x);
}
inline float rand(float2 x)
{
  return hash_float_to_float(x);
}
inline float rand(float3 x)
{
  return hash_float_to_float(x);
}
inline float rand(float4 x)
{
  return hash_float_to_float(x);
}

/* curl_noise(p): curl of a field of three signed noises, a divergence-free (swirling) vector
 * field for flow-like motion. Central differences; Blender has no node for it. */
inline float3 curl_potential(float3 q)
{
  return float3(snoise(q),
                snoise(q + float3(31.416f, -47.853f, 12.679f)),
                snoise(q + float3(-233.145f, -113.408f, -185.31f)));
}
inline float3 curl_noise(float3 p)
{
  const float e = 1e-3f;
  const float3 dx = (curl_potential(p + float3(e, 0.0f, 0.0f)) -
                     curl_potential(p - float3(e, 0.0f, 0.0f))) / (2.0f * e);
  const float3 dy = (curl_potential(p + float3(0.0f, e, 0.0f)) -
                     curl_potential(p - float3(0.0f, e, 0.0f))) / (2.0f * e);
  const float3 dz = (curl_potential(p + float3(0.0f, 0.0f, e)) -
                     curl_potential(p - float3(0.0f, 0.0f, e))) / (2.0f * e);
  return float3(dy.z - dz.y, dz.x - dx.z, dx.y - dy.x);
}

/* -------------------------------------------------------------------- */
/* Rotations and matrices. Same layout and conventions as Blender: math::Quaternion is
 * (w, x, y, z), float4x4 is column-major (columns: x axis, y axis, z axis, location). The
 * formulas follow Blender's math_rotation.c, so results match its nodes closely (not bit for bit
 * in every case). */

struct quat {
  float w = 1.0f, x = 0.0f, y = 0.0f, z = 0.0f;
  quat() = default;
  constexpr quat(float w_, float x_, float y_, float z_) : w(w_), x(x_), y(y_), z(z_) {}
};
static_assert(sizeof(quat) == 16, "quat must be packed");

inline quat operator*(const quat &a, const quat &b)
{
  return quat(a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
              a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
              a.w * b.y + a.y * b.w + a.z * b.x - a.x * b.z,
              a.w * b.z + a.z * b.w + a.x * b.y - a.y * b.x);
}
inline quat &operator*=(quat &a, const quat &b)
{
  return a = a * b;
}
inline float dot(const quat &a, const quat &b)
{
  return a.w * b.w + a.x * b.x + a.y * b.y + a.z * b.z;
}
inline quat normalize(const quat &q)
{
  const float len = __builtin_sqrtf(dot(q, q));
  if (!(len > 0.0f)) {
    return quat();
  }
  return quat(q.w / len, q.x / len, q.y / len, q.z / len);
}
inline quat inverse(const quat &q)
{
  const float d = dot(q, q);
  if (!(d > 0.0f)) {
    return quat();
  }
  return quat(q.w / d, -q.x / d, -q.y / d, -q.z / d);
}
inline quat quat_axis_angle(float3 axis, float angle)
{
  const float len = __builtin_sqrtf(axis.x * axis.x + axis.y * axis.y + axis.z * axis.z);
  if (!(len > 0.0f)) {
    return quat();
  }
  const float s = __builtin_sinf(angle * 0.5f) / len;
  return quat(__builtin_cosf(angle * 0.5f), axis.x * s, axis.y * s, axis.z * s);
}
/* Euler XYZ (radians), as Blender's eul_to_quat. */
inline quat quat_euler(float3 e)
{
  const float ti = e.x * 0.5f, tj = e.y * 0.5f, th = e.z * 0.5f;
  const float ci = __builtin_cosf(ti), cj = __builtin_cosf(tj), ch = __builtin_cosf(th);
  const float si = __builtin_sinf(ti), sj = __builtin_sinf(tj), sh = __builtin_sinf(th);
  const float cc = ci * ch, cs = ci * sh, sc = si * ch, ss = si * sh;
  return quat(cj * cc + sj * ss, cj * sc - sj * cs, cj * ss + sj * cc, cj * cs - sj * sc);
}
/* Rotate a vector by a (normalized) quaternion. */
inline float3 rotate(const quat &q, const float3 &v)
{
  const float3 u(q.x, q.y, q.z);
  const float3 t = float3(u.y * v.z - u.z * v.y, u.z * v.x - u.x * v.z, u.x * v.y - u.y * v.x) * 2.0f;
  const float3 c(u.y * t.z - u.z * t.y, u.z * t.x - u.x * t.z, u.x * t.y - u.y * t.x);
  return v + t * q.w + c;
}
/* Spherical interpolation along the shortest path, as Blender's interp_qt_qtqt. */
inline quat slerp(const quat &a, quat b, float t)
{
  float cosom = dot(a, b);
  if (cosom < 0.0f) {
    cosom = -cosom;
    b = quat(-b.w, -b.x, -b.y, -b.z);
  }
  float w0, w1;
  if ((1.0f - cosom) > 0.0001f) {
    const float omega = __builtin_acosf(cosom);
    const float sinom = __builtin_sinf(omega);
    w0 = __builtin_sinf((1.0f - t) * omega) / sinom;
    w1 = __builtin_sinf(t * omega) / sinom;
  }
  else {
    w0 = 1.0f - t;
    w1 = t;
  }
  return quat(a.w * w0 + b.w * w1, a.x * w0 + b.x * w1, a.y * w0 + b.y * w1, a.z * w0 + b.z * w1);
}
/* The smallest rotation turning direction `a` into direction `b`. */
inline quat quat_between(float3 a, float3 b)
{
  const float la = __builtin_sqrtf(a.x * a.x + a.y * a.y + a.z * a.z);
  const float lb = __builtin_sqrtf(b.x * b.x + b.y * b.y + b.z * b.z);
  if (!(la > 0.0f) || !(lb > 0.0f)) {
    return quat();
  }
  a = a / la;
  b = b / lb;
  float d = a.x * b.x + a.y * b.y + a.z * b.z;
  d = d < -1.0f ? -1.0f : (d > 1.0f ? 1.0f : d);
  float3 axis(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
  const float len = __builtin_sqrtf(axis.x * axis.x + axis.y * axis.y + axis.z * axis.z);
  if (len < 1e-6f) {
    if (d > 0.0f) {
      return quat();
    }
    /* Opposite: half a turn around any axis perpendicular to `a`. */
    axis = __builtin_fabsf(a.x) < 0.9f ? float3(0.0f, -a.z, a.y) : float3(a.z, 0.0f, -a.x);
  }
  return quat_axis_angle(axis, __builtin_acosf(d));
}

struct float4x4 {
  float m[4][4]; /* m[column][row] */
  float4x4()
  {
    for (int c = 0; c < 4; c++) {
      for (int r = 0; r < 4; r++) {
        m[c][r] = c == r ? 1.0f : 0.0f;
      }
    }
  }
};
static_assert(sizeof(float4x4) == 64, "float4x4 must be packed");

namespace detail {
/* Rotation matrix of a quaternion, as Blender's quat_to_mat3 (out[column][row]). */
inline void quat_to_mat3(const quat &q, float out[3][3])
{
  const double sqrt2 = 1.41421356237309504880;
  const float q0 = float(sqrt2 * q.w), q1 = float(sqrt2 * q.x), q2 = float(sqrt2 * q.y),
              q3 = float(sqrt2 * q.z);
  const float qda = q0 * q1, qdb = q0 * q2, qdc = q0 * q3;
  const float qaa = q1 * q1, qab = q1 * q2, qac = q1 * q3;
  const float qbb = q2 * q2, qbc = q2 * q3, qcc = q3 * q3;
  out[0][0] = 1.0f - qbb - qcc;
  out[0][1] = qdc + qab;
  out[0][2] = -qdb + qac;
  out[1][0] = -qdc + qab;
  out[1][1] = 1.0f - qaa - qcc;
  out[1][2] = qda + qbc;
  out[2][0] = qdb + qac;
  out[2][1] = -qda + qbc;
  out[2][2] = 1.0f - qaa - qbb;
}
/* Quaternion of an orthonormal rotation matrix, as Blender's mat3_normalized_to_quat_fast. */
inline quat mat3_to_quat(const float mat[3][3])
{
  float q[4];
  if (mat[2][2] < 0.0f) {
    if (mat[0][0] > mat[1][1]) {
      const float trace = 1.0f + mat[0][0] - mat[1][1] - mat[2][2];
      float s = 2.0f * __builtin_sqrtf(trace);
      if (mat[1][2] < mat[2][1]) {
        s = -s;
      }
      q[1] = 0.25f * s;
      s = 1.0f / s;
      q[0] = (mat[1][2] - mat[2][1]) * s;
      q[2] = (mat[0][1] + mat[1][0]) * s;
      q[3] = (mat[2][0] + mat[0][2]) * s;
      if (trace == 1.0f && q[0] == 0.0f && q[2] == 0.0f && q[3] == 0.0f) {
        q[1] = 1.0f;
      }
    }
    else {
      const float trace = 1.0f - mat[0][0] + mat[1][1] - mat[2][2];
      float s = 2.0f * __builtin_sqrtf(trace);
      if (mat[2][0] < mat[0][2]) {
        s = -s;
      }
      q[2] = 0.25f * s;
      s = 1.0f / s;
      q[0] = (mat[2][0] - mat[0][2]) * s;
      q[1] = (mat[0][1] + mat[1][0]) * s;
      q[3] = (mat[1][2] + mat[2][1]) * s;
      if (trace == 1.0f && q[0] == 0.0f && q[1] == 0.0f && q[3] == 0.0f) {
        q[2] = 1.0f;
      }
    }
  }
  else {
    if (mat[0][0] < -mat[1][1]) {
      const float trace = 1.0f - mat[0][0] - mat[1][1] + mat[2][2];
      float s = 2.0f * __builtin_sqrtf(trace);
      if (mat[0][1] < mat[1][0]) {
        s = -s;
      }
      q[3] = 0.25f * s;
      s = 1.0f / s;
      q[0] = (mat[0][1] - mat[1][0]) * s;
      q[1] = (mat[2][0] + mat[0][2]) * s;
      q[2] = (mat[1][2] + mat[2][1]) * s;
      if (trace == 1.0f && q[0] == 0.0f && q[1] == 0.0f && q[2] == 0.0f) {
        q[3] = 1.0f;
      }
    }
    else {
      const float trace = 1.0f + mat[0][0] + mat[1][1] + mat[2][2];
      float s = 2.0f * __builtin_sqrtf(trace);
      q[0] = 0.25f * s;
      s = 1.0f / s;
      q[1] = (mat[1][2] - mat[2][1]) * s;
      q[2] = (mat[2][0] - mat[0][2]) * s;
      q[3] = (mat[0][1] - mat[1][0]) * s;
      if (trace == 1.0f && q[1] == 0.0f && q[2] == 0.0f && q[3] == 0.0f) {
        q[0] = 1.0f;
      }
    }
  }
  return normalize(quat(q[0], q[1], q[2], q[3]));
}
}  // namespace detail

/* Euler XYZ (radians) of a rotation, as Blender's quat_to_eul (the smaller of two solutions). */
inline float3 to_euler(const quat &q)
{
  float mat[3][3];
  detail::quat_to_mat3(normalize(q), mat);
  const float cy = __builtin_hypotf(mat[0][0], mat[0][1]);
  float3 e1, e2;
  if (cy > 16.0f * 1.192092896e-07f) {
    e1 = float3(__builtin_atan2f(mat[1][2], mat[2][2]),
                __builtin_atan2f(-mat[0][2], cy),
                __builtin_atan2f(mat[0][1], mat[0][0]));
    e2 = float3(__builtin_atan2f(-mat[1][2], -mat[2][2]),
                __builtin_atan2f(-mat[0][2], -cy),
                __builtin_atan2f(-mat[0][1], -mat[0][0]));
  }
  else {
    e1 = float3(__builtin_atan2f(-mat[2][1], mat[1][1]), __builtin_atan2f(-mat[0][2], cy), 0.0f);
    e2 = e1;
  }
  const float s1 = __builtin_fabsf(e1.x) + __builtin_fabsf(e1.y) + __builtin_fabsf(e1.z);
  const float s2 = __builtin_fabsf(e2.x) + __builtin_fabsf(e2.y) + __builtin_fabsf(e2.z);
  return s1 > s2 ? e2 : e1;
}

inline float4x4 operator*(const float4x4 &a, const float4x4 &b)
{
  float4x4 r;
  for (int c = 0; c < 4; c++) {
    for (int row = 0; row < 4; row++) {
      float sum = 0.0f;
      for (int k = 0; k < 4; k++) {
        sum += a.m[k][row] * b.m[c][k];
      }
      r.m[c][row] = sum;
    }
  }
  return r;
}
inline float4x4 &operator*=(float4x4 &a, const float4x4 &b)
{
  return a = a * b;
}
inline float3 transform_point(const float4x4 &m, const float3 &p)
{
  return float3(m.m[0][0] * p.x + m.m[1][0] * p.y + m.m[2][0] * p.z + m.m[3][0],
                m.m[0][1] * p.x + m.m[1][1] * p.y + m.m[2][1] * p.z + m.m[3][1],
                m.m[0][2] * p.x + m.m[1][2] * p.y + m.m[2][2] * p.z + m.m[3][2]);
}
inline float3 transform_direction(const float4x4 &m, const float3 &d)
{
  return float3(m.m[0][0] * d.x + m.m[1][0] * d.y + m.m[2][0] * d.z,
                m.m[0][1] * d.x + m.m[1][1] * d.y + m.m[2][1] * d.z,
                m.m[0][2] * d.x + m.m[1][2] * d.y + m.m[2][2] * d.z);
}
inline float4x4 mat4_translation(const float3 &v)
{
  float4x4 r;
  r.m[3][0] = v.x;
  r.m[3][1] = v.y;
  r.m[3][2] = v.z;
  return r;
}
inline float4x4 mat4_scale(const float3 &v)
{
  float4x4 r;
  r.m[0][0] = v.x;
  r.m[1][1] = v.y;
  r.m[2][2] = v.z;
  return r;
}
inline float4x4 mat4_compose(const float3 &location, const quat &rotation, const float3 &scale)
{
  float rot[3][3];
  detail::quat_to_mat3(rotation, rot);
  float4x4 r;
  const float s[3] = {scale.x, scale.y, scale.z};
  for (int c = 0; c < 3; c++) {
    for (int row = 0; row < 3; row++) {
      r.m[c][row] = rot[c][row] * s[c];
    }
  }
  r.m[3][0] = location.x;
  r.m[3][1] = location.y;
  r.m[3][2] = location.z;
  return r;
}
inline float4x4 mat4_rotation(const quat &q)
{
  return mat4_compose(float3(0.0f), q, float3(1.0f));
}
inline float4x4 transpose(const float4x4 &a)
{
  float4x4 r;
  for (int c = 0; c < 4; c++) {
    for (int row = 0; row < 4; row++) {
      r.m[c][row] = a.m[row][c];
    }
  }
  return r;
}
/* Inverse by Gauss-Jordan elimination with partial pivoting. A matrix that can't be inverted
 * gives a zero matrix, as Blender's Invert Matrix node. */
inline float4x4 inverse(const float4x4 &a)
{
  float w[4][8];
  for (int row = 0; row < 4; row++) {
    for (int c = 0; c < 4; c++) {
      w[row][c] = a.m[c][row];
      w[row][c + 4] = row == c ? 1.0f : 0.0f;
    }
  }
  for (int col = 0; col < 4; col++) {
    int pivot = col;
    for (int row = col + 1; row < 4; row++) {
      if (__builtin_fabsf(w[row][col]) > __builtin_fabsf(w[pivot][col])) {
        pivot = row;
      }
    }
    if (!(__builtin_fabsf(w[pivot][col]) > 1e-30f)) {
      float4x4 zero;
      for (int c = 0; c < 4; c++) {
        for (int row = 0; row < 4; row++) {
          zero.m[c][row] = 0.0f;
        }
      }
      return zero;
    }
    if (pivot != col) {
      for (int k = 0; k < 8; k++) {
        const float t = w[col][k];
        w[col][k] = w[pivot][k];
        w[pivot][k] = t;
      }
    }
    const float inv = 1.0f / w[col][col];
    for (int k = 0; k < 8; k++) {
      w[col][k] *= inv;
    }
    for (int row = 0; row < 4; row++) {
      if (row != col) {
        const float f = w[row][col];
        for (int k = 0; k < 8; k++) {
          w[row][k] -= f * w[col][k];
        }
      }
    }
  }
  float4x4 r;
  for (int row = 0; row < 4; row++) {
    for (int c = 0; c < 4; c++) {
      r.m[c][row] = w[row][c + 4];
    }
  }
  return r;
}
inline float3 mat_translation(const float4x4 &m)
{
  return float3(m.m[3][0], m.m[3][1], m.m[3][2]);
}
inline float3 mat_scale(const float4x4 &m)
{
  float3 r;
  for (int c = 0; c < 3; c++) {
    r[c] = __builtin_sqrtf(m.m[c][0] * m.m[c][0] + m.m[c][1] * m.m[c][1] + m.m[c][2] * m.m[c][2]);
  }
  return r;
}
/* The rotation of a matrix with scale removed (a mirrored matrix is flipped first). */
inline quat mat_rotation(const float4x4 &m)
{
  float n[3][3];
  for (int c = 0; c < 3; c++) {
    const float len = __builtin_sqrtf(m.m[c][0] * m.m[c][0] + m.m[c][1] * m.m[c][1] +
                                      m.m[c][2] * m.m[c][2]);
    for (int row = 0; row < 3; row++) {
      n[c][row] = len > 0.0f ? m.m[c][row] / len : 0.0f;
    }
  }
  const float det = n[0][0] * (n[1][1] * n[2][2] - n[2][1] * n[1][2]) -
                    n[1][0] * (n[0][1] * n[2][2] - n[2][1] * n[0][2]) +
                    n[2][0] * (n[0][1] * n[1][2] - n[1][1] * n[0][2]);
  if (det < 0.0f) {
    for (int c = 0; c < 3; c++) {
      for (int row = 0; row < 3; row++) {
        n[c][row] = -n[c][row];
      }
    }
  }
  return detail::mat3_to_quat(n);
}

/* -------------------------------------------------------------------- */
/* Fixed-size arrays (Toast lists). Values, like vectors: assigning copies. Indices wrap once
 * from the end like Python (-1 is the last); other out-of-range reads give zero and writes are
 * dropped, so a bad index never crashes Blender. */

template<typename T, int N> struct Array {
  T v[N + 1]; /* v[N] absorbs out-of-range writes. */
  static Array filled(const T &x)
  {
    Array a;
    for (int k = 0; k < N; k++) {
      a.v[k] = x;
    }
    return a;
  }
  T get(int32_t k) const
  {
    if (k < 0) {
      k += N;
    }
    return (k >= 0 && k < N) ? v[k] : T{};
  }
  T &at(int32_t k)
  {
    if (k < 0) {
      k += N;
    }
    return (k >= 0 && k < N) ? v[k] : v[N];
  }
};

/* add_curve(points, count): a curve through the first `count` point numbers of a list. */
template<int N>
inline void add_curve_list(const ToastCtx *c, int64_t src, const Array<int32_t, N> &pts, int32_t n)
{
  n = n < 0 ? 0 : (n > N ? N : n);
  int64_t list[N > 0 ? N : 1];
  for (int32_t k = 0; k < n; k++) {
    list[k] = pts.v[k];
  }
  c->host->cmd_add_curve(c->host->self, c->cmd, src, list, n);
}

}  // namespace toast
