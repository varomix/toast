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

#define TOAST_ABI_VERSION 4

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
};

/* ToastAttr.domain */
enum {
  TOAST_DOMAIN_POINT = 0,
  TOAST_DOMAIN_FACE = 1,
  TOAST_DOMAIN_EDGE = 2,
  TOAST_DOMAIN_CORNER = 3,
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
 * - ray_cast / closest_point: query the triangles of `input`'s mesh (as it was before the run).
 *   ray_cast normalizes `dir`; both ignore results farther than `max_dist`. Return out->hit.
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

}  // namespace toast
