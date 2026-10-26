use super::core::math;
#[path = "../../src/core/joint_rows.rs"]
mod joint_rows;

use joint_rows::*;
use math::{Basis, Vec3};

struct Words<'a>(std::slice::Iter<'a, u32>);
impl Words<'_> {
    fn word(&mut self) -> u32 {
        *self.0.next().expect("fixture word")
    }
    fn scalar(&mut self) -> f32 {
        f32::from_bits(self.word())
    }
    fn vector(&mut self) -> Vec3 {
        Vec3(std::array::from_fn(|_| self.scalar()))
    }
    fn motor(&mut self) -> AxisMotor {
        AxisMotor {
            lower: self.scalar(),
            upper: self.scalar(),
            enabled: self.word() != 0,
            target_velocity: self.scalar(),
            max_motor_force: self.scalar(),
            current_position: self.scalar(),
            current_limit: self.word() as u8,
            current_limit_error: self.scalar(),
        }
    }
    fn state(&mut self) -> JointState {
        JointState {
            linear: std::array::from_fn(|_| self.motor()),
            angular: std::array::from_fn(|_| AngularMotor {
                motor: self.motor(),
                erp: self.scalar(),
                bounce: self.scalar(),
            }),
            linear_erp: self.scalar(),
            springs: std::array::from_fn(|_| Spring {
                enabled: self.word() != 0,
                equilibrium: self.scalar(),
                stiffness: self.scalar(),
                damping: self.scalar(),
            }),
        }
    }
}

fn motor_words(m: AxisMotor, out: &mut Vec<u32>) {
    out.extend([
        m.lower.to_bits(),
        m.upper.to_bits(),
        m.enabled as u32,
        m.target_velocity.to_bits(),
        m.max_motor_force.to_bits(),
        m.current_position.to_bits(),
        m.current_limit as u32,
        m.current_limit_error.to_bits(),
    ]);
}
fn state_words(state: JointState, out: &mut Vec<u32>) {
    for m in state.linear {
        motor_words(m, out);
    }
    for m in state.angular {
        motor_words(m.motor, out);
        out.extend([m.erp.to_bits(), m.bounce.to_bits()]);
    }
    out.push(state.linear_erp.to_bits());
    for s in state.springs {
        out.extend([
            s.enabled as u32,
            s.equilibrium.to_bits(),
            s.stiffness.to_bits(),
            s.damping.to_bits(),
        ]);
    }
}

#[test]
fn every_joint_row_and_state_word_matches_native() {
    let mut cases = 0;
    let mut previous_state = None;
    let mut row_counts = [0; 7];
    let mut axes_seen = [false; 6];
    let mut wrap_seen = false;
    let mut stale_error_seen = false;
    let mut spring_update_seen = false;
    let mut zero_rows_preserve_spring_seen = false;
    for line in include_str!("../joint_data/native.tsv").lines() {
        let mut fields = line.split('\t');
        let id: usize = fields.next().unwrap().parse().unwrap();
        let input: Vec<_> = fields
            .map(|v| u32::from_str_radix(v, 16).unwrap())
            .collect();
        let mut words = Words(input.iter());
        let coordinates = JointCoordinates {
            basis_a_world: Basis(std::array::from_fn(|_| words.vector().0)),
            pivot_b_world: words.vector(),
            linear_diff: words.vector(),
            angular_diff: words.vector(),
            angular_axes: std::array::from_fn(|_| words.vector()),
        };
        let bodies = std::array::from_fn(|_| JointBodySnapshot {
            origin: words.vector(),
            linear_velocity: words.vector(),
            angular_velocity: words.vector(),
        });
        let step = JointStep {
            fps: words.scalar(),
            erp: words.scalar(),
            iterations: words.word(),
        };
        let fixture_prior = words.state();
        let mut state = if id % 6 == 0 {
            fixture_prior
        } else {
            previous_state.unwrap()
        };
        let mut prior_words = Vec::new();
        let mut fixture_prior_words = Vec::new();
        state_words(state, &mut prior_words);
        state_words(fixture_prior, &mut fixture_prior_words);
        assert_eq!(prior_words, fixture_prior_words, "case {id} sequence state");
        let prior = state;
        let expected: Vec<_> = words.0.copied().collect();
        let rows = generate_rows(coordinates, bodies, step, &mut state);
        let mut actual = vec![rows.as_slice().len() as u32];
        row_counts[rows.as_slice().len()] += 1;
        for row in rows.as_slice() {
            let axis = row.axis as usize;
            axes_seen[axis] = true;
            actual.push(axis as u32);
            for v in [row.j1_linear, row.j1_angular, row.j2_angular] {
                actual.extend(v.0.map(f32::to_bits));
            }
            actual.extend(
                [
                    row.positional_rhs,
                    row.cfm,
                    row.lower_impulse,
                    row.upper_impulse,
                ]
                .map(f32::to_bits),
            );
        }
        state_words(state, &mut actual);
        assert_eq!(actual.len(), expected.len(), "case {id} word count");
        for (index, (&a, &b)) in actual.iter().zip(&expected).enumerate() {
            assert_eq!(
                a, b,
                "case {id}, output word {index}, actual {a:08x}, native {b:08x}"
            );
        }
        for i in 0..3 {
            wrap_seen |= (state.angular[i].motor.current_position - coordinates.angular_diff.0[i])
                .abs()
                > 6.0;
            stale_error_seen |= state.angular[i].motor.current_limit == 0
                && state.angular[i].motor.current_limit_error != 0.0;
        }
        for i in 0..6 {
            let (before, after) = if i < 3 {
                (prior.linear[i], state.linear[i])
            } else {
                (prior.angular[i - 3].motor, state.angular[i - 3].motor)
            };
            if state.springs[i].enabled {
                spring_update_seen |=
                    before.target_velocity.to_bits() != after.target_velocity.to_bits();
                zero_rows_preserve_spring_seen |= rows.as_slice().is_empty()
                    && before.target_velocity.to_bits() == after.target_velocity.to_bits();
            }
        }
        previous_state = Some(state);
        cases += 1;
    }
    assert_eq!(cases, 378);
    assert!(row_counts.into_iter().all(|count| count > 0));
    assert!(axes_seen.into_iter().all(|seen| seen));
    assert!(wrap_seen && stale_error_seen && spring_update_seen && zero_rows_preserve_spring_seen);
}
