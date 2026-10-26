/* C ABI for the physics of the C++ app, object for object as it builds them:
 * the world of SceneConstruct (src/physics/scene_create.cpp), the bodies and
 * joints of CreateRigidBody and CreatePhysJoint (src/physics/physics_create.cpp),
 * and the body writes of src/physics/physics_frame.cpp. Matrices are D3DX
 * row-vector 4x4 in memory order (basis rows of Bullet = matrix columns).
 * The world owns its bodies and joints. Functions return MDS_BT_OK or a
 * negative MDS_BT_ERR_* code of mds_bt.h and never let an exception escape. */
#ifndef MDS_MMD_H
#define MDS_MMD_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct mds_mmd_world mds_mmd_world;
typedef struct mds_mmd_body mds_mmd_body;

/* SceneConstruct: bt32BitAxisSweep3, gravity (0, -98, 0), the ground plane.
 * NULL on failure. */
mds_mmd_world *mds_mmd_world_create(void);
void mds_mmd_world_destroy(mds_mmd_world *world);
int mds_mmd_world_set_gravity(mds_mmd_world *world, float x, float y, float z);
int mds_mmd_world_step(mds_mmd_world *world, float dt, int32_t max_sub_steps, float fixed_step);
/* The floor menu 285 (src/window/command_view_menu.cpp 1437-1455): the
 * ground's m_collisionFlags (x64 +0xE0, x86 +0xD4) becomes 1 when `on`,
 * the startup CF_STATIC_OBJECT, else -1, whose CF_NO_CONTACT_RESPONSE
 * lets bodies fall through. No other Bullet call, as in the C++. */
int mds_mmd_world_set_floor(mds_mmd_world *world, int32_t on);

/* CreateRigidBody. shape 0 sphere (sx), 1 box (sx, sy, sz), 2 capsule
 * (sx radius, sy height); `rotation` is the quaternion that setRotation
 * gets. mode 0 makes a kinematic body of mass 0. `group` and `mask` are the
 * shorts of addRigidBody. */
int mds_mmd_body_create(mds_mmd_world *world, int32_t shape, float sx, float sy, float sz,
                        const float origin[3], const float rotation[4], int32_t mode, float mass,
                        float linear_damping, float angular_damping, float restitution,
                        float friction, int16_t group, int16_t mask, mds_mmd_body **out_body);

/* CreatePhysJoint: btGeneric6DofSpringConstraint with frames from origin and
 * quaternion, limits, springs (enabled where > 0, then the equilibrium
 * point when any is) and the solver uid. */
int mds_mmd_joint_create(mds_mmd_world *world, mds_mmd_body *a, mds_mmd_body *b,
                         const float a_origin[3], const float a_rotation[4],
                         const float b_origin[3], const float b_rotation[4],
                         const float linear_lower[3], const float linear_upper[3],
                         const float angular_lower[3], const float angular_upper[3],
                         const float springs[6], int32_t uid);

/* Sets or clears CF_KINEMATIC_OBJECT (NotifyBonePhysicsMode). */
int mds_mmd_body_set_kinematic(mds_mmd_body *body, int32_t kinematic);
/* ModelKinematicSync: the motion state gets the matrix. */
int mds_mmd_body_set_motion_state(mds_mmd_body *body, const float matrix[16]);
/* ModelDynamicReseat: world transform, and the current and interpolation
 * velocities zeroed. */
int mds_mmd_body_reseat(mds_mmd_body *body, const float matrix[16]);
/* The readback's over-stretch stop: the origin moves, the current
 * velocities are zeroed. */
int mds_mmd_body_stop_at(mds_mmd_body *body, const float origin[3]);
/* The world transform as a D3DX matrix (TransformToMatrix). */
int mds_mmd_body_matrix(const mds_mmd_body *body, float out_matrix[16]);
/* The world transform origin and getRotation(), x y z w (the trace). */
int mds_mmd_body_pose(const mds_mmd_body *body, float out_origin[3], float out_rotation[4]);

#ifdef __cplusplus
}
#endif

#endif
