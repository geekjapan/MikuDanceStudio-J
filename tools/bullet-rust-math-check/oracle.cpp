// Native Bullet 2.75 oracle. Uses the vendored altered sources and their zlib license.
#include "LinearMath/btTransformUtil.h"
#include <cstdio>
#include <cstdint>
#include <cstring>

static void word(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    std::printf("\t%08x", bits);
}
static void fields(const btVector3& v) { for (int i = 0; i < 3; ++i) word(v[i]); }
static void fields(const btQuaternion& q) { for (int i = 0; i < 4; ++i) word(q[i]); }
static void fields(const btMatrix3x3& m) { for (int i = 0; i < 3; ++i) fields(m[i]); }
static void fields(const btTransform& t) { fields(t.getBasis()); fields(t.getOrigin()); }
static void end() { std::puts(""); }

int main() {
    static_assert(sizeof(btScalar) == 4, "single precision oracle required");
#ifndef BT_USE_SSE
#error Current deterministic shim must enable BT_USE_SSE
#endif
    const btVector3 vectors[] = {
        {1, 2, 3}, {-2.125f, 3.75f, -0.03125f}, {33554432, -33554432, 1},
        {0.000001f, -0.000002f, 0.000003f}, {-0.0f, 0, -1},
        {8193.25f, 0.0001220703125f, -4097.75f}, {1, 1, 1}
    };
    for (const auto& a : vectors) for (const auto& b : vectors) {
        std::printf("vector"); fields(a); fields(b);
        fields(a + b); fields(a - b); fields(-a); fields(a.cross(b));
        word(a.dot(b)); word(a.length2()); word(a.length()); fields(a.normalized());
        // Same intrinsic expression as the patched solver's _vmathVfDot3.
        __m128 product = _mm_mul_ps(a.mVec128, b.mVec128);
        __m128 sum = _mm_add_ps(
            _mm_add_ps(_mm_shuffle_ps(product, product, _MM_SHUFFLE(2,2,2,2)),
                       _mm_shuffle_ps(product, product, _MM_SHUFFLE(1,1,1,1))),
            _mm_shuffle_ps(product, product, _MM_SHUFFLE(0,0,0,0)));
        alignas(16) float lanes[4]; _mm_store_ps(lanes, sum); word(lanes[0]); end();
    }
    const btVector3 axes[] = {{1,0,0}, {0,1,0}, {0,0,1}, {1,-2,3}, {-3.125f,0.2f,1.75f}};
    const float angles[] = {0, 0.00001f, 0.75f, SIMD_PI, -2.75f};
    for (const auto& axis : axes) for (float angle : angles) {
        btQuaternion q(axis, angle);
        const btQuaternion other(btVector3(-0.25f, 2, 1), -1.125f);
        const btVector3 v(2.5f, -0.125f, 7.75f);
        std::printf("quaternion"); fields(axis); word(angle); fields(other); fields(v);
        fields(q); fields(q.inverse()); fields(q * other); fields(quatRotate(q, v));
        word(q.length2()); fields(q.normalized()); fields(btMatrix3x3(q)); end();
    }
    const btMatrix3x3 matrices[] = {
        {1,0,0, 0,1,0, 0,0,1}, {2,3,-1, 1,-2,4, 3,1,2},
        {0.0001f,0.5f,-2, 1,-0.03125f,3.25f, 4,2,0.125f},
        btMatrix3x3(btQuaternion(btVector3(1,-2,3), 2.75f))
    };
    for (const auto& a : matrices) for (const auto& b : matrices) {
        const btVector3 v(2.5f, -0.125f, 7.75f);
        std::printf("basis"); fields(a); fields(b); fields(v);
        fields(a * b); fields(a.inverse()); fields(a.transpose()); fields(a * v); end();
    }
    const btVector3 angular[] = {
        {0,0,0}, {0.0002f,-0.0003f,0.0004f}, {0.0009999f,0,0},
        {0.001f,0,0}, {0.0010001f,0,0}, {1.25f,-2.5f,3.75f},
        {47.12388f,0,0}, {47.12389f,0,0}, {47.12390f,0,0}, {300,-400,500}
    };
    const float steps[] = {0, 1.0f/60.0f, 0.125f, -0.03125f};
    for (const auto& axis : axes) for (float angle : angles) {
        const btTransform a(btQuaternion(axis, angle), btVector3(1.125f,-2.25f,3.5f));
        const btTransform b(btQuaternion(btVector3(-2,1,0.5f), -1.125f), btVector3(-3,0.125f,2));
        const btVector3 v(2.5f, -0.125f, 7.75f);
        std::printf("transform"); fields(a); fields(b); fields(v);
        fields(a * b); fields(a.inverse()); fields(a(v)); fields(a.invXform(v));
        fields(a.getRotation()); end();
        for (const auto& w : angular) for (float dt : steps) {
            const btVector3 linear(-0.25f,1.5f,2.75f);
            btTransform out;
            btTransformUtil::integrateTransform(a, linear, w, dt, out);
            std::printf("integrate"); fields(a); fields(linear); fields(w); word(dt); fields(out); end();
        }
    }
}
