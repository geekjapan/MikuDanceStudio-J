#include "btBulletDynamicsCommon.h"
#include "BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint.h"
#include <cstdint>
#include <vector>
struct World {
  btDefaultCollisionConfiguration cfg; btCollisionDispatcher disp{&cfg};
  btDbvtBroadphase bp; btSequentialImpulseConstraintSolver solver;
  btDiscreteDynamicsWorld w{&disp, &bp, &solver, &cfg};
  std::vector<btRigidBody*> bodies; btRigidBody* root = nullptr;
};
extern "C" {
World* bt_world_new(int links) {
  auto* W = new World(); W->w.setGravity(btVector3(0, -98.0f, 0));
  auto* ground = new btStaticPlaneShape(btVector3(0, 1, 0), 0);
  auto* g = new btRigidBody(0, new btDefaultMotionState(), ground); W->w.addRigidBody(g);
  btRigidBody* prev = nullptr;
  for (int i = 0; i <= links; ++i) {
    btCollisionShape* s = new btCapsuleShape(0.4f, 1.2f);
    float mass = i == 0 ? 0.0f : 1.0f; btVector3 inertia(0, 0, 0);
    if (mass > 0) s->calculateLocalInertia(mass, inertia);
    btTransform t; t.setIdentity(); t.setOrigin(btVector3(0.3f * i, 20.0f - 1.6f * i, 0.1f * i));
    auto* b = new btRigidBody(btRigidBody::btRigidBodyConstructionInfo(mass, new btDefaultMotionState(t), s, inertia));
    if (i == 0) { b->setCollisionFlags(b->getCollisionFlags() | btCollisionObject::CF_KINEMATIC_OBJECT); b->setActivationState(DISABLE_DEACTIVATION); W->root = b; }
    b->setDamping(0.5f, 0.5f);
    W->w.addRigidBody(b); W->bodies.push_back(b);
    if (prev) {
      btTransform fa; fa.setIdentity(); fa.setOrigin(btVector3(0, -0.8f, 0));
      btTransform fb; fb.setIdentity(); fb.setOrigin(btVector3(0, 0.8f, 0));
      auto* c = new btGeneric6DofSpringConstraint(*prev, *b, fa, fb, true);
      c->setLinearLowerLimit(btVector3(0, 0, 0)); c->setLinearUpperLimit(btVector3(0, 0, 0));
      c->setAngularLowerLimit(btVector3(-0.6f, -0.3f, -0.6f)); c->setAngularUpperLimit(btVector3(0.6f, 0.3f, 0.6f));
      for (int k = 3; k < 6; ++k) { c->enableSpring(k, true); c->setStiffness(k, 30.0f); }
      W->w.addConstraint(c, true);
    }
    prev = b;
  }
  return W;
}
// Root follows a polynomial path so the driver itself uses no libm.
void bt_world_step(World* W, int frame) {
  float t = frame / 60.0f, x = 4.0f * t * (1.0f - t / 10.0f);
  btTransform tr; tr.setIdentity(); tr.setOrigin(btVector3(x, 20.0f, 0));
  btQuaternion q(btVector3(0, 0, 1), 0.02f * frame); tr.setRotation(q);
  W->root->getMotionState()->setWorldTransform(tr);
  W->w.stepSimulation(1.0f / 30.0f, 1, 1.0f / 60.0f);
}
uint64_t bt_world_hash(World* W) {
  uint64_t h = 1469598103934665603ull;
  for (auto* b : W->bodies) {
    btTransform t; b->getMotionState()->getWorldTransform(t);
    const btScalar* m = &t.getBasis()[0][0];
    float v[15];
    for (int r = 0; r < 3; ++r) for (int c = 0; c < 3; ++c) v[r * 3 + c] = t.getBasis()[r][c];
    v[9] = t.getOrigin().x(); v[10] = t.getOrigin().y(); v[11] = t.getOrigin().z();
    v[12] = b->getLinearVelocity().x(); v[13] = b->getAngularVelocity().y(); v[14] = 0; (void)m;
    const unsigned char* p = reinterpret_cast<const unsigned char*>(v);
    for (size_t i = 0; i < sizeof v; ++i) { h ^= p[i]; h *= 1099511628211ull; }
  }
  return h;
}
float bt_world_tip_y(World* W) { btTransform t; W->bodies.back()->getMotionState()->getWorldTransform(t); return t.getOrigin().y(); }
}
