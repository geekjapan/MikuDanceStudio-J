/* The SSE intrinsics that Bullet 2.75 reaches with BT_USE_SSE, for clang
 * builds on every target (__m128 is a plain struct, as MSVC's union, not a
 * vector type with operators). Every lane is one IEEE single-precision operation, as on SSE,
 * so with -ffp-contract=off the results are the same bits. Compare masks
 * are all-ones lanes and the logic operations act on the bits. */
#pragma once
#include <stdint.h>
#include <string.h>

typedef struct alignas(16) mds_m128 {
  float m[4];
} __m128;

#define _MM_SHUFFLE(z, y, x, w) (((z) << 6) | ((y) << 4) | ((x) << 2) | (w))

static inline __m128 mds_m128_of(float a, float b, float c, float d) {
  __m128 r;
  r.m[0] = a;
  r.m[1] = b;
  r.m[2] = c;
  r.m[3] = d;
  return r;
}
static inline __m128 _mm_set1_ps(float a) { return mds_m128_of(a, a, a, a); }
static inline __m128 _mm_set_ss(float a) { return mds_m128_of(a, 0.0f, 0.0f, 0.0f); }
static inline float _mm_cvtss_f32(__m128 a) { return a.m[0]; }
static inline __m128 _mm_load_ps(const float *p) { return mds_m128_of(p[0], p[1], p[2], p[3]); }
static inline void _mm_store_ps(float *p, __m128 a) { memcpy(p, a.m, sizeof a.m); }

#define MDS_SSE_LANES(name, op)                                                                    \
  static inline __m128 name(__m128 a, __m128 b) {                                                  \
    return mds_m128_of(a.m[0] op b.m[0], a.m[1] op b.m[1], a.m[2] op b.m[2], a.m[3] op b.m[3]);    \
  }
MDS_SSE_LANES(_mm_add_ps, +)
MDS_SSE_LANES(_mm_sub_ps, -)
MDS_SSE_LANES(_mm_mul_ps, *)
#undef MDS_SSE_LANES

#define MDS_SSE_LOW(name, op)                                                                      \
  static inline __m128 name(__m128 a, __m128 b) {                                                  \
    a.m[0] = a.m[0] op b.m[0];                                                                     \
    return a;                                                                                      \
  }
MDS_SSE_LOW(_mm_add_ss, +)
MDS_SSE_LOW(_mm_sub_ss, -)
MDS_SSE_LOW(_mm_mul_ss, *)
MDS_SSE_LOW(_mm_div_ss, /)
#undef MDS_SSE_LOW

static inline uint32_t mds_m128_bits(float f) {
  uint32_t u;
  memcpy(&u, &f, 4);
  return u;
}
static inline float mds_m128_float(uint32_t u) {
  float f;
  memcpy(&f, &u, 4);
  return f;
}
static inline __m128 _mm_cmplt_ps(__m128 a, __m128 b) {
  __m128 r;
  for (int i = 0; i < 4; ++i) r.m[i] = mds_m128_float(a.m[i] < b.m[i] ? 0xFFFFFFFFu : 0u);
  return r;
}

#define MDS_SSE_BITS(name, expr)                                                                   \
  static inline __m128 name(__m128 a, __m128 b) {                                                  \
    __m128 r;                                                                                      \
    for (int i = 0; i < 4; ++i) {                                                                  \
      const uint32_t x = mds_m128_bits(a.m[i]), y = mds_m128_bits(b.m[i]);                         \
      r.m[i] = mds_m128_float(expr);                                                               \
    }                                                                                              \
    return r;                                                                                      \
  }
MDS_SSE_BITS(_mm_and_ps, x & y)
MDS_SSE_BITS(_mm_or_ps, x | y)
MDS_SSE_BITS(_mm_andnot_ps, ~x & y)
#undef MDS_SSE_BITS

static inline __m128 _mm_shuffle_ps(__m128 a, __m128 b, int imm) {
  return mds_m128_of(a.m[imm & 3], a.m[(imm >> 2) & 3], b.m[(imm >> 4) & 3], b.m[(imm >> 6) & 3]);
}
