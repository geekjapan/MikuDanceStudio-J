use super::core::{
    activation::{ActivationState, BodyActivation, CollisionClassification, DeactivationSettings},
    math::Vec3,
};

fn state(value: &str) -> ActivationState {
    match value {
        "0" => ActivationState::Moving,
        "1" => ActivationState::Active,
        "2" => ActivationState::IslandSleeping,
        "3" => ActivationState::WantsDeactivation,
        "4" => ActivationState::DisableDeactivation,
        "5" => ActivationState::DisableSimulation,
        _ => panic!("invalid native activation state"),
    }
}
fn float(value: &str) -> f32 {
    f32::from_bits(u32::from_str_radix(value, 16).unwrap())
}
fn classification(flags: i32) -> CollisionClassification {
    match flags & 3 {
        0 => CollisionClassification::Dynamic,
        1 => CollisionClassification::Static,
        2 => CollisionClassification::Kinematic,
        3 => CollisionClassification::StaticAndKinematic,
        _ => unreachable!(),
    }
}

#[test]
fn activation_traces_match_every_native_state_and_word() {
    use std::fmt::Write;
    let full_inputs = std::env::var("MDS_ACTIVATION_INPUTS")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    let full_native = std::env::var("MDS_ACTIVATION_NATIVE")
        .ok()
        .map(|p| std::fs::read_to_string(p).unwrap());
    let inputs = full_inputs
        .as_deref()
        .unwrap_or(include_str!("../activation_data/inputs.tsv"));
    let native = full_native
        .as_deref()
        .unwrap_or(include_str!("../activation_data/native.tsv"));
    assert!(!inputs.is_empty());
    assert_eq!(inputs.lines().count(), native.lines().count());
    let mut body = BodyActivation::default();
    let mut settings = DeactivationSettings::default();
    let mut flags = 0;
    let mut linear = Vec3::ZERO;
    let mut angular = Vec3::ZERO;
    for (input, expected) in inputs.lines().zip(native.lines()) {
        let p: Vec<_> = input.split_whitespace().collect();
        match p[1] {
            "reset" => {
                body = BodyActivation::default();
                settings = DeactivationSettings::default();
                flags = 0;
                linear = Vec3::ZERO;
                angular = Vec3::ZERO;
            }
            "force" => body.force_activation_state(state(p[2])),
            "set" => body.set_activation_state(state(p[2])),
            "time" => body.deactivation_time = float(p[2]),
            "thresholds" => {
                body.linear_sleeping_threshold = float(p[2]);
                body.angular_sleeping_threshold = float(p[3]);
            }
            "flags" => flags = p[2].parse().unwrap(),
            "velocities" => {
                linear = Vec3(std::array::from_fn(|i| float(p[2 + i])));
                angular = Vec3(std::array::from_fn(|i| float(p[5 + i])));
            }
            "settings" => {
                settings = DeactivationSettings {
                    time: float(p[2]),
                    disabled: p[3] == "1",
                }
            }
            "activate" => body.activate(p[2] == "1", classification(flags)),
            "update" => body.update_deactivation(float(p[2]), linear, angular),
            "world" => body.update_activation_state(
                float(p[2]),
                classification(flags),
                &mut linear,
                &mut angular,
                settings,
            ),
            "query" => (),
            _ => panic!("unknown activation operation"),
        }
        let mut actual = format!(
            "{}\t{}\t{}\t{}\t{}",
            p[0],
            body.state as i32,
            u8::from(body.is_active()),
            u8::from(body.wants_sleeping(settings)),
            flags
        );
        for value in [
            body.deactivation_time,
            body.linear_sleeping_threshold,
            body.angular_sleeping_threshold,
        ]
        .into_iter()
        .chain(linear.0)
        .chain(angular.0)
        .chain([settings.time])
        {
            write!(actual, "\t{:08x}", value.to_bits()).unwrap();
        }
        write!(actual, "\t{}", u8::from(settings.disabled)).unwrap();
        assert_eq!(actual, expected, "operation {input}");
    }
}
