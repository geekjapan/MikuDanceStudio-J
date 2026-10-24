#include "mds_bt.h"

#include "btBulletDynamicsCommon.h"
#include "BulletDynamics/ConstraintSolver/btGeneric6DofSpringConstraint.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <memory>
#include <new>
#include <vector>

namespace {

std::atomic<int64_t> g_worlds{0}, g_bodies{0}, g_joints{0};

} // namespace

struct mds_bt_body {
  btRigidBody *rb = nullptr;
  btCollisionShape *shape = nullptr;
  btDefaultMotionState *ms = nullptr;
  bool kinematic = false;
  bool hashed = false; // non-static: dynamic or kinematic
};

struct mds_bt_joint {
  btGeneric6DofSpringConstraint *c = nullptr;
};

// Member order and construction match the P1 prototype scene.
struct mds_bt_world {
  btDefaultCollisionConfiguration cfg;
  btCollisionDispatcher disp{&cfg};
  btDbvtBroadphase bp;
  btSequentialImpulseConstraintSolver solver;
  btDiscreteDynamicsWorld w{&disp, &bp, &solver, &cfg};
  std::vector<mds_bt_body *> bodies;
  std::vector<mds_bt_joint *> joints;

  bool owns(const mds_bt_body *b) const {
    return b && std::find(bodies.begin(), bodies.end(), b) != bodies.end();
  }
};

namespace {

bool finite(const float *v, int n) {
  for (int i = 0; i < n; ++i)
    if (!std::isfinite(v[i])) return false;
  return true;
}

bool valid_rotation(const float q[4]) {
  return finite(q, 4) && (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]) > 1e-12f;
}

// setRotation divides by |q|^2, so q need not be unit. It is not normalized
// here, so the caller's bits reach Bullet unchanged.
btTransform make_transform(const float p[3], const float q[4]) {
  btTransform t;
  t.setIdentity();
  t.setOrigin(btVector3(p[0], p[1], p[2]));
  t.setRotation(btQuaternion(q[0], q[1], q[2], q[3]));
  return t;
}

btVector3 vec3(const float v[3]) { return btVector3(v[0], v[1], v[2]); }

void destroy_body(mds_bt_world *W, mds_bt_body *b) {
  W->w.removeRigidBody(b->rb);
  delete b->rb;
  delete b->ms;
  delete b->shape;
  delete b;
  --g_bodies;
}

template <class F> int guarded(F &&f) {
  try {
    return f();
  } catch (const std::bad_alloc &) {
    return MDS_BT_ERR_ALLOC;
  } catch (...) {
    return MDS_BT_ERR_EXCEPTION;
  }
}

} // namespace

extern "C" {

int mds_bt_live_counts(int64_t out[3]) {
  if (!out) return MDS_BT_ERR_NULL;
  out[0] = g_worlds.load();
  out[1] = g_bodies.load();
  out[2] = g_joints.load();
  return MDS_BT_OK;
}

mds_bt_world *mds_bt_world_create(void) {
  try {
    auto *W = new mds_bt_world();
    W->w.setGravity(btVector3(0, -9.8f, 0));
    ++g_worlds;
    return W;
  } catch (...) {
    return nullptr;
  }
}

void mds_bt_world_destroy(mds_bt_world *W) {
  if (!W) return;
  for (auto it = W->joints.rbegin(); it != W->joints.rend(); ++it) {
    W->w.removeConstraint((*it)->c);
    delete (*it)->c;
    delete *it;
    --g_joints;
  }
  for (auto it = W->bodies.rbegin(); it != W->bodies.rend(); ++it) destroy_body(W, *it);
  delete W;
  --g_worlds;
}

int mds_bt_world_set_gravity(mds_bt_world *W, float x, float y, float z) {
  if (!W) return MDS_BT_ERR_NULL;
  const float g[3] = {x, y, z};
  if (!finite(g, 3)) return MDS_BT_ERR_INVALID;
  W->w.setGravity(btVector3(x, y, z));
  return MDS_BT_OK;
}

int mds_bt_world_step(mds_bt_world *W, float dt, int32_t max_sub_steps, float fixed_step,
                      int32_t *out_substeps) {
  if (!W) return MDS_BT_ERR_NULL;
  if (!std::isfinite(dt) || dt < 0.0f || max_sub_steps < 0 || !std::isfinite(fixed_step) ||
      fixed_step <= 0.0f)
    return MDS_BT_ERR_INVALID;
  return guarded([&] {
    int n = W->w.stepSimulation(dt, max_sub_steps, fixed_step);
    if (out_substeps) *out_substeps = n;
    return MDS_BT_OK;
  });
}

int mds_bt_world_state_hash(mds_bt_world *W, uint64_t *out_hash) {
  if (!W || !out_hash) return MDS_BT_ERR_NULL;
  uint64_t h = 1469598103934665603ull;
  for (const auto *b : W->bodies) {
    if (!b->hashed) continue;
    btTransform t;
    b->ms->getWorldTransform(t);
    float v[15];
    for (int r = 0; r < 3; ++r)
      for (int c = 0; c < 3; ++c) v[r * 3 + c] = t.getBasis()[r][c];
    v[9] = t.getOrigin().x();
    v[10] = t.getOrigin().y();
    v[11] = t.getOrigin().z();
    v[12] = b->rb->getLinearVelocity().x();
    v[13] = b->rb->getAngularVelocity().y();
    v[14] = 0;
    const unsigned char *p = reinterpret_cast<const unsigned char *>(v);
    for (size_t i = 0; i < sizeof v; ++i) {
      h ^= p[i];
      h *= 1099511628211ull;
    }
  }
  *out_hash = h;
  return MDS_BT_OK;
}

int mds_bt_body_create(mds_bt_world *W, const mds_bt_body_desc *d, mds_bt_body **out) {
  if (!W || !d || !out) return MDS_BT_ERR_NULL;
  *out = nullptr;
  const float *sp = d->shape_params;
  if (!finite(sp, 4) || !finite(&d->mass, 1) || d->mass < 0.0f || !finite(&d->linear_damping, 1) ||
      !finite(&d->angular_damping, 1) || !finite(&d->restitution, 1) || !finite(&d->friction, 1) ||
      !finite(d->position, 3) || !valid_rotation(d->rotation))
    return MDS_BT_ERR_INVALID;

  return guarded([&] {
    std::unique_ptr<btCollisionShape> shape;
    switch (d->shape_kind) {
    case MDS_BT_SHAPE_SPHERE:
      if (sp[0] <= 0.0f) return MDS_BT_ERR_INVALID;
      shape.reset(new btSphereShape(sp[0]));
      break;
    case MDS_BT_SHAPE_BOX:
      if (sp[0] <= 0.0f || sp[1] <= 0.0f || sp[2] <= 0.0f) return MDS_BT_ERR_INVALID;
      shape.reset(new btBoxShape(btVector3(sp[0], sp[1], sp[2])));
      break;
    case MDS_BT_SHAPE_CAPSULE:
      if (sp[0] <= 0.0f || sp[1] < 0.0f) return MDS_BT_ERR_INVALID;
      shape.reset(new btCapsuleShape(sp[0], sp[1]));
      break;
    case MDS_BT_SHAPE_STATIC_PLANE: {
      const float len2 = sp[0] * sp[0] + sp[1] * sp[1] + sp[2] * sp[2];
      if (std::fabs(len2 - 1.0f) > 1e-3f || d->mass != 0.0f || d->kinematic)
        return MDS_BT_ERR_INVALID;
      shape.reset(new btStaticPlaneShape(btVector3(sp[0], sp[1], sp[2]), sp[3]));
      break;
    }
    default:
      return MDS_BT_ERR_INVALID;
    }

    const bool kinematic = d->kinematic != 0;
    const float mass = kinematic ? 0.0f : d->mass;
    btVector3 inertia(0, 0, 0);
    if (mass > 0) shape->calculateLocalInertia(mass, inertia);

    W->bodies.reserve(W->bodies.size() + 1);
    std::unique_ptr<btDefaultMotionState> ms(
        new btDefaultMotionState(make_transform(d->position, d->rotation)));
    btRigidBody::btRigidBodyConstructionInfo info(mass, ms.get(), shape.get(), inertia);
    info.m_linearDamping = d->linear_damping;
    info.m_angularDamping = d->angular_damping;
    info.m_restitution = d->restitution;
    info.m_friction = d->friction;
    std::unique_ptr<btRigidBody> rb(new btRigidBody(info));
    if (kinematic) {
      rb->setCollisionFlags(rb->getCollisionFlags() | btCollisionObject::CF_KINEMATIC_OBJECT);
      rb->setActivationState(DISABLE_DEACTIVATION);
    }
    std::unique_ptr<mds_bt_body> body(new mds_bt_body());
    if (d->has_filter)
      W->w.addRigidBody(rb.get(), static_cast<short>(d->collision_group),
                        static_cast<short>(d->collision_mask));
    else
      W->w.addRigidBody(rb.get());
    body->rb = rb.release();
    body->ms = ms.release();
    body->shape = shape.release();
    body->kinematic = kinematic;
    body->hashed = kinematic || mass > 0.0f;
    W->bodies.push_back(body.get());
    ++g_bodies;
    *out = body.release();
    return MDS_BT_OK;
  });
}

int mds_bt_body_get_transform(mds_bt_world *W, mds_bt_body *b, float pos[3], float rot[4]) {
  if (!W || !pos || !rot || !W->owns(b)) return MDS_BT_ERR_NULL;
  btTransform t;
  b->ms->getWorldTransform(t);
  const btVector3 &o = t.getOrigin();
  pos[0] = o.x();
  pos[1] = o.y();
  pos[2] = o.z();
  const btQuaternion q = t.getRotation();
  rot[0] = q.x();
  rot[1] = q.y();
  rot[2] = q.z();
  rot[3] = q.w();
  return MDS_BT_OK;
}

int mds_bt_body_set_transform(mds_bt_world *W, mds_bt_body *b, const float pos[3],
                              const float rot[4]) {
  if (!W || !pos || !rot || !W->owns(b)) return MDS_BT_ERR_NULL;
  // Static bodies are not re-registered with the broadphase, so they stay put.
  if (!b->hashed || !finite(pos, 3) || !valid_rotation(rot)) return MDS_BT_ERR_INVALID;
  const btTransform t = make_transform(pos, rot);
  b->ms->setWorldTransform(t);
  // A kinematic body derives its velocity from the motion state at the next
  // step, so it must not be teleported through the body itself.
  if (!b->kinematic) {
    b->rb->setWorldTransform(t);
    b->rb->setInterpolationWorldTransform(t);
  }
  return MDS_BT_OK;
}

int mds_bt_joint_create(mds_bt_world *W, const mds_bt_joint_desc *d, mds_bt_joint **out) {
  if (!W || !d || !out) return MDS_BT_ERR_NULL;
  *out = nullptr;
  if (!W->owns(d->body_a) || !W->owns(d->body_b)) return MDS_BT_ERR_NULL;
  if (d->body_a == d->body_b || !valid_rotation(d->frame_a_rotation) ||
      !valid_rotation(d->frame_b_rotation) || !finite(d->frame_a_position, 3) ||
      !finite(d->frame_b_position, 3) || !finite(d->linear_lower, 3) ||
      !finite(d->linear_upper, 3) || !finite(d->angular_lower, 3) ||
      !finite(d->angular_upper, 3) || !finite(d->spring_stiffness, 6))
    return MDS_BT_ERR_INVALID;

  return guarded([&] {
    W->joints.reserve(W->joints.size() + 1);
    std::unique_ptr<mds_bt_joint> joint(new mds_bt_joint());
    std::unique_ptr<btGeneric6DofSpringConstraint> c(new btGeneric6DofSpringConstraint(
        *d->body_a->rb, *d->body_b->rb, make_transform(d->frame_a_position, d->frame_a_rotation),
        make_transform(d->frame_b_position, d->frame_b_rotation),
        d->use_linear_reference_frame_a != 0));
    c->setLinearLowerLimit(vec3(d->linear_lower));
    c->setLinearUpperLimit(vec3(d->linear_upper));
    c->setAngularLowerLimit(vec3(d->angular_lower));
    c->setAngularUpperLimit(vec3(d->angular_upper));
    for (int k = 0; k < 6; ++k) {
      if (!d->spring_enabled[k]) continue;
      c->enableSpring(k, true);
      c->setStiffness(k, d->spring_stiffness[k]);
    }
    W->w.addConstraint(c.get(), d->disable_collision_between_bodies != 0);
    joint->c = c.release();
    W->joints.push_back(joint.get());
    ++g_joints;
    *out = joint.release();
    return MDS_BT_OK;
  });
}

} // extern "C"
