//! Port of the per-frame physics of the C++ x64 app, as the L2 trace mode
//! (`src/tools/trace_mode.cpp`) runs it: the Bullet 2.75 world of
//! `SceneConstruct`, the bodies and joints of the model loaders, and per
//! frame `PlaybackCatchup` (the 1/60 s catch-up substeps) and `PhysicsFrame`
//! (wind or gravity, the pose passes, the kinematic sync, the main step, the
//! settle and the readback into the bones).
//!
//! [`PhysicsScene::new`] is the PMM load (bodies, joints, the load-time
//! kinematic sync), the one `PhysicsFrame` that the window paints after the
//! load (settle requested, no time passed) and `ArmFrameStep`: trace
//! frame 0. [`PhysicsScene::step`] is one frame-step pass at 30 fps.
//!
//! Sources: `src/physics/physics_frame.cpp`, `src/app/playback_catchup.cpp`,
//! `src/physics/physics_create.cpp`, `src/io/pmm_load_v2.cpp`.

use mds_bullet_sys as sys;
use mds_formats::pmm::Pmm;
use mds_math::{Mat4, Quat, Vec3};
use mds_pose::model::{flag, kind, Model, Rigid};
use mds_pose::Scene;
use std::fmt::Write as _;
use std::ptr;

const SUBSTEP: f32 = 1.0 / 60.0;
/// `AviRecordFps` of the trace mode.
const FPS: f32 = 30.0;

fn check(code: i32, what: &str) -> Result<(), String> {
    if code == sys::MDS_BT_OK {
        Ok(())
    } else {
        Err(format!("{what}: Bullet error {code}"))
    }
}

/// The Bullet world with its ground plane. It owns the bodies and joints.
struct World(*mut sys::mds_mmd_world);

impl Drop for World {
    fn drop(&mut self) {
        // SAFETY: the pointer came from mds_mmd_world_create and is freed once.
        unsafe { sys::mds_mmd_world_destroy(self.0) }
    }
}

/// MSVC `rand()` with the CRT's default seed 1 (the app never calls `srand`).
struct MsvcRand(u32);

impl MsvcRand {
    fn next(&mut self) -> i32 {
        self.0 = self.0.wrapping_mul(214_013).wrapping_add(2_531_011);
        ((self.0 >> 16) & 0x7fff) as i32
    }
}

pub struct PhysicsScene {
    pub scene: Scene,
    world: World,
    /// Per model (scene order), per rigid body: the Bullet body, null for
    /// shapes the loaders do not build.
    bodies: Vec<Vec<*mut sys::mds_mmd_body>>,
    /// `PhysicsResetPending`: the next `PhysicsFrame` settles.
    settle: bool,
    /// `physicsBodiesMoved`: never set by the trace.
    moved: bool,
    /// `PlaybackActive`.
    playing: bool,
    /// `DeltaTime`.
    delta_time: f32,
    /// `g_CatchupDtBudget`: what the main step of `PhysicsFrame` steps.
    budget: f32,
    gravity_magnitude: f32,
    gravity_noise: i32,
    gravity_direction: [f32; 3],
    gravity_noise_enabled: bool,
    gravity_noise_timer: f32,
    rand: MsvcRand,
}

impl PhysicsScene {
    /// Loads the PMM's models through `read` and sets up trace frame 0.
    pub fn new(
        pmm: &Pmm,
        read: impl FnMut(&str) -> Result<Vec<u8>, String>,
    ) -> Result<PhysicsScene, String> {
        let scene = Scene::load(pmm, read)?;
        // SAFETY: no arguments; null on failure.
        let world = World(unsafe { sys::mds_mmd_world_create() });
        if world.0.is_null() {
            return Err("Bullet world creation failed".into());
        }
        let p = &pmm.physics;
        let mut this = PhysicsScene {
            bodies: vec![Vec::new(); scene.models.len()],
            scene,
            world,
            settle: false,
            moved: false,
            playing: false,
            delta_time: 0.0,
            budget: 0.0,
            gravity_magnitude: p.gravity_magnitude,
            gravity_noise: p.gravity_noise,
            gravity_direction: p.gravity_direction,
            gravity_noise_enabled: p.gravity_noise_enabled == 1,
            gravity_noise_timer: 0.0,
            rand: MsvcRand(1),
        };
        // The loaders build bodies and joints model by model in PMM order.
        let mut uid = 0;
        for source in &pmm.models {
            let m = this
                .scene
                .models
                .iter()
                .position(|m| m.slot == source.slot)
                .ok_or("model slot lost")?;
            this.bodies[m] = this.create_bodies(m, &mut uid)?;
        }
        // The load's success tail (pmm_load_v2.cpp, pmm_load_v1.cpp) hands the
        // PMM gravity to the world: no zero-direction nudge here, and the D3DX
        // normalization rounds (0, -1, 0) to a y of 0x3F7FFFFF.
        let n = Vec3(this.gravity_direction).normalize().0;
        let mag = this.gravity_magnitude;
        this.set_gravity(n.map(|n| (n * mag) * 10.0))?;
        // RestoreScenePhysics.
        for m in 0..this.bodies.len() {
            this.kinematic_sync(m)?;
        }
        // The PMM load tail requests a settle; the first paint after it runs
        // PhysicsFrame with no time passed and playback stopped.
        this.settle = true;
        this.physics_frame()?;
        // ArmFrameStep (UpdateBoneFrames clears the frame-changed flag
        // instead of requesting another settle).
        this.playing = true;
        this.delta_time = 1.0 / FPS;
        this.scene.arm_frame_step();
        Ok(this)
    }

    /// `CreateRigidBody` per rigid body, then `CreatePhysJoint` per joint.
    fn create_bodies(
        &self,
        m: usize,
        uid: &mut i32,
    ) -> Result<Vec<*mut sys::mds_mmd_body>, String> {
        let model = &self.scene.models[m];
        let mut bodies = Vec::with_capacity(model.rigids.len());
        for r in &model.rigids {
            let mut body = ptr::null_mut();
            if r.shape <= 2 {
                // SAFETY: the world is live; the arrays outlive the call.
                check(
                    unsafe {
                        sys::mds_mmd_body_create(
                            self.world.0,
                            i32::from(r.shape),
                            r.size[0],
                            r.size[1],
                            r.size[2],
                            r.start_origin.as_ptr(),
                            r.start_rotation.as_ptr(),
                            i32::from(r.mode),
                            r.mass,
                            r.linear_damping,
                            r.angular_damping,
                            r.restitution,
                            r.friction,
                            (1u16 << (r.group & 15)) as i16,
                            r.mask as i16,
                            &mut body,
                        )
                    },
                    "rigid body",
                )?;
            }
            bodies.push(body);
        }
        for j in &model.joints {
            let (a, b) = (bodies[j.rigid_a], bodies[j.rigid_b]);
            if a.is_null() || b.is_null() {
                continue;
            }
            // SAFETY: as above; both bodies belong to this world.
            check(
                unsafe {
                    sys::mds_mmd_joint_create(
                        self.world.0,
                        a,
                        b,
                        j.frame_a.0.as_ptr(),
                        j.frame_a.1.as_ptr(),
                        j.frame_b.0.as_ptr(),
                        j.frame_b.1.as_ptr(),
                        j.linear_lower.as_ptr(),
                        j.linear_upper.as_ptr(),
                        j.angular_lower.as_ptr(),
                        j.angular_upper.as_ptr(),
                        j.springs.as_ptr(),
                        *uid,
                    )
                },
                "joint",
            )?;
            *uid += 1;
        }
        Ok(bodies)
    }

    /// Hands the `CF_KINEMATIC_OBJECT` flags that `NotifyBonePhysicsMode`
    /// set since the last world call to Bullet. The C++ sets them at once;
    /// Bullet reads them only in `setGravity` and `stepSimulation`.
    fn push_kinematic_flags(&self) -> Result<(), String> {
        for (model, bodies) in self.scene.models.iter().zip(&self.bodies) {
            for (r, &body) in model.rigids.iter().zip(bodies) {
                if !body.is_null() {
                    // SAFETY: a live body of this world.
                    check(
                        unsafe { sys::mds_mmd_body_set_kinematic(body, i32::from(r.kinematic)) },
                        "kinematic flag",
                    )?;
                }
            }
        }
        Ok(())
    }

    fn set_gravity(&self, g: [f32; 3]) -> Result<(), String> {
        self.push_kinematic_flags()?;
        // SAFETY: the world is live.
        check(
            unsafe { sys::mds_mmd_world_set_gravity(self.world.0, g[0], g[1], g[2]) },
            "gravity",
        )
    }

    fn world_step(&self, dt: f32) -> Result<(), String> {
        self.push_kinematic_flags()?;
        // SAFETY: the world is live.
        check(
            unsafe { sys::mds_mmd_world_step(self.world.0, dt, 10, SUBSTEP) },
            "step",
        )
    }

    /// `ModelKinematicSync`: bone followers get the bone pose in their
    /// motion state.
    fn kinematic_sync(&self, m: usize) -> Result<(), String> {
        let model = &self.scene.models[m];
        for (r, &body) in model.rigids.iter().zip(&self.bodies[m]) {
            if r.mode != 0 || body.is_null() {
                continue;
            }
            let mat = follow_matrix(model, r, r.bone);
            // SAFETY: a live body; 16 floats.
            check(
                unsafe { sys::mds_mmd_body_set_motion_state(body, mat.0.as_ptr()) },
                "kinematic sync",
            )?;
        }
        Ok(())
    }

    /// `ModelDynamicReseat`: physics bodies jump to the bone pose and stop.
    fn dynamic_reseat(&self, m: usize) -> Result<(), String> {
        let model = &self.scene.models[m];
        for (r, &body) in model.rigids.iter().zip(&self.bodies[m]) {
            if r.mode as i8 <= 0 || body.is_null() {
                continue;
            }
            let bone = if r.bone < 0 {
                model.center_bone as i32
            } else {
                r.bone
            };
            let mat = follow_matrix(model, r, bone);
            // SAFETY: a live body; 16 floats.
            check(
                unsafe { sys::mds_mmd_body_reseat(body, mat.0.as_ptr()) },
                "reseat",
            )?;
        }
        Ok(())
    }

    /// One frame-step pass at 30 fps: `PlaybackCatchup` then `PhysicsFrame`.
    pub fn step(&mut self) -> Result<(), String> {
        let count = self.scene.physics_mode;
        self.budget = 1.0 / FPS;
        let target = self.scene.next_target();
        if count >= 1 {
            self.scene.cursor += SUBSTEP;
            while self.scene.cursor < target {
                self.scene.advance_keys();
                self.scene.ordered_pass(0, count);
                for m in 0..self.bodies.len() {
                    self.kinematic_sync(m)?;
                }
                self.world_step(SUBSTEP)?;
                self.budget -= SUBSTEP;
                self.scene.cursor += SUBSTEP;
            }
        }
        self.scene.cursor = target;
        self.scene.advance_keys();
        self.physics_frame()
    }

    /// `PhysicsFrame` with no model selected.
    fn physics_frame(&mut self) -> Result<(), String> {
        let count = self.scene.physics_mode;
        if count > 0 {
            if self.gravity_noise_enabled {
                self.gravity_noise_timer += self.delta_time;
                if self.gravity_noise_timer > 0.5 {
                    let noise = self.gravity_noise as f32;
                    let strength = ((self.rand.next() as f32 * 10.0) / 32767.0) * noise
                        + self.gravity_magnitude;
                    let mut g = [0.0; 3];
                    for (g, d) in g.iter_mut().zip(self.gravity_direction) {
                        *g = ((self.rand.next() as f32 * 0.2) / 32767.0 - 0.1 + d) * strength;
                    }
                    self.set_gravity(g)?;
                    self.gravity_noise_timer = 0.0;
                }
            } else {
                if self.gravity_direction == [0.0; 3] {
                    self.gravity_direction[1] = 0.1;
                }
                let n = Vec3(self.gravity_direction).normalize().0;
                let mag = self.gravity_magnitude;
                self.set_gravity(n.map(|n| (n * mag) * 10.0))?;
            }
        }
        let pose_mode = if self.settle { 0 } else { count };
        self.scene.ordered_pass(0, pose_mode);
        let run =
            count == 1 || count == 2 || (count == 3 && (self.moved || self.settle || self.playing));
        if run {
            for m in 0..self.bodies.len() {
                self.kinematic_sync(m)?;
            }
            let extra = self.moved && count == 3;
            self.world_step(if extra { SUBSTEP } else { self.budget })?;
            if extra {
                self.world_step(SUBSTEP)?;
            }
            if self.settle {
                for _ in 0..3 {
                    for m in 0..self.bodies.len() {
                        self.dynamic_reseat(m)?;
                    }
                    self.world_step(SUBSTEP)?;
                }
                self.settle = false;
            }
            for m in 0..self.bodies.len() {
                readback(&mut self.scene.models[m], &self.bodies[m])?;
            }
            self.moved = false;
        }
        self.scene.ordered_pass(1, count);
        Ok(())
    }

    /// Appends the lines of `frame`: per model the pose lines, then a
    /// `rigid` line per body (world origin and rotation).
    pub fn write_frame(&self, out: &mut String, frame: u32) -> Result<(), String> {
        for (model, bodies) in self.scene.models.iter().zip(&self.bodies) {
            mds_pose::trace::write_model(out, frame, model)?;
            for (i, &body) in bodies.iter().enumerate() {
                if body.is_null() {
                    return Err(format!("model {} rigid body {i} has no body", model.slot));
                }
                let (mut origin, mut rotation) = ([0.0f32; 3], [0.0f32; 4]);
                // SAFETY: a live body; 3 and 4 floats.
                check(
                    unsafe {
                        sys::mds_mmd_body_pose(body, origin.as_mut_ptr(), rotation.as_mut_ptr())
                    },
                    "body pose",
                )?;
                write!(out, "{frame} rigid {} {i}", model.slot).unwrap();
                mds_pose::trace::floats(out, &origin)?;
                mds_pose::trace::floats(out, &rotation)?;
                out.push('\n');
            }
        }
        Ok(())
    }

    /// The header and frames `0..frames`, stepping the scene.
    pub fn trace(&mut self, frames: u32) -> Result<String, String> {
        let mut out = String::from(mds_pose::trace::HEADER);
        for frame in 0..frames {
            if frame > 0 {
                self.step().map_err(|e| format!("frame {frame}: {e}"))?;
            }
            self.write_frame(&mut out, frame)
                .map_err(|e| format!("frame {frame}: {e}"))?;
        }
        Ok(out)
    }
}

/// `BuildFollowMatrix`: `Rz * Rx * Ry * T(rigid)`, then
/// `* T(bone position) * bone world` for a bone index `>= 0`.
fn follow_matrix(model: &Model, r: &Rigid, bone: i32) -> Mat4 {
    let mut o = Mat4::multiply(
        &Mat4::rotation_z(r.rotation[2]),
        &Mat4::rotation_x(r.rotation[0]),
    );
    o = Mat4::multiply(&o, &Mat4::rotation_y(r.rotation[1]));
    let [x, y, z] = r.position;
    o = Mat4::multiply(&o, &Mat4::translation(x, y, z));
    if let Ok(b) = usize::try_from(bone) {
        let bn = &model.bones[b];
        let [x, y, z] = bn.position;
        o = Mat4::multiply(&o, &Mat4::translation(x, y, z));
        o = Mat4::multiply(&o, &bn.mat_init);
    }
    o
}

fn body_matrix(body: *mut sys::mds_mmd_body) -> Result<Mat4, String> {
    let mut m = Mat4([0.0; 16]);
    // SAFETY: a live body; 16 floats.
    check(
        unsafe { sys::mds_mmd_body_matrix(body, m.0.as_mut_ptr()) },
        "body matrix",
    )?;
    Ok(m)
}

/// `ModelPhysicsReadback`: over-stretched joints, then the physics bodies
/// drive their bones' world matrices and physics poses.
fn readback(model: &mut Model, bodies: &[*mut sys::mds_mmd_body]) -> Result<(), String> {
    for j in &model.joints {
        let (a, b) = (bodies[j.rigid_a], bodies[j.rigid_b]);
        if a.is_null() || b.is_null() {
            continue;
        }
        let ma = body_matrix(a)?;
        let mb = body_matrix(b)?;
        let (ma, mb) = (ma.0, mb.0);
        let dy = ma[13] - mb[13];
        let dx = ma[12] - mb[12];
        let dz = ma[14] - mb[14];
        let dist = ((dy * dy + dx * dx) + dz * dz).sqrt();
        let limit = j.radius_bound;
        if dist - limit < 2.0 {
            continue;
        }
        let k = limit / dist;
        let t = Mat4::translation(
            (mb[12] - ma[12]) * k,
            (mb[13] - ma[13]) * k,
            (mb[14] - ma[14]) * k,
        );
        let moved = Mat4::multiply(&Mat4(ma), &t).0;
        // SAFETY: a live body; 3 floats.
        check(
            unsafe { sys::mds_mmd_body_stop_at(b, moved[12..15].as_ptr()) },
            "over-stretch stop",
        )?;
    }

    for (r, &body) in model.rigids.iter().zip(bodies) {
        let Ok(bi) = usize::try_from(r.bone) else {
            continue;
        };
        if r.mode as i8 <= 0 || body.is_null() {
            continue;
        }
        let w = body_matrix(body)?;
        model.bones[bi].mat_init = Mat4::multiply(&r.inv_transform, &w);
    }

    let bones = &mut model.bones;
    for r in &model.rigids {
        let Ok(bi) = usize::try_from(r.bone) else {
            continue;
        };
        if r.mode as i8 <= 0 {
            continue;
        }
        let parent = bones[bi].parent;
        let world = bones[bi].mat_init;
        let local = match usize::try_from(parent) {
            Err(_) => Some(world),
            Ok(p) => bones[p]
                .mat_init
                .inverse()
                .map(|(inv, _)| Mat4::multiply(&world, &inv)),
        };
        let Some(mut local) = local else {
            bones[bi].mat_extra = bones[bi].mat_init;
            continue;
        };
        bones[bi].mat_local = local;
        let mut q = Quat::from_matrix(&local);
        let [px, py, pz] = bones[bi].position;
        let mut work = Mat4::multiply(&Mat4::translation(px, py, pz), &local);
        let pos = Mat4::multiply(&work, &Mat4::translation(-px, -py, -pz));
        let mut backup_pos = [pos.0[12], pos.0[13], pos.0[14]];

        // The tail bone may be the bone itself, whose local matrix is the
        // new one by now.
        let tail = usize::try_from(bones[bi].tail_idx).unwrap_or(bi);
        let (t_quat, t_local, t_offset) = (
            bones[tail].physics_quat,
            bones[tail].mat_local,
            bones[tail].physics_offset,
        );
        let bone = &mut bones[bi];
        if bone.kind == kind::ROTATE_GRANT {
            let conj = Quat([-t_quat[0], -t_quat[1], -t_quat[2], t_quat[3]]);
            q = Quat::multiply(conj, q);
        }
        if bone.flags & flag::ROT_INHERIT != 0 {
            let mut l = Quat::from_matrix(&t_local).0;
            l[3] = l[3].clamp(-1.0, 1.0);
            let mut angle = mds_crtmath::acosf(l[3]);
            if l[3] < 0.0 {
                angle -= f32::from_bits(0x4048_F5C3);
            }
            let axis_len = ((l[1] * l[1] + l[0] * l[0]) + l[2] * l[2]).sqrt();
            if angle != 0.0 && axis_len >= 1.192_092_9e-7 {
                let a = angle * bone.inherit_ratio;
                let s = mds_crtmath::sinf(a) / axis_len;
                let rot = Quat([-l[0] * s, -l[1] * s, -l[2] * s, mds_crtmath::cosf(a)]);
                q = if parent >= 0 {
                    Quat::multiply(rot, q)
                } else {
                    Quat::multiply(q, rot)
                };
            }
        }
        if bone.flags & flag::TRANS_INHERIT != 0 {
            for (o, t) in bone.physics_offset.iter_mut().zip(t_offset) {
                *o -= t * bone.inherit_ratio;
            }
        }
        let mut world = world;
        if r.mode == 2 {
            bone.trans = [0.0; 3];
            backup_pos = [0.0; 3];
            work.0[12..15].fill(0.0);
            local = Mat4::multiply(&Mat4::translation(-px, -py, -pz), &work);
            local = Mat4::multiply(&local, &Mat4::translation(px, py, pz));
        }
        bone.ik_backup[..3].copy_from_slice(&backup_pos);
        bone.ik_backup[3..].copy_from_slice(&q.0);
        bone.mat_local = local;
        if r.mode == 2 {
            if let Ok(p) = usize::try_from(parent) {
                world = Mat4::multiply(&local, &bones[p].mat_init);
            }
        }
        let bone = &mut bones[bi];
        bone.mat_init = world;
        bone.mat_extra = world;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::MsvcRand;

    #[test]
    fn rand_is_the_msvc_sequence() {
        let mut r = MsvcRand(1);
        let first: Vec<i32> = (0..4).map(|_| r.next()).collect();
        assert_eq!(first, [41, 18467, 6334, 26500]);
    }
}
