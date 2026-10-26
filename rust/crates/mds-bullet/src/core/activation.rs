//! Altered Rust translation of Bullet activation; see mod.rs for the zlib notice.
use super::math::Vec3;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(i32)]
pub enum ActivationState {
    /// The unnamed state assigned by updateDeactivation when a body moves.
    Moving = 0,
    Active = 1,
    IslandSleeping = 2,
    WantsDeactivation = 3,
    DisableDeactivation = 4,
    DisableSimulation = 5,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CollisionClassification {
    Dynamic,
    Static,
    Kinematic,
    StaticAndKinematic,
}

/// The native gDeactivationTime and gDisableDeactivation values.
#[derive(Clone, Copy, Debug)]
pub struct DeactivationSettings {
    pub time: f32,
    pub disabled: bool,
}

impl Default for DeactivationSettings {
    fn default() -> Self {
        Self {
            time: 2.0,
            disabled: false,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct BodyActivation {
    pub state: ActivationState,
    pub deactivation_time: f32,
    pub linear_sleeping_threshold: f32,
    pub angular_sleeping_threshold: f32,
}

impl Default for BodyActivation {
    fn default() -> Self {
        Self {
            state: ActivationState::Active,
            deactivation_time: 0.0,
            linear_sleeping_threshold: 0.8,
            angular_sleeping_threshold: 1.0,
        }
    }
}

impl BodyActivation {
    pub fn set_activation_state(&mut self, state: ActivationState) {
        if !matches!(
            self.state,
            ActivationState::DisableDeactivation | ActivationState::DisableSimulation
        ) {
            self.state = state;
        }
    }

    pub fn force_activation_state(&mut self, state: ActivationState) {
        self.state = state;
    }

    pub fn activate(&mut self, force: bool, classification: CollisionClassification) {
        if force || classification == CollisionClassification::Dynamic {
            self.set_activation_state(ActivationState::Active);
            self.deactivation_time = 0.0;
        }
    }

    pub fn is_active(&self) -> bool {
        !matches!(
            self.state,
            ActivationState::IslandSleeping | ActivationState::DisableSimulation
        )
    }

    pub fn update_deactivation(&mut self, time_step: f32, linear: Vec3, angular: Vec3) {
        if matches!(
            self.state,
            ActivationState::IslandSleeping | ActivationState::DisableDeactivation
        ) {
            return;
        }
        if linear.length2() < self.linear_sleeping_threshold * self.linear_sleeping_threshold
            && angular.length2() < self.angular_sleeping_threshold * self.angular_sleeping_threshold
        {
            self.deactivation_time += time_step;
        } else {
            self.deactivation_time = 0.0;
            self.set_activation_state(ActivationState::Moving);
        }
    }

    pub fn wants_sleeping(&self, settings: DeactivationSettings) -> bool {
        if self.state == ActivationState::DisableDeactivation
            || settings.disabled
            || settings.time == 0.0
        {
            return false;
        }
        matches!(
            self.state,
            ActivationState::IslandSleeping | ActivationState::WantsDeactivation
        ) || self.deactivation_time > settings.time
    }

    /// One entry of btDiscreteDynamicsWorld::m_nonStaticRigidBodies, in native order.
    /// Registration and array iteration belong to the world, not this body kernel.
    pub fn update_activation_state(
        &mut self,
        time_step: f32,
        classification: CollisionClassification,
        linear: &mut Vec3,
        angular: &mut Vec3,
        settings: DeactivationSettings,
    ) {
        self.update_deactivation(time_step, *linear, *angular);
        if self.wants_sleeping(settings) {
            if classification != CollisionClassification::Dynamic {
                self.set_activation_state(ActivationState::IslandSleeping);
            } else {
                if self.state == ActivationState::Active {
                    self.set_activation_state(ActivationState::WantsDeactivation);
                }
                if self.state == ActivationState::IslandSleeping {
                    *angular = Vec3::ZERO;
                    *linear = Vec3::ZERO;
                }
            }
        } else if self.state != ActivationState::DisableDeactivation {
            self.set_activation_state(ActivationState::Active);
        }
    }
}
