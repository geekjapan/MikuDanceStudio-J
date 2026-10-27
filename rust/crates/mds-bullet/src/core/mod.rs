//! Native-free Bullet 2.75 migration core. Not yet connected to the public World.
//!
//! Altered Rust translation of the vendored Bullet sources, including local
//! changes. Pilot math/body/time operations were compared with stock Bullet 2.75
//! non-x86 branches. New math (including solver SSE dot) and shape inertia include
//! vendored local patches whose ancestry remains pending audit, as do unported
//! vendored ranges. This translation retains
//! the Bullet zlib license below; it is not an MIT relicensing of Bullet.
/*
Bullet Continuous Collision Detection and Physics Library
Copyright (c) 2003-2009 Erwin Coumans  http://bulletphysics.org
Copyright (c) 2003-2006 Erwin Coumans  http://continuousphysics.com/Bullet/
Copyright (c) 2003-2006 Gino van den Bergen / Erwin Coumans http://continuousphysics.com/Bullet/

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it freely,
subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim that you wrote the original software. If you use this software in a product, an acknowledgment in the product documentation would be appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
*/

#![forbid(unsafe_code)]

pub mod activation;
pub mod axis_sweep;
pub mod body;
pub mod box_box;
pub mod contact;
pub mod contact_solver;
pub mod gjk_epa;
pub mod gjk_pair;
pub mod joint_coordinates;
pub mod joint_rows;
pub mod math;
pub mod pair_cache;
pub mod shape;
pub mod simplex;
pub mod solver;
pub mod time;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct InvalidArgument;
