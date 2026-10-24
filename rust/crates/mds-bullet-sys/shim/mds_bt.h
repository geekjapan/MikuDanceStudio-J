/* C ABI over the vendored Bullet 2.75. Handles are opaque. The world owns every
 * body and joint it creates and frees them in mds_bt_world_destroy. Every
 * function checks its handles and arguments and returns a status code; none
 * lets a C++ exception escape. Quaternions are x, y, z, w. */
#ifndef MDS_BT_H
#define MDS_BT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct mds_bt_world mds_bt_world;
typedef struct mds_bt_body mds_bt_body;
typedef struct mds_bt_joint mds_bt_joint;

enum {
  MDS_BT_OK = 0,
  MDS_BT_ERR_NULL = -1,      /* null or foreign handle, null pointer argument */
  MDS_BT_ERR_INVALID = -2,   /* non-finite, out-of-range, or unknown value */
  MDS_BT_ERR_ALLOC = -3,
  MDS_BT_ERR_EXCEPTION = -4
};

enum {
  MDS_BT_SHAPE_SPHERE = 0,       /* params: radius */
  MDS_BT_SHAPE_BOX = 1,          /* params: half extents x, y, z */
  MDS_BT_SHAPE_CAPSULE = 2,      /* params: radius, cylinder height (Y axis) */
  MDS_BT_SHAPE_STATIC_PLANE = 3  /* params: normal x, y, z, constant; mass must be 0 */
};

typedef struct mds_bt_body_desc {
  int32_t shape_kind;
  float shape_params[4];
  float mass;               /* 0 makes the body static; forced to 0 when kinematic */
  float linear_damping;
  float angular_damping;
  float restitution;
  float friction;
  int32_t has_filter;       /* 0: Bullet default group and mask */
  uint16_t collision_group;
  uint16_t collision_mask;
  int32_t kinematic;
  float position[3];
  float rotation[4];
} mds_bt_body_desc;

typedef struct mds_bt_joint_desc {
  mds_bt_body *body_a;
  mds_bt_body *body_b;
  float frame_a_position[3];
  float frame_a_rotation[4];
  float frame_b_position[3];
  float frame_b_rotation[4];
  int32_t use_linear_reference_frame_a;
  int32_t disable_collision_between_bodies;
  float linear_lower[3];
  float linear_upper[3];
  float angular_lower[3];
  float angular_upper[3];
  int32_t spring_enabled[6]; /* DOF 0..2 linear, 3..5 angular */
  float spring_stiffness[6];
} mds_bt_joint_desc;

/* Live object counts across all worlds, for leak tests. out[0]=worlds,
 * out[1]=bodies, out[2]=joints. */
int mds_bt_live_counts(int64_t out[3]);

/* Returns NULL on failure. */
mds_bt_world *mds_bt_world_create(void);
/* Frees the world and everything it owns. NULL is a no-op. */
void mds_bt_world_destroy(mds_bt_world *world);

int mds_bt_world_set_gravity(mds_bt_world *world, float x, float y, float z);
/* stepSimulation(dt, max_sub_steps, fixed_step). Writes the substep count to
 * out_substeps when it is not NULL. */
int mds_bt_world_step(mds_bt_world *world, float dt, int32_t max_sub_steps,
                      float fixed_step, int32_t *out_substeps);
/* FNV-1a over the transform (motion state), linear velocity x and angular
 * velocity y of every non-static body in creation order. Static bodies never
 * move and are skipped. */
int mds_bt_world_state_hash(mds_bt_world *world, uint64_t *out_hash);

int mds_bt_body_create(mds_bt_world *world, const mds_bt_body_desc *desc,
                       mds_bt_body **out_body);
int mds_bt_body_get_transform(mds_bt_world *world, mds_bt_body *body,
                              float out_position[3], float out_rotation[4]);
/* Fails with MDS_BT_ERR_INVALID for static bodies, which cannot be moved. */
int mds_bt_body_set_transform(mds_bt_world *world, mds_bt_body *body,
                              const float position[3], const float rotation[4]);

int mds_bt_joint_create(mds_bt_world *world, const mds_bt_joint_desc *desc,
                        mds_bt_joint **out_joint);

#ifdef __cplusplus
}
#endif

#endif
