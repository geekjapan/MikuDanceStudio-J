//! Altered Rust translation of Bullet 2.75 joint row assembly, including local
//! patches whose ancestry remains pending audit. Coordinate calculation and the
//! solver's mass, inertia and impulse processing are outside this module.
/*
Bullet Continuous Collision Detection and Physics Library, http://bulletphysics.org
Copyright (C) 2006, 2007 Sony Computer Entertainment Inc.

This software is provided 'as-is', without any express or implied warranty.
In no event will the authors be held liable for any damages arising from the use of this software.
Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it freely,
subject to the following restrictions:

1. The origin of this software must not be misrepresented; you must not claim that you wrote the original software. If you use this software in a product, an acknowledgment in the product documentation would be appreciated but is not required.
2. Altered source versions must be plainly marked as such, and must not be misrepresented as being the original software.
3. This notice may not be removed or altered from any source distribution.
*/

use super::math::{Basis, Vec3};

#[derive(Clone, Copy, Debug)]
pub struct JointCoordinates {
    pub basis_a_world: Basis,
    pub pivot_b_world: Vec3,
    pub linear_diff: Vec3,
    pub angular_diff: Vec3,
    pub angular_axes: [Vec3; 3],
}

#[derive(Clone, Copy, Debug)]
pub struct JointBodySnapshot {
    pub origin: Vec3,
    pub linear_velocity: Vec3,
    pub angular_velocity: Vec3,
}

#[derive(Clone, Copy, Debug)]
pub struct JointStep {
    pub fps: f32,
    pub erp: f32,
    pub iterations: u32,
}

#[derive(Clone, Copy, Debug)]
pub struct AxisMotor {
    pub lower: f32,
    pub upper: f32,
    pub enabled: bool,
    pub target_velocity: f32,
    pub max_motor_force: f32,
    pub current_position: f32,
    pub current_limit: u8,
    pub current_limit_error: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct AngularMotor {
    pub motor: AxisMotor,
    pub erp: f32,
    pub bounce: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct Spring {
    pub enabled: bool,
    pub equilibrium: f32,
    pub stiffness: f32,
    pub damping: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct JointState {
    pub linear: [AxisMotor; 3],
    pub angular: [AngularMotor; 3],
    pub linear_erp: f32,
    pub springs: [Spring; 6],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum JointAxis {
    LinearX,
    LinearY,
    LinearZ,
    AngularX,
    AngularY,
    AngularZ,
}

#[derive(Clone, Copy, Debug)]
pub struct JointRow {
    pub axis: JointAxis,
    pub j1_linear: Vec3,
    pub j1_angular: Vec3,
    pub j2_angular: Vec3,
    pub positional_rhs: f32,
    pub cfm: f32,
    pub lower_impulse: f32,
    pub upper_impulse: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct JointRows {
    rows: [JointRow; 6],
    len: usize,
}

impl JointRows {
    pub fn as_slice(&self) -> &[JointRow] {
        &self.rows[..self.len]
    }
}

impl AxisMotor {
    fn test_limit(&mut self, position: f32, angular: bool) {
        self.current_position = position;
        self.current_limit = 0;
        if self.lower <= self.upper {
            if position < self.lower {
                self.current_limit = if angular { 1 } else { 2 };
                self.current_limit_error = position - self.lower;
            } else if position > self.upper {
                self.current_limit = if angular { 2 } else { 1 };
                self.current_limit_error = position - self.upper;
            }
        }
        if !angular && self.current_limit == 0 {
            self.current_limit_error = 0.0;
        }
    }

    fn needs_row(self) -> bool {
        self.enabled || self.current_limit != 0
    }
}

fn normalize_angle(angle: f32) -> f32 {
    let angle = angle % std::f32::consts::TAU;
    if angle < -std::f32::consts::PI {
        angle + std::f32::consts::TAU
    } else if angle > std::f32::consts::PI {
        angle - std::f32::consts::TAU
    } else {
        angle
    }
}

fn adjust_angle(angle: f32, lower: f32, upper: f32) -> f32 {
    if lower >= upper {
        angle
    } else if angle < lower {
        if normalize_angle(lower - angle) < normalize_angle(upper - angle).abs() {
            angle
        } else {
            angle + std::f32::consts::TAU
        }
    } else if angle > upper && normalize_angle(angle - lower).abs() < normalize_angle(angle - upper)
    {
        angle - std::f32::consts::TAU
    } else {
        angle
    }
}

fn motor_factor(motor: AxisMotor, velocity: f32, time_factor: f32) -> f32 {
    if motor.lower > motor.upper {
        return 1.0;
    }
    if motor.lower == motor.upper {
        return 0.0;
    }
    let delta = velocity / time_factor;
    if delta < 0.0 {
        if motor.current_position >= motor.lower && motor.current_position < motor.lower - delta {
            (motor.lower - motor.current_position) / delta
        } else if motor.current_position < motor.lower {
            0.0
        } else {
            1.0
        }
    } else if delta > 0.0 {
        if motor.current_position <= motor.upper && motor.current_position > motor.upper - delta {
            (motor.upper - motor.current_position) / delta
        } else if motor.current_position > motor.upper {
            0.0
        } else {
            1.0
        }
    } else {
        0.0
    }
}

/// Requires finite native-calculated coordinates and motor/spring inputs,
/// positive fps/iterations, and setter-normalized angular limits.
/// Spring enablement and motor enablement are independent stored setter state.
pub fn generate_rows(
    coordinates: JointCoordinates,
    bodies: [JointBodySnapshot; 2],
    step: JointStep,
    state: &mut JointState,
) -> JointRows {
    for i in 0..3 {
        state.linear[i].test_limit(coordinates.linear_diff.0[i], false);
        let angular = &mut state.angular[i].motor;
        let angle = adjust_angle(coordinates.angular_diff.0[i], angular.lower, angular.upper);
        angular.test_limit(angle, true);
    }
    let blank = JointRow {
        axis: JointAxis::LinearX,
        j1_linear: Vec3::ZERO,
        j1_angular: Vec3::ZERO,
        j2_angular: Vec3::ZERO,
        positional_rhs: 0.0,
        cfm: 0.0,
        lower_impulse: -f32::MAX,
        upper_impulse: f32::MAX,
    };
    let mut result = JointRows {
        rows: [blank; 6],
        len: 0,
    };
    if !state.linear.iter().any(|m| m.needs_row())
        && !state.angular.iter().any(|m| m.motor.needs_row())
    {
        return result;
    }
    for i in 0..6 {
        let spring = state.springs[i];
        if spring.enabled {
            let (position, motor) = if i < 3 {
                (coordinates.linear_diff.0[i], &mut state.linear[i])
            } else {
                (
                    coordinates.angular_diff.0[i - 3],
                    &mut state.angular[i - 3].motor,
                )
            };
            let delta = position - spring.equilibrium;
            let force = if i < 3 { delta } else { -delta } * spring.stiffness;
            let velocity_factor = (step.fps * spring.damping) / step.iterations as f32;
            motor.target_velocity = velocity_factor * force;
            motor.max_motor_force = force.abs() / step.fps;
        }
    }
    let axes = [
        JointAxis::LinearX,
        JointAxis::LinearY,
        JointAxis::LinearZ,
        JointAxis::AngularX,
        JointAxis::AngularY,
        JointAxis::AngularZ,
    ];
    for (i, axis_id) in axes.into_iter().enumerate() {
        let rotational = i >= 3;
        let (motor, erp, bounce) = if rotational {
            let angular = state.angular[i - 3];
            (angular.motor, angular.erp, angular.bounce)
        } else {
            (state.linear[i], state.linear_erp, 0.0)
        };
        if !motor.needs_row() {
            continue;
        }
        let axis = if rotational {
            coordinates.angular_axes[i - 3]
        } else {
            Vec3(std::array::from_fn(|r| coordinates.basis_a_world.0[r][i]))
        };
        let mut row = JointRow {
            axis: axis_id,
            ..blank
        };
        if rotational {
            row.j1_angular = axis;
            row.j2_angular = axis.negate();
        } else {
            row.j1_linear = axis;
            row.j1_angular = coordinates.pivot_b_world.sub(bodies[0].origin).cross(axis);
            row.j2_angular = coordinates
                .pivot_b_world
                .sub(bodies[1].origin)
                .cross(axis)
                .negate();
        }
        let limited = motor.current_limit != 0;
        let powered = motor.enabled && !(limited && motor.lower == motor.upper);
        if powered && !limited {
            let velocity = if rotational {
                motor.target_velocity
            } else {
                -motor.target_velocity
            };
            row.positional_rhs +=
                motor_factor(motor, velocity, step.fps * step.erp) * motor.target_velocity;
            row.lower_impulse = -motor.max_motor_force;
            row.upper_impulse = motor.max_motor_force;
        }
        if limited {
            let k = step.fps * erp;
            row.positional_rhs += if rotational { -k } else { k } * motor.current_limit_error;
            if motor.lower != motor.upper {
                if motor.current_limit == 1 {
                    row.lower_impulse = 0.0;
                } else {
                    row.upper_impulse = 0.0;
                }
                if bounce > 0.0 {
                    let a = if rotational {
                        bodies[0].angular_velocity
                    } else {
                        bodies[0].linear_velocity
                    }
                    .0;
                    let b = if rotational {
                        bodies[1].angular_velocity
                    } else {
                        bodies[1].linear_velocity
                    }
                    .0;
                    let x = axis.0;
                    // The local native patch uses this asymmetric lane association.
                    let mut velocity = (a[1] * x[1] + a[2] * x[2]) + a[0] * x[0];
                    velocity -= b[0] * x[0] + (b[1] * x[1] + b[2] * x[2]);
                    let bounced = -bounce * velocity;
                    if (motor.current_limit == 1 && velocity < 0.0 && bounced > row.positional_rhs)
                        || (motor.current_limit != 1
                            && velocity > 0.0
                            && bounced < row.positional_rhs)
                    {
                        row.positional_rhs = bounced;
                    }
                }
            }
        }
        result.rows[result.len] = row;
        result.len += 1;
    }
    result
}
