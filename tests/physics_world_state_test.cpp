#include "mikudancestudio/physics_world_state.hpp"

#include "btBulletDynamicsCommon.h"

#include <cstdio>

int main() {
    mikudancestudio::PhysicsWorldState state;
    mikudancestudio::DestroyPhysicsWorld(state);  // interrupted startup
    mikudancestudio::CreatePhysicsWorld(state);

    if (state.world == nullptr || state.groundBody == nullptr ||
        state.world->getNumCollisionObjects() != 1 ||
        state.world->getGravity() != btVector3(0.0f, -98.0f, 0.0f) ||
        state.groundBody->getRestitution() != 0.88f) {
        std::fputs("headless physics world did not match its initialization contract\n", stderr);
        return 1;
    }

    mikudancestudio::DestroyPhysicsWorld(state);
    mikudancestudio::DestroyPhysicsWorld(state);  // repeat shutdown
    if (state.world || state.groundBody || state.solver || state.broadphase ||
        state.dispatcher || state.collisionConfig) {
        std::fputs("headless physics world retained owned pointers\n", stderr);
        return 1;
    }
    std::puts("headless physics world creation and cleanup passed");
}
