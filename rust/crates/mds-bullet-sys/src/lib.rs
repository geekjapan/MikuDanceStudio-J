//! Raw bindings to `shim/mds_bt.h`. Use the `mds-bullet` crate instead.
#![allow(non_camel_case_types)]

use std::os::raw::c_int;

#[repr(C)]
pub struct mds_bt_world {
    _private: [u8; 0],
}
#[repr(C)]
pub struct mds_bt_body {
    _private: [u8; 0],
}
#[repr(C)]
pub struct mds_bt_joint {
    _private: [u8; 0],
}

pub const MDS_BT_OK: c_int = 0;
pub const MDS_BT_ERR_NULL: c_int = -1;
pub const MDS_BT_ERR_INVALID: c_int = -2;
pub const MDS_BT_ERR_ALLOC: c_int = -3;
pub const MDS_BT_ERR_EXCEPTION: c_int = -4;

pub const MDS_BT_SHAPE_SPHERE: i32 = 0;
pub const MDS_BT_SHAPE_BOX: i32 = 1;
pub const MDS_BT_SHAPE_CAPSULE: i32 = 2;
pub const MDS_BT_SHAPE_STATIC_PLANE: i32 = 3;

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct mds_bt_body_desc {
    pub shape_kind: i32,
    pub shape_params: [f32; 4],
    pub mass: f32,
    pub linear_damping: f32,
    pub angular_damping: f32,
    pub restitution: f32,
    pub friction: f32,
    pub has_filter: i32,
    pub collision_group: u16,
    pub collision_mask: u16,
    pub kinematic: i32,
    pub position: [f32; 3],
    pub rotation: [f32; 4],
}

#[repr(C)]
#[derive(Clone, Copy, Debug)]
pub struct mds_bt_joint_desc {
    pub body_a: *mut mds_bt_body,
    pub body_b: *mut mds_bt_body,
    pub frame_a_position: [f32; 3],
    pub frame_a_rotation: [f32; 4],
    pub frame_b_position: [f32; 3],
    pub frame_b_rotation: [f32; 4],
    pub use_linear_reference_frame_a: i32,
    pub disable_collision_between_bodies: i32,
    pub linear_lower: [f32; 3],
    pub linear_upper: [f32; 3],
    pub angular_lower: [f32; 3],
    pub angular_upper: [f32; 3],
    pub spring_enabled: [i32; 6],
    pub spring_stiffness: [f32; 6],
}

extern "C" {
    pub fn mds_bt_live_counts(out: *mut i64) -> c_int;
    pub fn mds_bt_world_create() -> *mut mds_bt_world;
    pub fn mds_bt_world_destroy(world: *mut mds_bt_world);
    pub fn mds_bt_world_set_gravity(world: *mut mds_bt_world, x: f32, y: f32, z: f32) -> c_int;
    pub fn mds_bt_world_step(
        world: *mut mds_bt_world,
        dt: f32,
        max_sub_steps: i32,
        fixed_step: f32,
        out_substeps: *mut i32,
    ) -> c_int;
    pub fn mds_bt_world_state_hash(world: *mut mds_bt_world, out_hash: *mut u64) -> c_int;
    pub fn mds_bt_body_create(
        world: *mut mds_bt_world,
        desc: *const mds_bt_body_desc,
        out_body: *mut *mut mds_bt_body,
    ) -> c_int;
    pub fn mds_bt_body_get_transform(
        world: *mut mds_bt_world,
        body: *mut mds_bt_body,
        out_position: *mut f32,
        out_rotation: *mut f32,
    ) -> c_int;
    pub fn mds_bt_body_set_transform(
        world: *mut mds_bt_world,
        body: *mut mds_bt_body,
        position: *const f32,
        rotation: *const f32,
    ) -> c_int;
    pub fn mds_bt_joint_create(
        world: *mut mds_bt_world,
        desc: *const mds_bt_joint_desc,
        out_joint: *mut *mut mds_bt_joint,
    ) -> c_int;
}
