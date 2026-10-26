#include <BulletCollision/BroadphaseCollision/btDbvt.h>
#include <BulletCollision/BroadphaseCollision/btDbvtBroadphase.h>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

static btDbvtVolume volume(const std::uint32_t* words) {
    float v[6];
    std::memcpy(v, words, sizeof(v));
    return btDbvtVolume::FromMM(btVector3(v[0], v[1], v[2]), btVector3(v[3], v[4], v[5]));
}
static void words(const btDbvtVolume& v) {
    for (int i = 0; i < 6; ++i) {
        const float value = i < 3 ? v.Mins()[i] : v.Maxs()[i - 3];
        std::uint32_t bits;
        std::memcpy(&bits, &value, sizeof(bits));
        std::cout << ',' << bits;
    }
}
struct Leaves : btDbvt::ICollide {
    void Process(const btDbvtNode* n) { std::cout << reinterpret_cast<std::uintptr_t>(n->data) << ','; }
};
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string mode(argv[1]);
    if (mode == "select") {
        btDbvt tree;
        const btVector3 points[] = {btVector3(0.5f, 8388608.0f, 0.5f), btVector3(1, 8388608.0f, 0), btVector3(0, 0, 0)};
        for (std::uintptr_t i = 0; i < 3; ++i)
            tree.insert(btDbvtVolume::FromMM(points[i], points[i]), reinterpret_cast<void*>(i + 1));
        Leaves leaves;
        tree.collideTV(tree.m_root, btDbvtVolume::FromMM(btVector3(-1, -1, -1), btVector3(2, 8388609.0f, 2)), leaves);
        std::cout << '\n';
        return 0;
    }
    if (mode != "aabb" && mode != "archive-merge" && mode != "archive-intersect") return 2;
    for (unsigned id = 0; id < 51; ++id) {
        std::uint32_t input[12];
        for (auto& word : input) if (!(std::cin >> word)) return 3;
        const auto a = volume(input), b = volume(input + 6);
        std::cout << id;
        if (mode == "aabb") {
            std::cout << ',' << unsigned(Intersect(a, b));
            btDbvtVolume ab, ba;
            Merge(a, b, ab); Merge(b, a, ba);
            words(ab); words(ba);
        } else if (mode == "archive-merge") {
            for (int order = 0; order < 2; ++order) {
                btDbvt tree;
                tree.insert(order ? b : a, nullptr);
                tree.insert(order ? a : b, nullptr);
                words(tree.m_root->volume);
            }
        } else {
            btDbvtBroadphase broadphase;
            if (broadphase.m_deferedcollide) return 4;
            auto* p = broadphase.createProxy(a.Mins(), a.Maxs(), 0, nullptr, 1, 1, nullptr, nullptr);
            auto* q = broadphase.createProxy(b.Mins(), b.Maxs(), 0, nullptr, 1, 1, nullptr, nullptr);
            auto* cache = broadphase.getOverlappingPairCache();
            const int count = cache->getNumOverlappingPairs();
            if (count < 0 || count > 1 || bool(cache->findPair(p, q)) != bool(count)) return 5;
            std::cout << ',' << count;
            broadphase.destroyProxy(q, nullptr);
            broadphase.destroyProxy(p, nullptr);
            if (cache->getNumOverlappingPairs() != 0) return 6;
        }
        std::cout << '\n';
    }
    std::string extra;
    return std::cin >> extra ? 7 : 0;
}
