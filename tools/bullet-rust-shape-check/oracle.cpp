// Calls the actual vendored Bullet shapes. No shape formulas are reproduced here.
#include "BulletCollision/CollisionShapes/btSphereShape.h"
#include "BulletCollision/CollisionShapes/btBoxShape.h"
#include "BulletCollision/CollisionShapes/btCapsuleShape.h"
#include "BulletCollision/CollisionShapes/btStaticPlaneShape.h"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>

static float scalar(unsigned word) {
    float result;
    std::memcpy(&result, &word, sizeof result);
    return result;
}
static void word(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof bits);
    std::printf("\t%08x", bits);
}
static void vector(const btVector3& value) {
    for (int i = 0; i < 3; ++i) word(value[i]);
}
int main() {
    int id, kind;
    unsigned bits[12];
    while (std::scanf("%d%d", &id, &kind) == 2) {
        float v[12];
        for (int i = 0; i < 12; ++i) {
            if (std::scanf("%x", &bits[i]) != 1) return 2;
            v[i] = scalar(bits[i]);
        }
        std::unique_ptr<btCollisionShape> shape;
        btVector3 dimensions(0, 0, 0);
        switch (kind) {
        case 0: {
            auto s = new btSphereShape(v[0]);
            dimensions.setValue(s->getRadius(), 0, 0);
            shape.reset(s);
            break;
        }
        case 1: {
            auto s = new btBoxShape(btVector3(v[0], v[1], v[2]));
            dimensions = s->getHalfExtentsWithoutMargin();
            shape.reset(s);
            break;
        }
        case 2: {
            auto s = new btCapsuleShape(v[0], v[1]);
            dimensions.setValue(s->getRadius(), s->getHalfHeight(), s->getRadius());
            shape.reset(s);
            break;
        }
        case 3: {
            auto s = new btStaticPlaneShape(btVector3(v[0], v[1], v[2]), v[3]);
            dimensions = s->getPlaneNormal();
            shape.reset(s);
            break;
        }
        default: return 3;
        }
        btTransform t(btQuaternion(v[8], v[9], v[10], v[11]), btVector3(v[5], v[6], v[7]));
        btVector3 inertia, minimum, maximum;
        shape->calculateLocalInertia(v[4], inertia);
        shape->getAabb(t, minimum, maximum);
        std::printf("%d\t%d", id, kind);
        for (float value : v) word(value);
        word(shape->getMargin());
        vector(dimensions);
        vector(inertia);
        vector(minimum);
        vector(maximum);
        std::putchar('\n');
    }
    return std::ferror(stdin) ? 4 : 0;
}
