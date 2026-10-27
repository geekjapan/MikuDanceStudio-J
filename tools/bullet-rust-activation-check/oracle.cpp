#include "btBulletDynamicsCommon.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>

class ActivationWorld : public btDiscreteDynamicsWorld {
public:
    using btDiscreteDynamicsWorld::btDiscreteDynamicsWorld;
    using btDiscreteDynamicsWorld::updateActivationState;
};

static float scalar() {
    std::string word;
    std::cin >> word;
    uint32_t bits = uint32_t(std::stoul(word, nullptr, 16));
    float result;
    std::memcpy(&result, &bits, sizeof(result));
    return result;
}
static void word(float value) {
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    char text[10];
    std::snprintf(text, sizeof(text), "%08x", bits);
    std::cout << '\t' << text;
}
int main() {
    btDefaultCollisionConfiguration config;
    btCollisionDispatcher dispatcher(&config);
    btDbvtBroadphase broadphase;
    ActivationWorld world(&dispatcher, &broadphase, nullptr, &config);
    btSphereShape shape(1);
    std::unique_ptr<btRigidBody> body;
    std::string id, op;
    while (std::cin >> id >> op) {
        if (op == "reset") {
            if (body) world.removeRigidBody(body.get());
            body.reset(new btRigidBody(1, nullptr, &shape, btVector3(1,1,1)));
            world.addRigidBody(body.get());
            gDeactivationTime = 2;
            gDisableDeactivation = false;
        } else if (op == "force" || op == "set") {
            int state; std::cin >> state;
            if (op == "force") body->forceActivationState(state);
            else body->setActivationState(state);
        } else if (op == "time") body->setDeactivationTime(scalar());
        else if (op == "thresholds") {
            float linear = scalar(), angular = scalar();
            body->setSleepingThresholds(linear, angular);
        } else if (op == "flags") {
            int flags; std::cin >> flags; body->setCollisionFlags(flags);
        } else if (op == "velocities") {
            float v[6]; for (float &x : v) x = scalar();
            body->setLinearVelocity(btVector3(v[0],v[1],v[2]));
            body->setAngularVelocity(btVector3(v[3],v[4],v[5]));
        } else if (op == "settings") {
            gDeactivationTime = scalar();
            int disabled; std::cin >> disabled; gDisableDeactivation = disabled != 0;
        } else if (op == "activate") {
            int force; std::cin >> force; body->activate(force != 0);
        } else if (op == "update") body->updateDeactivation(scalar());
        else if (op == "world") world.updateActivationState(scalar());
        else if (op != "query") return 2;
        std::cout << id << '\t' << body->getActivationState() << '\t' << body->isActive()
                  << '\t' << body->wantsSleeping() << '\t' << body->getCollisionFlags();
        word(body->getDeactivationTime());
        word(body->getLinearSleepingThreshold()); word(body->getAngularSleepingThreshold());
        for (int j=0;j<3;j++) word(body->getLinearVelocity()[j]);
        for (int j=0;j<3;j++) word(body->getAngularVelocity()[j]);
        word(gDeactivationTime); std::cout << '\t' << gDisableDeactivation << '\n';
    }
    if (body) world.removeRigidBody(body.get());
}
