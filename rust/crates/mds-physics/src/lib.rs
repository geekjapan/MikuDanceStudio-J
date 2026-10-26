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
//! The interactive application keeps one world alive instead:
//! [`PhysicsScene::open`] is the load alone ([`PhysicsScene::open_running`]
//! after the app has pumped), and each pump of the window
//! (`FrameDriver`, `src/app/frame_driver.cpp`) is one [`PhysicsScene::tick`]
//! while stopped or one [`PhysicsScene::catch_up`] while playing. Seeks,
//! frame steps, play, stop, loop and the physics reset only change the
//! state the next pump reads: the key pose, the settle request
//! (`PhysicsResetPending`) and the playback cursor.
//!
//! Sources: `src/physics/physics_frame.cpp`, `src/app/playback_catchup.cpp`,
//! `src/physics/physics_create.cpp`, `src/io/pmm_load_v2.cpp`,
//! `src/app/playback_state.cpp`, `src/window/ui_frame_step.cpp`,
//! `src/window/ui_editor_click.cpp`, `src/window/command_frame_edit.cpp`,
//! `src/window/command_view_menu.cpp`.

use mds_bullet_sys as sys;
use mds_formats::pmm::Pmm;
use mds_math::{Mat4, Quat, Vec3};
use mds_pose::keys;
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

/// A world or pose operation, recorded by the unit tests.
#[cfg_attr(not(test), allow(dead_code))]
#[derive(Clone, Copy, Debug, PartialEq)]
enum Op {
    Gravity,
    /// The key application at the cursor (`AdvanceModelKeyframes`).
    Keys,
    /// `OrderedMorphPhysicsPass` or a pose pass of `PhysicsFrame`: after
    /// physics, physics mode.
    Pose(u8, i32),
    /// `ModelKinematicSync` of every model.
    Sync,
    Step(f32),
    /// `ModelDynamicReseat` of every model.
    Reseat,
    /// `ModelPhysicsReadback` of every model.
    Readback,
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
    /// `SavedPlaybackPhysicsMode`: the mode that stop and loop restore.
    saved_mode: i32,
    /// `playbackAlwaysOnOffMode`, the menu toggle
    /// `MDS_CMD_TOGGLE_PLAYBACK_PHYSICS_ON_OFF` (`command_view_menu.cpp`):
    /// playback runs in physics mode 2.
    pub always_on_off: bool,
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
    #[cfg(test)]
    log: std::cell::RefCell<Vec<Op>>,
}

impl PhysicsScene {
    /// Loads the PMM's models through `read` and sets up trace frame 0.
    pub fn new(
        pmm: &Pmm,
        read: impl FnMut(&str) -> Result<Vec<u8>, String>,
    ) -> Result<PhysicsScene, String> {
        let mut this = PhysicsScene::open(pmm, read)?;
        // The first paint after the load runs PhysicsFrame with no time
        // passed and playback stopped.
        this.tick(0.0)?;
        // ArmFrameStep (UpdateBoneFrames clears the frame-changed flag
        // instead of requesting another settle).
        this.playing = true;
        this.delta_time = 1.0 / FPS;
        this.scene.arm_frame_step();
        Ok(this)
    }

    /// The PMM load of the application, stopped, with a settle requested
    /// (`pmm_load_v2.cpp`, 0x458F43). The first [`tick`](Self::tick) is the
    /// paint after the load (`wm_paint.cpp`, `FrameDriver`).
    pub fn open(
        pmm: &Pmm,
        read: impl FnMut(&str) -> Result<Vec<u8>, String>,
    ) -> Result<PhysicsScene, String> {
        PhysicsScene::load(pmm, read, false)
    }

    /// [`open`](Self::open) in an application that has pumped since
    /// `SceneConstruct` built its world: the File menu or a drop. The C++
    /// world outlives the loads, and `btDiscreteDynamicsWorld` starts its
    /// substep clock at 1/60 s, which the first `PhysicsFrame` on the empty
    /// world spends (the startup paint, `window_init.cpp` `UpdateWindow`).
    /// Pumps of whole 1/60 s steps, as the script runner's settle frames,
    /// keep the clock at 0; the remainder that wall-clock pumps leave is not
    /// carried into this new world. A PMM named on the command line loads
    /// before that paint, as [`open`](Self::open) does.
    pub fn open_running(
        pmm: &Pmm,
        read: impl FnMut(&str) -> Result<Vec<u8>, String>,
    ) -> Result<PhysicsScene, String> {
        PhysicsScene::load(pmm, read, true)
    }

    fn load(
        pmm: &Pmm,
        read: impl FnMut(&str) -> Result<Vec<u8>, String>,
        pumped: bool,
    ) -> Result<PhysicsScene, String> {
        let scene = Scene::load(pmm, read)?;
        // SAFETY: no arguments; null on failure.
        let world = World(unsafe { sys::mds_mmd_world_create() });
        if world.0.is_null() {
            return Err("Bullet world creation failed".into());
        }
        if pumped {
            // SAFETY: the world is live; only the ground is in it.
            check(
                unsafe { sys::mds_mmd_world_step(world.0, 0.0, 10, SUBSTEP) },
                "startup step",
            )?;
        }
        let p = &pmm.physics;
        let mut this = PhysicsScene {
            bodies: vec![Vec::new(); scene.models.len()],
            saved_mode: scene.physics_mode,
            always_on_off: false,
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
            #[cfg(test)]
            log: Default::default(),
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
        this.sync_all()?;
        this.settle = true;
        #[cfg(test)]
        this.log.borrow_mut().clear();
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

    fn note(&self, _op: Op) {
        #[cfg(test)]
        self.log.borrow_mut().push(_op);
    }

    fn set_gravity(&self, g: [f32; 3]) -> Result<(), String> {
        self.note(Op::Gravity);
        self.push_kinematic_flags()?;
        // SAFETY: the world is live.
        check(
            unsafe { sys::mds_mmd_world_set_gravity(self.world.0, g[0], g[1], g[2]) },
            "gravity",
        )
    }

    fn world_step(&self, dt: f32) -> Result<(), String> {
        self.note(Op::Step(dt));
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

    fn sync_all(&self) -> Result<(), String> {
        self.note(Op::Sync);
        (0..self.bodies.len()).try_for_each(|m| self.kinematic_sync(m))
    }

    fn reseat_all(&self) -> Result<(), String> {
        self.note(Op::Reseat);
        (0..self.bodies.len()).try_for_each(|m| self.dynamic_reseat(m))
    }

    fn readback_all(&mut self) -> Result<(), String> {
        self.note(Op::Readback);
        for (model, bodies) in self.scene.models.iter_mut().zip(&self.bodies) {
            readback(model, bodies)?;
        }
        Ok(())
    }

    fn pose(&mut self, after: u8, physics_mode: i32) {
        self.note(Op::Pose(after, physics_mode));
        self.scene.ordered_pass(after, physics_mode);
    }

    fn advance_keys(&mut self) {
        self.note(Op::Keys);
        self.scene.advance_keys();
    }

    /// `SeekModelFrame` of every model at `frame`.
    fn seek_models(&mut self, frame: u32) {
        let mode = self.scene.physics_mode;
        for model in &mut self.scene.models {
            keys::seek_model_frame(model, frame, mode);
        }
    }

    /// `UpdateBoneFrames` (`playback_state.cpp`): the track cursors at the
    /// playback cursor, and a settle unless the frame did not change.
    fn update_bone_frames(&mut self, frame_changed: bool) {
        self.saved_mode = self.scene.physics_mode;
        if self.always_on_off {
            self.scene.physics_mode = 2;
        }
        let (cursor, mode) = (self.scene.cursor, self.scene.physics_mode);
        for model in &mut self.scene.models {
            keys::init_track_cursors(model, cursor, mode);
        }
        if !frame_changed {
            self.settle = true;
        }
    }

    /// One frame-step pass at 30 fps: `PlaybackCatchup` then `PhysicsFrame`.
    pub fn step(&mut self) -> Result<(), String> {
        self.budget = 1.0 / FPS;
        let target = self.scene.next_target();
        self.catch_up_to(target)
    }

    /// BLOCK 1 or 2 of `PlaybackCatchup` with no model skipped (the skip
    /// needs a Kinect selection): 1/60 s substeps while the cursor is behind
    /// `target`, each paid from the budget, then the keys at `target` and
    /// `PhysicsFrame`.
    fn catch_up_to(&mut self, target: f32) -> Result<(), String> {
        let count = self.scene.physics_mode;
        if count >= 1 {
            self.scene.cursor += SUBSTEP;
            while self.scene.cursor < target {
                self.advance_keys();
                self.pose(0, count);
                self.sync_all()?;
                self.world_step(SUBSTEP)?;
                self.budget -= SUBSTEP;
                self.scene.cursor += SUBSTEP;
            }
        }
        self.scene.cursor = target;
        self.advance_keys();
        self.physics_frame()
    }

    /// One pump while stopped: `PlaybackCatchup` leaves the budget at the
    /// pump's `delta_time` (`playback_catchup.cpp`, 0x46EFDE) and returns,
    /// then `PhysicsFrame`. The caller skips the pump while the message
    /// counter of `PhysicsFrame` gate A is 0.
    pub fn tick(&mut self, delta_time: f32) -> Result<(), String> {
        if self.playing {
            return Err("tick while playing".into());
        }
        self.delta_time = delta_time;
        self.budget = delta_time;
        self.physics_frame()
    }

    /// One pump while playing with `target` (start plus wall clock) not past
    /// the end: BLOCK 2 of `PlaybackCatchup` (0x46F3D6), then
    /// `PhysicsFrame`.
    pub fn catch_up(&mut self, target: f32, delta_time: f32) -> Result<(), String> {
        if !self.playing {
            return Err("catch_up while stopped".into());
        }
        self.delta_time = delta_time;
        self.budget = delta_time;
        self.catch_up_to(target)
    }

    /// One pump while playing whose target passed the end with loop on:
    /// `PlayingBeyondEnd` restarts at `start` seconds (the mode saved at play
    /// start, `UpdateBoneFrames`, the keys at the start), then `PhysicsFrame`.
    /// No substeps run in this pump.
    pub fn loop_restart(&mut self, start: f32, delta_time: f32) -> Result<(), String> {
        if !self.playing {
            return Err("loop_restart while stopped".into());
        }
        self.delta_time = delta_time;
        self.budget = delta_time;
        self.scene.physics_mode = self.saved_mode;
        self.scene.cursor = start;
        self.update_bone_frames(false);
        self.advance_keys();
        self.physics_frame()
    }

    /// The play button 408 (`ApplyPlaybackRangeEdits`): the cursor at
    /// `start` seconds, then `UpdateBoneFrames`. `frame_changed` is the
    /// C++ `PlaybackFrameChanged`: play starts at the current frame, from
    /// the current frame or from a start edit equal to it, and then no
    /// settle is requested.
    pub fn start_playback(&mut self, start: f32, frame_changed: bool) {
        self.playing = true;
        self.scene.cursor = start;
        self.update_bone_frames(frame_changed);
    }

    /// `StopPlayback` (`playback_state.cpp`), from the play button or past
    /// the end with loop off: the saved physics mode back, every model at
    /// `frame` (the current frame after the stop) and a settle. The same
    /// pump's `PhysicsFrame` is the caller's next [`tick`](Self::tick).
    pub fn stop_playback(&mut self, frame: u32) {
        self.playing = false;
        self.scene.physics_mode = self.saved_mode;
        self.seek_models(frame);
        self.settle = true;
    }

    /// A jump to `frame` while stopped: the frame strip click
    /// (`ui_editor_click.cpp`, `HandleLButtonDown_FrameStripHit`) and
    /// `RefreshAfterFrameApply` (`ui_frame_step.cpp`) seek every model and
    /// request a settle.
    pub fn seek(&mut self, frame: u32) {
        self.seek_models(frame);
        self.settle = true;
    }

    /// `StepFrame` (`ui_frame_step.cpp`, commands 418 and 419) to `frame`:
    /// every model seeks, and the settle request follows `RefreshTimeline`.
    /// Forward sets it to physics mode 3, clearing a pending settle in the
    /// other modes; back requests one in mode 3 and leaves it otherwise.
    pub fn step_frame(&mut self, frame: u32, forward: bool) {
        self.seek_models(frame);
        let mode3 = self.scene.physics_mode == 3;
        if forward {
            self.settle = mode3;
        } else if mode3 {
            self.settle = true;
        }
    }

    /// The physics menus 265, 269, 270 and 272 (`command_view_menu.cpp`
    /// 1048-1110): `PlaybackPhysicsMode`, which stop and loop also restore,
    /// then `ModelKinematicSync` of every model. The settle request of modes
    /// 1 to 3 is the document's (`physics_reset_pending`, [`reset`](Self::reset)).
    pub fn set_physics_mode(&mut self, mode: u8) -> Result<(), String> {
        self.scene.physics_mode = i32::from(mode);
        self.saved_mode = self.scene.physics_mode;
        self.sync_all()
    }

    /// The floor menu 285 (`command_view_menu.cpp` 1437-1455): the ground's
    /// collision flags become 1 (`CF_STATIC_OBJECT`, as the world starts) or
    /// -1. The `CF_NO_CONTACT_RESPONSE` bit of -1 makes
    /// `btCollisionDispatcher::needsResponse` false, so `buildIslands` hands
    /// no ground manifold to the solver and bodies fall through; the other
    /// bits change nothing for a sleeping static body. Loading a PMM does not
    /// call this: its floor byte only sets the ground's deactivation time,
    /// which Bullet reads for non-static bodies alone.
    pub fn set_floor_visible(&mut self, on: bool) -> Result<(), String> {
        // SAFETY: the world is live.
        check(
            unsafe { sys::mds_mmd_world_set_floor(self.world.0, i32::from(on)) },
            "floor",
        )
    }

    /// The physics reset menu 268 (`MDS_CMD_RESET_PHYSICS_BODIES`,
    /// `command_view_menu.cpp`): the next pump settles.
    pub fn reset(&mut self) {
        self.settle = true;
    }

    pub fn playing(&self) -> bool {
        self.playing
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
        self.pose(0, pose_mode);
        let run =
            count == 1 || count == 2 || (count == 3 && (self.moved || self.settle || self.playing));
        if run {
            self.sync_all()?;
            let extra = self.moved && count == 3;
            self.world_step(if extra { SUBSTEP } else { self.budget })?;
            if extra {
                self.world_step(SUBSTEP)?;
            }
            if self.settle {
                for _ in 0..3 {
                    self.reseat_all()?;
                    self.world_step(SUBSTEP)?;
                }
                self.settle = false;
            }
            self.readback_all()?;
            self.moved = false;
        }
        self.pose(1, count);
        Ok(())
    }

    /// The world origin and rotation (x, y, z, w) of every rigid body, per
    /// model in `scene.models` order: what the `rigid` lines of
    /// [`write_frame`](Self::write_frame) print. `None` for a shape the
    /// loaders build no body for.
    pub fn body_poses(&self) -> Result<Vec<Vec<Option<BodyPose>>>, String> {
        self.bodies
            .iter()
            .map(|bodies| {
                bodies
                    .iter()
                    .map(|&b| (!b.is_null()).then(|| body_pose(b)).transpose())
                    .collect()
            })
            .collect()
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
                let (origin, rotation) = body_pose(body)?;
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

/// A body's world origin and rotation quaternion, x y z w.
pub type BodyPose = ([f32; 3], [f32; 4]);

fn body_pose(body: *mut sys::mds_mmd_body) -> Result<BodyPose, String> {
    let (mut origin, mut rotation) = ([0.0f32; 3], [0.0f32; 4]);
    // SAFETY: a live body; 3 and 4 floats.
    check(
        unsafe { sys::mds_mmd_body_pose(body, origin.as_mut_ptr(), rotation.as_mut_ptr()) },
        "body pose",
    )?;
    Ok((origin, rotation))
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
    use super::Op::{self, *};
    use super::{ptr, sys, MsvcRand, PhysicsScene, SUBSTEP};
    use mds_formats::pmm::Pmm;
    use std::path::PathBuf;

    /// swing600.pmm in physics `mode`, gravity noise off.
    fn open(mode: u8) -> PhysicsScene {
        open_with(mode, 0)
    }

    fn open_with(mode: u8, noise: u8) -> PhysicsScene {
        let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/rust");
        let mut pmm = Pmm::read(&std::fs::read(dir.join("swing600.pmm")).unwrap()).unwrap();
        pmm.physics.playback_mode = mode;
        pmm.physics.gravity_noise_enabled = noise;
        PhysicsScene::open(&pmm, |p| {
            std::fs::read(dir.join(p)).map_err(|e| format!("{p}: {e}"))
        })
        .unwrap()
    }

    fn ops(s: &PhysicsScene) -> Vec<Op> {
        s.log.take()
    }

    /// `PhysicsFrame` with the world pass: gravity (0x46F7D9), the pose pass
    /// (0x46FCB1, mode 0 while a settle is pending), the kinematic sync
    /// (0x46FD4D), the main step of the budget, with a settle three reseats
    /// each followed by a 1/60 step (0x46FDF7, 0x46FE0C), the readback
    /// (0x46FE49) and the second pose pass (0x46FE93).
    fn world_pass(mode: i32, budget: f32, settle: bool) -> Vec<Op> {
        let mut v = vec![
            Gravity,
            Pose(0, if settle { 0 } else { mode }),
            Sync,
            Step(budget),
        ];
        if settle {
            for _ in 0..3 {
                v.extend([Reseat, Step(SUBSTEP)]);
            }
        }
        v.extend([Readback, Pose(1, mode)]);
        v
    }

    /// One substep of BLOCK 2 (`playback_catchup.cpp`, 0x46F416..0x46F55C).
    fn substep(mode: i32) -> [Op; 4] {
        [Keys, Pose(0, mode), Sync, Step(SUBSTEP)]
    }

    #[test]
    fn stopped_pumps_step_the_world_by_the_pump_time() {
        // `PhysicsFrame` gate `count == 1 || count == 2`; the budget is the
        // pump's `deltaTime` (`PlaybackCatchup`, 0x46EFDE, returning at
        // `PlaybackActive() == 0`).
        for mode in [1, 2] {
            let mut s = open(mode as u8);
            s.tick(0.0).unwrap();
            assert_eq!(ops(&s), world_pass(mode, 0.0, true), "mode {mode}");
            s.tick(0.02).unwrap();
            assert_eq!(ops(&s), world_pass(mode, 0.02, false), "mode {mode}");
        }
    }

    #[test]
    fn the_wind_timer_runs_on_the_pump_time() {
        // The noise block (0x46F582): the timer adds `DeltaTime` and a new
        // gravity fires when it is strictly above 0.5, replacing the normal
        // per-pass gravity.
        let mut s = open_with(2, 1);
        s.tick(0.0).unwrap();
        ops(&s);
        s.tick(0.25).unwrap();
        s.tick(0.25).unwrap();
        assert!(!ops(&s).contains(&Gravity));
        s.tick(0.01).unwrap();
        assert_eq!(ops(&s), world_pass(2, 0.01, false));
        assert_eq!(s.gravity_noise_timer, 0.0);
    }

    #[test]
    fn mode_3_steps_while_stopped_only_to_settle() {
        // `count == 3 && (moved || settle || frameAdv)`.
        let mut s = open(3);
        s.tick(0.0).unwrap();
        assert_eq!(ops(&s), world_pass(3, 0.0, true));
        s.tick(0.02).unwrap();
        assert_eq!(ops(&s), [Gravity, Pose(0, 3), Pose(1, 3)]);
    }

    #[test]
    fn physics_off_only_poses_and_keeps_the_settle_request() {
        // `count > 0` gates gravity; the request clears only inside the
        // world pass (0x46FE2D).
        let mut s = open(0);
        s.tick(0.02).unwrap();
        assert_eq!(ops(&s), [Pose(0, 0), Pose(1, 0)]);
        assert!(s.settle);
    }

    #[test]
    fn a_seek_settles_on_the_next_pump_only() {
        // HandleLButtonDown_FrameStripHit and RefreshAfterFrameApply end
        // with `PhysicsResetPending() = 1`.
        let mut s = open(2);
        s.tick(0.0).unwrap();
        ops(&s);
        s.seek(10);
        s.tick(0.02).unwrap();
        assert_eq!(ops(&s), world_pass(2, 0.02, true));
        s.tick(0.02).unwrap();
        assert_eq!(ops(&s), world_pass(2, 0.02, false));
    }

    #[test]
    fn frame_steps_settle_by_the_rule_of_refresh_timeline() {
        // ui_frame_step.cpp RefreshTimeline: forward assigns `mode == 3`,
        // back sets the request in mode 3 only.
        let mut s = open(2);
        s.seek(5);
        s.step_frame(6, true);
        assert!(!s.settle, "forward clears a pending settle in mode 2");
        s.step_frame(5, false);
        assert!(!s.settle);
        s.seek(5);
        s.step_frame(4, false);
        assert!(s.settle, "back keeps a pending settle");

        let mut s = open(3);
        s.tick(0.0).unwrap();
        s.step_frame(1, true);
        assert!(s.settle);
        s.tick(0.0).unwrap();
        s.step_frame(0, false);
        assert!(s.settle);
    }

    #[test]
    fn playback_substeps_are_paid_from_the_pump_time() {
        // BLOCK 2: cursor += 1/60, then a substep while cursor < target,
        // each `g_CatchupDtBudget -= 1/60` (x64 0x7FF7CB44BE57); the main
        // step takes what is left, negative here as in the C++.
        let mut s = open(2);
        s.tick(0.0).unwrap();
        s.start_playback(0.0, true);
        ops(&s);
        let (target, dt) = (3.5 * SUBSTEP, 0.03);
        s.catch_up(target, dt).unwrap();
        let mut budget = dt;
        let mut expected = Vec::new();
        for _ in 0..3 {
            expected.extend(substep(2));
            budget -= SUBSTEP;
        }
        assert!(budget < 0.0);
        expected.push(Keys);
        expected.extend(world_pass(2, budget, false));
        assert_eq!(ops(&s), expected);
        assert_eq!(s.scene.cursor, target);
    }

    #[test]
    fn mode_3_playback_steps_every_pump() {
        // `frameAdv` (`PlaybackActive`) opens the mode 3 world pass.
        let mut s = open(3);
        s.tick(0.0).unwrap();
        s.start_playback(0.0, true);
        ops(&s);
        s.catch_up(SUBSTEP, 0.02).unwrap();
        let mut expected = vec![Keys];
        expected.extend(world_pass(3, 0.02, false));
        assert_eq!(ops(&s), expected);
    }

    #[test]
    fn physics_off_playback_has_no_substeps() {
        // BLOCK 2 is gated on `count >= 1`.
        let mut s = open(0);
        s.start_playback(0.0, true);
        s.catch_up(0.1, 0.1).unwrap();
        assert_eq!(ops(&s), [Keys, Pose(0, 0), Pose(1, 0)]);
        assert_eq!(s.scene.cursor, 0.1);
    }

    #[test]
    fn play_start_settles_unless_the_frame_is_unchanged() {
        // UpdateBoneFrames: `PlaybackFrameChanged` clears instead of
        // requesting a settle (playback_state.cpp, 0x433A40).
        let mut s = open(2);
        s.tick(0.0).unwrap();
        s.start_playback(1.0, false);
        assert!(s.settle && s.playing());
        assert_eq!(s.scene.cursor, 1.0);
        let mut s = open(2);
        s.tick(0.0).unwrap();
        s.start_playback(1.0, true);
        assert!(!s.settle);
    }

    #[test]
    fn always_on_off_plays_in_mode_2() {
        // UpdateBoneFrames saves the mode and switches to 2; StopPlayback and
        // the loop restart put the saved mode back first.
        let mut s = open(3);
        s.always_on_off = true;
        s.start_playback(0.0, true);
        assert_eq!(s.scene.physics_mode, 2);
        s.loop_restart(0.0, 0.02).unwrap();
        assert_eq!(s.scene.physics_mode, 2);
        s.stop_playback(0);
        assert_eq!(s.scene.physics_mode, 3);
    }

    #[test]
    fn a_loop_restart_settles_with_no_substeps() {
        // PlayingBeyondEnd: cursor = start, UpdateBoneFrames (the flag was
        // consumed at play start), PlaybackPoseAdvance(0), no BLOCK 2.
        let mut s = open(2);
        s.tick(0.0).unwrap();
        s.start_playback(0.0, true);
        s.catch_up(0.5, 0.5).unwrap();
        ops(&s);
        s.loop_restart(0.0, 0.02).unwrap();
        let mut expected = vec![Keys];
        expected.extend(world_pass(2, 0.02, true));
        assert_eq!(ops(&s), expected);
        assert_eq!(s.scene.cursor, 0.0);
    }

    #[test]
    fn a_stop_settles_on_the_next_stopped_pump() {
        // StopPlayback ends with `PhysicsResetPending() = 1`; the pump of a
        // stop past the end runs PhysicsFrame with PlaybackActive cleared.
        let mut s = open(2);
        s.tick(0.0).unwrap();
        assert!(s.catch_up(0.1, 0.1).is_err());
        s.start_playback(0.0, true);
        assert!(s.tick(0.02).is_err());
        s.catch_up(0.1, 0.1).unwrap();
        s.stop_playback(3);
        assert!(!s.playing());
        ops(&s);
        s.tick(0.02).unwrap();
        assert_eq!(ops(&s), world_pass(2, 0.02, true));
    }

    #[test]
    fn the_reset_menu_settles() {
        // Menu 268: `PhysicsResetPending() = 1`.
        let mut s = open(2);
        s.tick(0.0).unwrap();
        s.reset();
        ops(&s);
        s.tick(0.02).unwrap();
        assert_eq!(ops(&s), world_pass(2, 0.02, true));
    }

    #[test]
    fn the_physics_menus_set_the_mode_and_sync() {
        // command_view_menu.cpp 1048-1110: `PlaybackPhysicsMode() = n`, then
        // ModelKinematicSync over the model slots; stop restores the new mode.
        let mut s = open(2);
        s.tick(0.0).unwrap();
        ops(&s);
        s.set_physics_mode(3).unwrap();
        assert_eq!(ops(&s), [Sync]);
        assert_eq!((s.scene.physics_mode, s.saved_mode), (3, 3));
        s.start_playback(0.0, true);
        s.stop_playback(0);
        assert_eq!(s.scene.physics_mode, 3);
        s.tick(0.02).unwrap();
        ops(&s);
        s.set_physics_mode(0).unwrap();
        assert!(!s.settle, "the settle request is the document's");
        s.tick(0.02).unwrap();
        assert_eq!(ops(&s), [Sync, Pose(0, 0), Pose(1, 0)]);
    }

    /// Drops a unit box (half extent 1) from y = 20, away from the model and
    /// colliding with the ground alone, for two seconds; its final pose.
    fn drop_box(s: &PhysicsScene) -> ([f32; 3], [f32; 4]) {
        let mut body = ptr::null_mut();
        // SAFETY: the world is live; the arrays outlive the calls.
        unsafe {
            let code = sys::mds_mmd_body_create(
                s.world.0,
                1,
                1.0,
                1.0,
                1.0,
                [500.0, 20.0, 500.0].as_ptr(),
                [0.0, 0.0, 0.0, 1.0].as_ptr(),
                1,
                1.0,
                0.0,
                0.0,
                0.0,
                0.5,
                0x4000,
                i16::MIN,
                &mut body,
            );
            assert_eq!(code, sys::MDS_BT_OK);
        }
        for _ in 0..120 {
            s.world_step(SUBSTEP).unwrap();
        }
        let (mut origin, mut rotation) = ([0.0; 3], [0.0; 4]);
        // SAFETY: a live body of this world.
        let code =
            unsafe { sys::mds_mmd_body_pose(body, origin.as_mut_ptr(), rotation.as_mut_ptr()) };
        assert_eq!(code, sys::MDS_BT_OK);
        (origin, rotation)
    }

    #[test]
    fn the_floor_menu_switches_the_ground_contact() {
        let rest = drop_box(&open(1));
        assert!(
            (rest.0[1] - 1.0).abs() < 0.05,
            "rests on the floor: {rest:?}"
        );

        let mut s = open(1);
        s.set_floor_visible(false).unwrap();
        let fallen = drop_box(&s).0[1];
        // Free fall from 20 under -98 for 2 s ends near -176.
        assert!(fallen < -150.0, "falls through: {fallen}");

        let mut s = open(1);
        s.set_floor_visible(false).unwrap();
        s.set_floor_visible(true).unwrap();
        assert_eq!(drop_box(&s), rest, "1 is the startup flag value");
    }

    #[test]
    fn rand_is_the_msvc_sequence() {
        let mut r = MsvcRand(1);
        let first: Vec<i32> = (0..4).map(|_| r.next()).collect();
        assert_eq!(first, [41, 18467, 6334, 26500]);
    }
}
