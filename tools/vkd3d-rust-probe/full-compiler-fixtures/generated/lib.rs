#![allow(clippy::missing_safety_doc)]
#![allow(dead_code)]
#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(non_upper_case_globals)]
#![allow(unsafe_op_in_unsafe_fn)]
#![allow(unused_assignments)]
#![allow(unused_mut)]
#![feature(c_variadic)]
#![feature(core_intrinsics)]
#![feature(extern_types)]

#[macro_use]
extern crate c2rust_bitfields;#[macro_use]
extern crate memoffset;
extern crate libc;

pub mod src {
pub mod vkd3d_common {
pub mod blob;
pub mod debug;
pub mod error;
pub mod memory;
pub mod utf8;
} // mod vkd3d_common
pub mod vkd3d_shader {
pub mod checksum;
pub mod d3d_asm;
pub mod d3dbc;
pub mod dxbc;
pub mod dxil;
pub mod fx;
pub mod glsl;
pub mod hlsl;
pub mod hlsl_codegen;
pub mod hlsl_constant_ops;
pub mod hlsl_tab;
pub mod hlsl_yy;
pub mod ir;
pub mod msl;
pub mod preproc_tab;
pub mod preproc_yy;
pub mod spirv;
pub mod tpf;
pub mod vkd3d_shader_main;
} // mod vkd3d_shader
} // mod src
