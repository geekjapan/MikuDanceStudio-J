#include "BulletCollision/BroadphaseCollision/btDbvt.h"
#include "LinearMath/btAlignedAllocator.h"
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <iostream>

static void* pointers[32];
static unsigned count;
static unsigned events[32], released;
static void* allocate(size_t size) {
    assert(count < 32);
    void* pointer = std::malloc(size);
    assert(pointer);
    pointers[count++] = pointer;
    return pointer;
}
static void release(void* pointer) {
    if (!pointer) return;
    unsigned id = 0;
    while (id < count && pointers[id] != pointer) ++id;
    assert(id < count && released < 32);
    pointers[id] = nullptr;
    events[released++] = id;
    std::free(pointer);
}
int main() {
    btAlignedAllocSetCustom(allocate, release);
    for (unsigned scenario = 0; scenario < 5; ++scenario) {
        for (unsigned explicit_clear = 0; explicit_clear < 2; ++explicit_clear) {
            count = released = 0;
            {
                btDbvt tree;
                btDbvtNode* leaves[4];
                unsigned n = scenario == 0 ? 0 : scenario == 1 ? 1 : 4;
                for (unsigned i = 0; i < n; ++i) {
                    auto v = btDbvtVolume::FromMM(btVector3(i*3, 0, 0), btVector3(i*3+1, 1, 1));
                    leaves[i] = tree.insert(v, reinterpret_cast<void*>(uintptr_t(i)));
                }
                if (scenario == 3) tree.remove(leaves[3]);
                if (scenario == 4) for (auto* leaf : leaves) tree.remove(leaf);
                unsigned before = released;
                if (explicit_clear) { tree.clear(); tree.clear(); }
                std::cout << scenario << ',' << explicit_clear << ',' << count << ',' << before << '|';
            }
            assert(released == count);
            for (unsigned i = 0; i < released; ++i) std::cout << events[i] << ',';
            std::cout << '\n';
        }
    }
}
