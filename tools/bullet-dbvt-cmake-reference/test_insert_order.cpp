#include <BulletCollision/BroadphaseCollision/btDbvt.h>
#include <cstdint>
#include <cstring>

static btDbvtVolume volume(const std::uint32_t* words) {
    float v[6];
    std::memcpy(v, words, sizeof(v));
    return btDbvtVolume::FromMM(btVector3(v[0], v[1], v[2]), btVector3(v[3], v[4], v[5]));
}

static std::uint32_t word(const btDbvtVolume& v, int i) {
    const float f = i < 3 ? v.Mins()[i] : v.Maxs()[i - 3];
    std::uint32_t bits;
    std::memcpy(&bits, &f, sizeof(bits));
    return bits;
}

int main() {
    const std::uint32_t cases[][12] = {
        {0x80000000, 0, 0, 0x3f800000, 0x3f800000, 0x3f800000,
         0, 0, 0, 0x3f800000, 0x3f800000, 0x3f800000},
        {0x7fc00001, 0, 0, 0x3f800000, 0x3f800000, 0x3f800000,
         0x7fc00002, 0, 0, 0x3f800000, 0x3f800000, 0x3f800000}
    };
    for (const auto& input : cases) {
        const auto a = volume(input), b = volume(input + 6);
        btDbvtVolume ab, ba;
        Merge(a, b, ab);
        Merge(b, a, ba);
        if (word(ab, 0) == word(ba, 0)) return 1;
        for (int order = 0; order < 2; ++order) {
            btDbvt tree;
            tree.insert(order ? b : a, nullptr);
            tree.insert(order ? a : b, nullptr);
            const auto& expected = order ? ab : ba;
            for (int i = 0; i < 6; ++i) if (word(tree.m_root->volume, i) != word(expected, i)) return 2;
        }
    }
}
