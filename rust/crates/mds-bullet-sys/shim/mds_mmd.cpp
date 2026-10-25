#include "mds_mmd.h"
#include "mds_bt.h"

#include "btBulletDynamicsCommon.h"
#include "BulletCollision/BroadphaseCollision/btAxisSweep3.h"
#include "BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint.h"

#include <memory>
#include <new>
#include <vector>

struct mds_mmd_body {
  btRigidBody *rb;
  btCollisionShape *shape;
  btMotionState *ms;
};

// Construction order of SceneConstruct.
struct mds_mmd_world {
  btDefaultCollisionConfiguration cfg;
  btCollisionDispatcher disp{&cfg};
  bt32BitAxisSweep3 bp{btVector3(-10000.0f, -10000.0f, -10000.0f),
                       btVector3(10000.0f, 10000.0f, 10000.0f), 1500000};
  btSequentialImpulseConstraintSolver solver;
  btDiscreteDynamicsWorld w{&disp, &bp, &solver, &cfg};
  std::vector<mds_mmd_body *> bodies; // the ground first
  std::vector<btGeneric6DofSpringConstraint *> joints;
};

namespace {

template <class F> int guarded(F &&f) {
  try {
    return f();
  } catch (const std::bad_alloc &) {
    return MDS_BT_ERR_ALLOC;
  } catch (...) {
    return MDS_BT_ERR_EXCEPTION;
  }
}

// SetRotationOriginal, x64: btMatrix3x3::setRotation.
btTransform frame(const float origin[3], const float q[4]) {
  btTransform t;
  t.setIdentity();
  t.setOrigin(btVector3(origin[0], origin[1], origin[2]));
  t.getBasis().setRotation(btQuaternion(q[0], q[1], q[2], q[3]));
  return t;
}

// MatrixToBasis of physics_frame.cpp: basis rows are the D3DX columns.
btTransform from_matrix(const float *m) {
  btTransform t;
  t.setIdentity();
  t.getBasis().setValue(m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]);
  t.setOrigin(btVector3(m[12], m[13], m[14]));
  return t;
}

btVector3 vec3(const float v[3]) { return btVector3(v[0], v[1], v[2]); }

void add_body(mds_mmd_world *W, btCollisionShape *shape, float mass, btMotionState *ms,
              const btVector3 &inertia, short group, short mask, mds_mmd_body **out) {
  W->bodies.reserve(W->bodies.size() + 1);
  std::unique_ptr<btCollisionShape> s(shape);
  std::unique_ptr<btMotionState> m(ms);
  btRigidBody::btRigidBodyConstructionInfo ci(mass, ms, shape, inertia);
  std::unique_ptr<btRigidBody> rb(new btRigidBody(ci));
  std::unique_ptr<mds_mmd_body> body(new mds_mmd_body{rb.get(), shape, ms});
  W->w.addRigidBody(rb.get(), group, mask);
  rb.release();
  s.release();
  m.release();
  W->bodies.push_back(body.get());
  *out = body.release();
}

void destroy(mds_mmd_world *W) {
  for (auto it = W->joints.rbegin(); it != W->joints.rend(); ++it) {
    W->w.removeConstraint(*it);
    delete *it;
  }
  for (auto it = W->bodies.rbegin(); it != W->bodies.rend(); ++it) {
    W->w.removeRigidBody((*it)->rb);
    delete (*it)->rb;
    delete (*it)->ms;
    delete (*it)->shape;
    delete *it;
  }
  delete W;
}

} // namespace

extern "C" {

mds_mmd_world *mds_mmd_world_create(void) {
  mds_mmd_world *W = nullptr;
  try {
    W = new mds_mmd_world();
    W->w.getSolverInfo().m_solverMode &= ~1;
    W->w.setGravity(btVector3(0.0f, -98.0f, 0.0f));
    mds_mmd_body *ground = nullptr;
    add_body(W, new btStaticPlaneShape(btVector3(0.0f, 1.0f, 0.0f), 0.0f), 0.0f,
             new btDefaultMotionState(btTransform::getIdentity(), btTransform::getIdentity()),
             btVector3(0.0f, 0.0f, 0.0f), static_cast<short>(0x8000), static_cast<short>(-1),
             &ground);
    ground->rb->setRestitution(0.88f);
    return W;
  } catch (...) {
    if (W) destroy(W);
    return nullptr;
  }
}

void mds_mmd_world_destroy(mds_mmd_world *W) {
  if (W) destroy(W);
}

int mds_mmd_world_set_gravity(mds_mmd_world *W, float x, float y, float z) {
  if (!W) return MDS_BT_ERR_NULL;
  W->w.setGravity(btVector3(x, y, z));
  return MDS_BT_OK;
}

int mds_mmd_world_step(mds_mmd_world *W, float dt, int32_t max_sub_steps, float fixed_step) {
  if (!W) return MDS_BT_ERR_NULL;
  return guarded([&] {
    W->w.stepSimulation(dt, max_sub_steps, fixed_step);
    return MDS_BT_OK;
  });
}

int mds_mmd_body_create(mds_mmd_world *W, int32_t shape, float sx, float sy, float sz,
                        const float origin[3], const float rotation[4], int32_t mode, float mass,
                        float linear_damping, float angular_damping, float restitution,
                        float friction, int16_t group, int16_t mask, mds_mmd_body **out) {
  if (!W || !origin || !rotation || !out) return MDS_BT_ERR_NULL;
  *out = nullptr;
  if (shape < 0 || shape > 2) return MDS_BT_ERR_INVALID;
  return guarded([&] {
    btCollisionShape *s;
    if (shape == 0)
      s = new btSphereShape(sx);
    else if (shape == 1)
      s = new btBoxShape(btVector3(sx, sy, sz));
    else
      s = new btCapsuleShape(sx, sy);
    const float use_mass = mode ? mass : 0.0f;
    btVector3 inertia(0.0f, 0.0f, 0.0f);
    s->calculateLocalInertia(use_mass, inertia);
    btMotionState *ms = nullptr;
    try {
      ms = new btDefaultMotionState(frame(origin, rotation));
    } catch (...) {
      delete s;
      throw;
    }
    add_body(W, s, use_mass, ms, inertia, group, mask, out);
    btRigidBody *rb = (*out)->rb;
    rb->setDamping(linear_damping, angular_damping);
    rb->setRestitution(restitution);
    rb->setFriction(friction);
    if (mode == 0)
      rb->setCollisionFlags(rb->getCollisionFlags() | btCollisionObject::CF_KINEMATIC_OBJECT);
    rb->setActivationState(DISABLE_DEACTIVATION);
    return MDS_BT_OK;
  });
}

int mds_mmd_joint_create(mds_mmd_world *W, mds_mmd_body *a, mds_mmd_body *b,
                         const float a_origin[3], const float a_rotation[4],
                         const float b_origin[3], const float b_rotation[4],
                         const float linear_lower[3], const float linear_upper[3],
                         const float angular_lower[3], const float angular_upper[3],
                         const float springs[6], int32_t uid) {
  if (!W || !a || !b || !a_origin || !a_rotation || !b_origin || !b_rotation || !linear_lower ||
      !linear_upper || !angular_lower || !angular_upper || !springs)
    return MDS_BT_ERR_NULL;
  return guarded([&] {
    W->joints.reserve(W->joints.size() + 1);
    std::unique_ptr<btGeneric6DofSpringConstraint> c(new btGeneric6DofSpringConstraint(
        *a->rb, *b->rb, frame(a_origin, a_rotation), frame(b_origin, b_rotation), true));
    c->setLinearLowerLimit(vec3(linear_lower));
    c->setLinearUpperLimit(vec3(linear_upper));
    // VC9's fmod path gives +0 for a signed zero (CreatePhysJoint).
    const auto zero = [](float v) { return v == 0.0f ? 0.0f : v; };
    c->setAngularLowerLimit(
        btVector3(zero(angular_lower[0]), zero(angular_lower[1]), zero(angular_lower[2])));
    c->setAngularUpperLimit(
        btVector3(zero(angular_upper[0]), zero(angular_upper[1]), zero(angular_upper[2])));
    W->w.addConstraint(c.get(), false);
    btGeneric6DofSpringConstraint *con = c.release();
    W->joints.push_back(con);
    bool any = false;
    for (int axis = 0; axis < 6; ++axis) {
      if (springs[axis] > 0.0f) {
        con->enableSpring(axis, true);
        con->setStiffness(axis, springs[axis]);
        any = true;
      }
    }
    if (any) con->setEquilibriumPoint();
    con->setUid(uid);
    return MDS_BT_OK;
  });
}

int mds_mmd_body_set_kinematic(mds_mmd_body *body, int32_t kinematic) {
  if (!body) return MDS_BT_ERR_NULL;
  const int flags = body->rb->getCollisionFlags();
  body->rb->setCollisionFlags(kinematic ? flags | btCollisionObject::CF_KINEMATIC_OBJECT
                                        : flags & ~btCollisionObject::CF_KINEMATIC_OBJECT);
  return MDS_BT_OK;
}

int mds_mmd_body_set_motion_state(mds_mmd_body *body, const float m[16]) {
  if (!body || !m) return MDS_BT_ERR_NULL;
  body->ms->setWorldTransform(from_matrix(m));
  return MDS_BT_OK;
}

int mds_mmd_body_reseat(mds_mmd_body *body, const float m[16]) {
  if (!body || !m) return MDS_BT_ERR_NULL;
  const btVector3 zero(0.0f, 0.0f, 0.0f);
  btRigidBody *rb = body->rb;
  rb->setWorldTransform(from_matrix(m));
  rb->setLinearVelocity(zero);
  rb->setAngularVelocity(zero);
  rb->setInterpolationLinearVelocity(zero);
  rb->setInterpolationAngularVelocity(zero);
  return MDS_BT_OK;
}

int mds_mmd_body_stop_at(mds_mmd_body *body, const float origin[3]) {
  if (!body || !origin) return MDS_BT_ERR_NULL;
  const btVector3 zero(0.0f, 0.0f, 0.0f);
  btRigidBody *rb = body->rb;
  btTransform t = rb->getWorldTransform();
  t.setOrigin(vec3(origin));
  rb->setWorldTransform(t);
  rb->setLinearVelocity(zero);
  rb->setAngularVelocity(zero);
  return MDS_BT_OK;
}

int mds_mmd_body_matrix(const mds_mmd_body *body, float out[16]) {
  if (!body || !out) return MDS_BT_ERR_NULL;
  const btTransform &t = body->rb->getWorldTransform();
  const btMatrix3x3 &b = t.getBasis();
  const btVector3 &o = t.getOrigin();
  for (int c = 0; c < 3; ++c) {
    out[4 * c + 0] = b[0][c];
    out[4 * c + 1] = b[1][c];
    out[4 * c + 2] = b[2][c];
    out[4 * c + 3] = 0.0f;
  }
  out[12] = o.x();
  out[13] = o.y();
  out[14] = o.z();
  out[15] = 1.0f;
  return MDS_BT_OK;
}

int mds_mmd_body_pose(const mds_mmd_body *body, float origin[3], float rotation[4]) {
  if (!body || !origin || !rotation) return MDS_BT_ERR_NULL;
  const btTransform &t = body->rb->getWorldTransform();
  const btVector3 &o = t.getOrigin();
  const btQuaternion q = t.getRotation();
  origin[0] = o.x();
  origin[1] = o.y();
  origin[2] = o.z();
  rotation[0] = q.x();
  rotation[1] = q.y();
  rotation[2] = q.z();
  rotation[3] = q.w();
  return MDS_BT_OK;
}

} // extern "C"
