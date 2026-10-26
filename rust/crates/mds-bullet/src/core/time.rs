//! Altered Rust translation of btDiscreteDynamicsWorld::stepSimulation's clock.
//! See mod.rs for the zlib notice.

use super::InvalidArgument;

#[derive(Debug, Clone, Copy)]
pub struct StepClock {
    local_time: f32,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Step {
    /// Bullet returns this count, even when execution is clamped.
    pub requested: i32,
    pub executed: i32,
    pub dt: f32,
    pub remainder: f32,
}

impl StepClock {
    pub fn new() -> Self {
        Self {
            local_time: 1.0 / 60.0,
        }
    }

    pub fn advance(
        &mut self,
        dt: f32,
        max_substeps: i32,
        fixed: f32,
    ) -> Result<Step, InvalidArgument> {
        if !dt.is_finite() || dt < 0.0 || max_substeps < 0 || !fixed.is_finite() || fixed <= 0.0 {
            return Err(InvalidArgument);
        }
        let (requested, executed, step, remainder) = if max_substeps != 0 {
            let accumulated = self.local_time + dt;
            let count = if accumulated >= fixed {
                accumulated / fixed
            } else {
                0.0
            };
            // The native float-to-int conversion is undefined outside this range.
            if !count.is_finite() || count >= 2_147_483_648.0 {
                return Err(InvalidArgument);
            }
            let requested = count as i32;
            (
                requested,
                requested.min(max_substeps),
                fixed,
                accumulated - requested as f32 * fixed,
            )
        } else {
            let count = if dt.abs() < f32::EPSILON { 0 } else { 1 };
            (count, count, dt, dt)
        };
        self.local_time = remainder;
        Ok(Step {
            requested,
            executed,
            dt: step,
            remainder,
        })
    }
}
