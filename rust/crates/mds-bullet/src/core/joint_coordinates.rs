//! Altered Rust translation of patched Bullet 2.75 joint coordinates.
//! Local patch ancestry remains pending audit. The production backend stays native.
/*
Bullet Continuous Collision Detection and Physics Library
Copyright (c) 2003-2006 Erwin Coumans  http://continuousphysics.com/Bullet/

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it freely,
subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim that you wrote the original software. If you use this software in a product, an acknowledgment in the product documentation would be appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
*/
/*
2007-09-09
Refactored by Francisco Le?n
email: projectileman@yahoo.com
http://gimpact.sf.net
*/

use super::joint_rows::JointCoordinates;
use super::math::{Basis, Transform, Vec3};

#[derive(Clone, Copy, Debug)]
pub struct CalculatedJointCoordinates {
    pub frames_world: [Transform; 2],
    pub coordinates: JointCoordinates,
}

/// Requires finite transforms, a nonsingular calculated A basis, and nonzero axes.
pub fn calculate_coordinates(
    body_a: Transform,
    body_b: Transform,
    frame_a: Transform,
    frame_b: Transform,
) -> CalculatedJointCoordinates {
    let a = world_frame(body_a, frame_a);
    let b = world_frame(body_b, frame_b);
    let m = a.basis.0;
    let n = b.basis.0;
    let co0 = m[1][1] * m[2][2] - m[1][2] * m[2][1];
    let co1 = m[2][0] * m[1][2] - m[1][0] * m[2][2];
    let co2 = m[1][0] * m[2][1] - m[2][0] * m[1][1];
    // Linear and angular determinant folds differ in the original patch.
    let linear_s = 1.0 / ((m[0][1] * co1 + co2 * m[0][2]) + co0 * m[0][0]);
    let [dx, dy, dz] = b.origin.sub(a.origin).0;
    let v12 = (m[0][1] * m[2][0] - m[0][0] * m[2][1]) * linear_s;
    let v29 = (m[0][2] * m[1][0] - m[0][0] * m[1][2]) * linear_s;
    let v30 = (m[0][0] * m[2][2] - m[0][2] * m[2][0]) * linear_s;
    let v31 = co2 * linear_s;
    let v32 = (m[0][0] * m[1][1] - m[0][1] * m[1][0]) * linear_s;
    let linear_diff = Vec3([
        ((co0 * linear_s) * dx + dz * ((m[0][1] * m[1][2] - m[0][2] * m[1][1]) * linear_s))
            + ((m[0][2] * m[2][1] - m[0][1] * m[2][2]) * linear_s) * dy,
        ((co1 * linear_s) * dx + dz * v29) + v30 * dy,
        (v31 * dx + dz * v32) + v12 * dy,
    ]);
    let s = 1.0 / ((co2 * m[0][2] + m[0][1] * co1) + m[0][0] * co0);
    let inv = [
        [
            co0 * s,
            (m[0][2] * m[2][1] - m[0][1] * m[2][2]) * s,
            (m[0][1] * m[1][2] - m[0][2] * m[1][1]) * s,
        ],
        [
            co1 * s,
            (m[0][0] * m[2][2] - m[0][2] * m[2][0]) * s,
            (m[0][2] * m[1][0] - m[0][0] * m[1][2]) * s,
        ],
        [
            co2 * s,
            (m[0][1] * m[2][0] - m[0][0] * m[2][1]) * s,
            (m[0][0] * m[1][1] - m[0][1] * m[1][0]) * s,
        ],
    ];
    let relative: [[f32; 3]; 3] = std::array::from_fn(|i| {
        std::array::from_fn(|j| {
            let p0 = inv[i][0] * n[0][j];
            let p1 = inv[i][1] * n[1][j];
            let p2 = inv[i][2] * n[2][j];
            if j == 0 || (i == 2 && j == 1) {
                (p0 + p1) + p2
            } else if i == 2 {
                (p1 + p2) + p0
            } else {
                (p0 + p2) + p1
            }
        })
    });
    let fi = relative[2][0];
    let angular_diff = if fi < 1.0 {
        if fi > -1.0 {
            Vec3([
                (-(relative[2][1] as f64)).atan2(relative[2][2] as f64) as f32,
                (fi as f64).asin() as f32,
                (-(relative[1][0] as f64)).atan2(relative[0][0] as f64) as f32,
            ])
        } else {
            Vec3([
                -(relative[0][1] as f64).atan2(relative[1][1] as f64) as f32,
                -std::f32::consts::FRAC_PI_2,
                0.0,
            ])
        }
    } else {
        Vec3([
            (relative[0][1] as f64).atan2(relative[1][1] as f64) as f32,
            std::f32::consts::FRAC_PI_2,
            0.0,
        ])
    };
    let a1 = Vec3([
        m[1][2] * n[2][0] - m[2][2] * n[1][0],
        m[2][2] * n[0][0] - n[2][0] * m[0][2],
        n[1][0] * m[0][2] - m[1][2] * n[0][0],
    ]);
    let [x, y, z] = a1.0;
    let a0 = Vec3([
        m[2][2] * y - m[1][2] * z,
        m[0][2] * z - m[2][2] * x,
        m[1][2] * x - m[0][2] * y,
    ]);
    let a2 = Vec3([
        n[1][0] * z - n[2][0] * y,
        n[2][0] * x - z * n[0][0],
        y * n[0][0] - n[1][0] * x,
    ]);
    CalculatedJointCoordinates {
        frames_world: [a, b],
        coordinates: JointCoordinates {
            basis_a_world: a.basis,
            pivot_b_world: b.origin,
            linear_diff,
            angular_diff,
            angular_axes: [a0, a1, a2].map(normalize_axis),
        },
    }
}

fn world_frame(body: Transform, frame: Transform) -> Transform {
    let m = body.basis.0;
    let n = frame.basis.0;
    let fold = |i: usize, p0: f32, p1: f32, p2: f32| {
        if i == 0 {
            (p0 + p1) + p2
        } else {
            (p1 + p2) + p0
        }
    };
    Transform {
        basis: Basis(std::array::from_fn(|i| {
            std::array::from_fn(|j| {
                fold(i, n[0][j] * m[i][0], n[1][j] * m[i][1], n[2][j] * m[i][2])
            })
        })),
        origin: Vec3(std::array::from_fn(|i| {
            fold(
                i,
                m[i][0] * frame.origin.0[0],
                m[i][1] * frame.origin.0[1],
                m[i][2] * frame.origin.0[2],
            ) + body.origin.0[i]
        })),
    }
}

fn normalize_axis(axis: Vec3) -> Vec3 {
    let [x, y, z] = axis.0.map(f64::from);
    let reciprocal = (1.0 / ((x * x + y * y) + z * z).sqrt()) as f32;
    Vec3(axis.0.map(|v| reciprocal * v))
}
