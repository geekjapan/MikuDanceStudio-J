// Test adapter. Coordinate algorithms execute only in vendored Bullet.
#include "BulletDynamics/ConstraintSolver/btGeneric6DofConstraint.h"
#include "BulletDynamics/Dynamics/btRigidBody.h"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cfloat>

static void scalar(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    std::printf("\t%08x", bits);
}
static void vector(const btVector3& value) {
    for (int i = 0; i < 3; ++i) scalar(value[i]);
}
static void transform(const btTransform& value) {
    for (int i = 0; i < 3; ++i) vector(value.getBasis()[i]);
    vector(value.getOrigin());
}
struct Joint : btGeneric6DofConstraint {
    using btGeneric6DofConstraint::btGeneric6DofConstraint;
    void output() const {
        transform(m_calculatedTransformA);
        transform(m_calculatedTransformB);
        for (int i = 0; i < 3; ++i) vector(m_calculatedTransformA.getBasis()[i]);
        vector(m_calculatedTransformB.getOrigin());
        vector(m_calculatedLinearDiff);
        vector(m_calculatedAxisAngleDiff);
        for (int i = 0; i < 3; ++i) vector(m_calculatedAxis[i]);
    }
};
static uint32_t state = 0x56d32027;
static float random_float() {
    state ^= state << 13; state ^= state >> 17; state ^= state << 5;
    return (int32_t(state >> 8) - 8388608) * (1.0f / 8388608.0f);
}
static btTransform random_transform() {
    btTransform result;
    const float x = random_float(), y = random_float(), z = random_float();
    const float angle = random_float() * 3.0f;
    result.setRotation(btQuaternion(btVector3(x, y, z), angle));
    const float ox = random_float() * 32, oy = random_float() * 32, oz = random_float() * 32;
    result.setOrigin(btVector3(ox, oy, oz));
    return result;
}
int main(int argc, char** argv) {
    const int count = argc > 1 ? std::atoi(argv[1]) : 2120;
    std::fprintf(stderr, "native long double mantissa=%d, bytes=%zu, cases=%d\n", LDBL_MANT_DIG, sizeof(long double), count);
    for (int id = 0; id < count; ++id) {
        btTransform inputs[4];
        for (auto& input : inputs) input.setIdentity();
        if (id >= 72) {
            for (auto& input : inputs) input = random_transform();
            if (id % 3 == 0) {
                for (auto& input : inputs)
                    for (int i = 0; i < 3; ++i)
                        for (int j = 0; j < 3; ++j)
                            input.getBasis()[i][j] += random_float() * 0.03125f;
            }
        } else if (id > 0) {
            // Adjacent and out-of-range Euler branch values with nonzero cross axes.
            const uint32_t fi_bits[] = {0x3f7fffff, 0x3f800000, 0x3f800001,
                                       0xbf7fffff, 0xbf800000, 0xbf800001};
            float fi; const uint32_t bits = fi_bits[(id - 1) % 6];
            std::memcpy(&fi, &bits, sizeof(fi));
            auto& basis = inputs[1].getBasis();
            basis[2][0] = fi;
            basis[0][1] = id % 2 ? -0.0f : 0.125f;
            basis[2][1] = id % 3 ? 0.25f : -0.0f;
            const float scale = id < 24 ? 1.0f : (id < 48 ? 0.0009765625f : 1024.0f);
            basis[0][0] = scale;
            basis[1][0] = scale * 0.125f;
            inputs[1].setOrigin(btVector3(0.125f, -0.375f, 0.625f));
            inputs[2].setOrigin(btVector3(-0.0625f, 0.03125f, -0.0f));
        }
        btRigidBody a(1.0f, nullptr, nullptr, btVector3(1, 2, 3));
        btRigidBody b(2.0f, nullptr, nullptr, btVector3(3, 2, 1));
        a.setCenterOfMassTransform(inputs[0]);
        b.setCenterOfMassTransform(inputs[1]);
        Joint joint(a, b, inputs[2], inputs[3], id % 2 == 0);
        btTypedConstraint::btConstraintInfo1 info;
        joint.getInfo1(&info);
        std::printf("%d", id);
        for (const auto& input : inputs) transform(input);
        joint.output();
        std::printf("\n");
    }
}
