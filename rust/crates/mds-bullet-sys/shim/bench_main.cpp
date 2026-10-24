// The chain8 scene from the P1 prototype, driven through the C shim without
// Rust. mds-bullet's examples/chain8.rs is the Rust twin; keep them in step.
// Prints the final state hash and the mean time of one stepSimulation call.
#include "mds_bt.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>

static void check(int rc, const char *what) {
  if (rc != MDS_BT_OK) {
    std::fprintf(stderr, "%s failed: %d\n", what, rc);
    std::exit(1);
  }
}

static mds_bt_body_desc body_desc(int shape, float a, float b, float c, float d) {
  mds_bt_body_desc bd = {};
  bd.shape_kind = shape;
  bd.shape_params[0] = a;
  bd.shape_params[1] = b;
  bd.shape_params[2] = c;
  bd.shape_params[3] = d;
  bd.friction = 0.5f;
  bd.rotation[3] = 1.0f;
  return bd;
}

int main() {
  const int links = 8, frames = 600;
  mds_bt_world *w = mds_bt_world_create();
  if (!w) return 1;
  check(mds_bt_world_set_gravity(w, 0, -98.0f, 0), "gravity");

  mds_bt_body *tmp = nullptr;
  mds_bt_body_desc ground = body_desc(MDS_BT_SHAPE_STATIC_PLANE, 0, 1, 0, 0);
  check(mds_bt_body_create(w, &ground, &tmp), "ground");

  mds_bt_body *root = nullptr, *prev = nullptr;
  for (int i = 0; i <= links; ++i) {
    mds_bt_body_desc bd = body_desc(MDS_BT_SHAPE_CAPSULE, 0.4f, 1.2f, 0, 0);
    bd.mass = i == 0 ? 0.0f : 1.0f;
    bd.kinematic = i == 0;
    bd.linear_damping = 0.5f;
    bd.angular_damping = 0.5f;
    bd.position[0] = 0.3f * i;
    bd.position[1] = 20.0f - 1.6f * i;
    bd.position[2] = 0.1f * i;
    mds_bt_body *b = nullptr;
    check(mds_bt_body_create(w, &bd, &b), "body");
    if (i == 0) root = b;
    if (prev) {
      mds_bt_joint_desc jd = {};
      jd.body_a = prev;
      jd.body_b = b;
      jd.frame_a_position[1] = -0.8f;
      jd.frame_a_rotation[3] = 1.0f;
      jd.frame_b_position[1] = 0.8f;
      jd.frame_b_rotation[3] = 1.0f;
      jd.use_linear_reference_frame_a = 1;
      jd.disable_collision_between_bodies = 1;
      const float lo[3] = {-0.6f, -0.3f, -0.6f}, hi[3] = {0.6f, 0.3f, 0.6f};
      for (int k = 0; k < 3; ++k) {
        jd.angular_lower[k] = lo[k];
        jd.angular_upper[k] = hi[k];
      }
      for (int k = 3; k < 6; ++k) {
        jd.spring_enabled[k] = 1;
        jd.spring_stiffness[k] = 30.0f;
      }
      mds_bt_joint *j = nullptr;
      check(mds_bt_joint_create(w, &jd, &j), "joint");
    }
    prev = b;
  }

  double total_ns = 0;
  for (int frame = 0; frame < frames; ++frame) {
    float t = frame / 60.0f, x = 4.0f * t * (1.0f - t / 10.0f);
    float angle = 0.02f * frame;
    float s = (float)std::sin((double)(angle * 0.5f));
    float pos[3] = {x, 20.0f, 0.0f};
    float rot[4] = {0.0f * s, 0.0f * s, 1.0f * s, (float)std::cos((double)(angle * 0.5f))};
    check(mds_bt_body_set_transform(w, root, pos, rot), "set_transform");
    auto t0 = std::chrono::steady_clock::now();
    check(mds_bt_world_step(w, 1.0f / 30.0f, 1, 1.0f / 60.0f, nullptr), "step");
    auto t1 = std::chrono::steady_clock::now();
    total_ns += std::chrono::duration<double, std::nano>(t1 - t0).count();
  }
  uint64_t h = 0;
  check(mds_bt_world_state_hash(w, &h), "hash");
  std::printf("final %016llx\n", (unsigned long long)h);
  std::printf("mean_step_us %.3f\n", total_ns / frames / 1000.0);
  mds_bt_world_destroy(w);
  return 0;
}
